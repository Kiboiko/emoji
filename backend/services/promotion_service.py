"""Promotion bought only with a verified external TON transfer.

All mutations (ledger, invoice and promotion) share the caller's transaction.
Product row locking serializes invoice creation and duration extensions.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
import uuid

from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.finance import LedgerRefType
from models.p2p import ListingStatus, ProductListing, SellerProfile, SellerStatus
from models.payment import Payment
from models.product import Product
from models.promotion import ProductPromotion, PromotionInvoice
from models.user import User
from services import finance_service, settings_service, ton_service

TERMINAL = ("confirmed", "credited_to_balance")


class PromotionError(ValueError):
    pass


def active_promotion_expression(cutoff: datetime | None = None):
    return exists(select(ProductPromotion.product_id).where(
        ProductPromotion.product_id == Product.id,
        ProductPromotion.promoted_until > (cutoff or datetime.utcnow()),
    ))


async def eligible(db: AsyncSession, product: Product | None, user_id: uuid.UUID) -> bool:
    if product is None or not product.is_active or not product.is_p2p:
        return False
    if product.owner_user_id != user_id or (product.stock is not None and product.stock <= 0):
        return False
    return bool((await db.execute(select(ProductListing.id).join(
        SellerProfile, SellerProfile.id == ProductListing.seller_id,
    ).join(User, User.id == SellerProfile.user_id).where(
        ProductListing.product_id == product.id,
        ProductListing.status == ListingStatus.APPROVED,
        SellerProfile.user_id == user_id,
        SellerProfile.status == SellerStatus.ACTIVE,
        User.is_blocked.is_(False),
    ).limit(1))).scalar_one_or_none())


async def create_invoice(db: AsyncSession, product_id: uuid.UUID, user: User) -> PromotionInvoice:
    product = (await db.execute(select(Product).where(Product.id == product_id).with_for_update())).scalar_one_or_none()
    if not await eligible(db, product, user.id):
        raise PromotionError("Продвигать можно только свой активный одобренный товар")
    now = datetime.utcnow()
    existing = (await db.execute(select(PromotionInvoice).where(
        PromotionInvoice.product_id == product_id,
        PromotionInvoice.user_id == user.id,
        PromotionInvoice.status.in_(["pending", "seen"]),
    ).order_by(PromotionInvoice.created_at.desc()))).scalars().first()
    if existing is not None:
        if existing.status == "seen" or existing.expires_at > now:
            return existing
        existing.status = "expired"
    invoice = PromotionInvoice(
        id=uuid.uuid4(), product_id=product_id, user_id=user.id,
        amount_nano=await settings_service.get_int(db, "promotion_price_nano"),
        duration_hours=await settings_service.get_int(db, "promotion_duration_hours"),
        destination_address=ton_service.require_receiving_address(),
        network="testnet" if settings.ton_is_testnet else "mainnet",
        payment_comment=f"PROMO-{secrets.token_hex(12).upper()}",
        created_at=now, expires_at=now + timedelta(minutes=await settings_service.get_int(db, "order_payment_ttl_min")),
        status="pending", credited_nano=0,
    )
    db.add(invoice)
    await db.flush()
    return invoice


def serialize(invoice: PromotionInvoice) -> dict:
    payment = None
    if invoice.status in ("pending", "seen") and invoice.expires_at > datetime.utcnow():
        payment = {
            "address": invoice.destination_address, "amount_nano": str(invoice.amount_nano),
            "amount_ton": str(Decimal(invoice.amount_nano) / ton_service.NANO),
            "comment": invoice.payment_comment,
            "valid_until": int(invoice.expires_at.replace(tzinfo=timezone.utc).timestamp()),
            "network": invoice.network,
        }
    return {
        "id": str(invoice.id), "product_id": str(invoice.product_id) if invoice.product_id else None,
        "status": invoice.status, "paid": invoice.status == "confirmed",
        "promoted_until": invoice.promoted_until.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if invoice.promoted_until else None,
        "credited_nano": str(invoice.credited_nano),
        "credit_reason": invoice.credit_reason, "payment": payment,
    }


async def verify_invoice(db: AsyncSession, invoice_id: uuid.UUID, txs: list | None = None) -> PromotionInvoice:
    initial = await db.get(PromotionInvoice, invoice_id)
    if initial is None:
        raise PromotionError("Счёт не найден")
    # Lock order matches create_invoice (product, then invoice), avoiding deadlocks.
    product = (await db.execute(select(Product).where(Product.id == initial.product_id).with_for_update())).scalar_one_or_none()
    invoice = (await db.execute(select(PromotionInvoice).where(
        PromotionInvoice.id == invoice_id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if invoice.status in TERMINAL:
        return invoice
    current_network = "testnet" if settings.ton_is_testnet else "mainnet"
    if invoice.network != current_network or invoice.destination_address != ton_service.require_receiving_address():
        raise ton_service.TonError("Invoice network/address differs from the configured indexer")
    if txs is None:
        txs = await ton_service.fetch_incoming_transactions()
    start, end = ton_service.payment_window(invoice.created_at, invoice.expires_at)
    # Preserve even very late/underpaid transfers: credit them, never silently drop.
    candidates = [tx for tx in txs if tx.comment == invoice.payment_comment
                  and tx.tx_hash and tx.value_nano > 0 and tx.utime >= int(start.replace(tzinfo=timezone.utc).timestamp())]
    if invoice.tx_hash:
        # A confirmation hold belongs to one actual transfer, never a replacement.
        candidates = [tx for tx in candidates if tx.tx_hash == invoice.tx_hash]
        txs = candidates
    match = ton_service.match_payment(txs, comment=invoice.payment_comment,
        expected_nano=invoice.amount_nano, window_start=start.replace(tzinfo=timezone.utc), window_end=end.replace(tzinfo=timezone.utc))
    tx = match.tx if match.matched else min(candidates, key=lambda t: t.lt, default=None)
    now = datetime.utcnow()
    if tx is None:
        if invoice.expires_at < now:
            invoice.status = "expired"
        return invoice
    # Serialize claims across promotion invoices. MP and PROMO comments cannot match
    # the same actual transaction; additionally reject hashes already used by orders.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "ton-tx:" + tx.tx_hash})
    used = (await db.execute(select(Payment.id).where(Payment.tx_hash == tx.tx_hash))).first()
    other = (await db.execute(select(PromotionInvoice.id).where(
        PromotionInvoice.tx_hash == tx.tx_hash, PromotionInvoice.id != invoice.id,
    ))).first()
    if used or other:
        raise PromotionError("Транзакция уже использована другим платежом")
    invoice.tx_hash, invoice.received_nano = tx.tx_hash, tx.value_nano
    invoice.seen_at = invoice.seen_at or now
    if (now - invoice.seen_at).total_seconds() < await settings_service.get_int(db, "ton_min_confirm_sec"):
        invoice.status = "seen"
        await db.flush()
        return invoice
    reason = ("underpaid" if tx.value_nano < invoice.amount_nano else
              "late" if tx.utime > int(invoice.expires_at.replace(tzinfo=timezone.utc).timestamp()) else
              "ineligible" if not await eligible(db, product, invoice.user_id) else None)
    platform_amount = 0 if reason else invoice.amount_nano
    credit = tx.value_nano - platform_amount
    if platform_amount:
        await finance_service.deposit_from_external(db,
            account=await finance_service.platform_account(db, "TON"), amount_minor=platform_amount,
            ref_type=LedgerRefType.PROMOTION, ref_id=invoice.id, key_suffix="promotion",
            comment=f"Продвижение товара {invoice.product_id}; tx {tx.tx_hash}")
        promotion = await db.get(ProductPromotion, invoice.product_id)
        if promotion is None:
            promotion = ProductPromotion(product_id=invoice.product_id, promoted_until=now)
            db.add(promotion)
        promotion.promoted_until = max(now, promotion.promoted_until) + timedelta(hours=invoice.duration_hours)
        invoice.promoted_until = promotion.promoted_until
    if credit:
        await finance_service.deposit_from_external(db,
            account=await finance_service.user_account(db, invoice.user_id, "TON"), amount_minor=credit,
            ref_type=LedgerRefType.PROMOTION, ref_id=invoice.id, key_suffix="credit",
            comment=f"Возврат оплаты продвижения ({reason or 'overpaid'}); tx {tx.tx_hash}")
    invoice.credited_nano, invoice.credit_reason = credit, reason or ("overpaid" if credit else None)
    invoice.status = "credited_to_balance" if reason else "confirmed"
    invoice.completed_at = now
    await db.flush()
    return invoice


async def poll_invoices(db: AsyncSession) -> int:
    # Fetch once and also find expired invoices by comments, regardless of age.
    if not (await db.execute(select(PromotionInvoice.id).where(
        PromotionInvoice.status.not_in(TERMINAL)).limit(1))).first():
        return 0
    txs = await ton_service.fetch_incoming_transactions()
    comments = [tx.comment for tx in txs if tx.comment.startswith("PROMO-")]
    ids = (await db.execute(select(PromotionInvoice.id).where(
        PromotionInvoice.status.not_in(TERMINAL),
        or_(PromotionInvoice.status.in_(["pending", "seen"]), PromotionInvoice.payment_comment.in_(comments)),
    ))).scalars().all()
    for invoice_id in ids:
        try:
            await verify_invoice(db, invoice_id, txs)
            await db.commit()
        except Exception:
            await db.rollback()
            import logging
            logging.getLogger(__name__).exception("Promotion invoice verification failed: %s", invoice_id)
    return len(ids)
