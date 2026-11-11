"""Redirect earned commission, funded from the platform account, never from seller escrow."""
import secrets
from sqlalchemy import select
from models.partner import PartnerLink, PartnerAttribution, PartnerCommission
from models.finance import LedgerEntryType, LedgerRefType
from models.order import OrderItem
from services import finance_service, settings_service
from services.money import to_minor, split_by_bp


async def attribution(db, buyer_id):
    return await db.scalar(select(PartnerLink).join(PartnerAttribution, PartnerAttribution.link_id == PartnerLink.id)
                           .where(PartnerAttribution.buyer_id == buyer_id))


def new_code():
    return "sp_" + secrets.token_urlsafe(12)


async def pay_commission(db, *, buyer_id, order_id, source_kind, source_id, amount_nano):
    if amount_nano <= 0: return False
    link = await attribution(db, buyer_id)
    if link is None: return False
    # Existing attribution survives disabling the link; disabling stops new signups.
    platform = await finance_service.platform_account(db, "TON")
    recipient = await finance_service.user_account(db, link.beneficiary_id, "TON")
    result = await finance_service.post(db, ref_type=LedgerRefType.DEAL if source_kind == "deal" else LedgerRefType.ORDER,
        ref_id=source_id if source_kind == "deal" else order_id,
        postings=[
            finance_service.Posting(account=platform, entry_type=LedgerEntryType.REFERRAL_ACCRUAL,
                amount_minor=-amount_nano, key_suffix=f"partner:{source_kind}:{source_id}:src"),
            finance_service.Posting(account=recipient, entry_type=LedgerEntryType.REFERRAL_ACCRUAL,
                amount_minor=amount_nano, key_suffix=f"partner:{source_kind}:{source_id}:dst"),
        ], comment="Комиссия по специальной реферальной ссылке")
    if result.already_applied: return False
    db.add(PartnerCommission(link_id=link.id, buyer_id=buyer_id, beneficiary_id=link.beneficiary_id,
        order_id=order_id, source_kind=source_kind, source_id=source_id, amount_nano=amount_nano))
    await db.flush()
    return True


async def platform_products(db, order, buyer, received_nano):
    """Own products have no seller commission. Preserve their ordinary L1 rate,
    but fund it from platform revenue and do not add a second-level payout."""
    if received_nano <= 0: return
    allowed = await settings_service.get_list(db, "referral_applies_to")
    if "product" not in allowed: return
    bp = await settings_service.get_int(db, "referral_l1_bp")
    items = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    total = sum(to_minor(item.price_usdt * item.quantity, "USD") for item in items)
    if total <= 0: return
    for item in items:
        snapshot = item.product_snapshot or {}
        if snapshot.get("is_p2p") or snapshot.get("type") == "subscription": continue
        amount = received_nano * to_minor(item.price_usdt * item.quantity, "USD") // total
        reward, _ = split_by_bp(amount, bp)
        await pay_commission(db, buyer_id=buyer.id, order_id=order.id, source_kind="product",
                             source_id=item.id, amount_nano=reward)
