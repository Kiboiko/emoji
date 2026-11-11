from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import func, select

from config import settings
from models.category import Category
from models.finance import LedgerEntry
from models.p2p import ListingStatus, ProductListing, SellerProfile
from models.product import Product
from models.promotion import ProductPromotion, PromotionInvoice
from services import finance_service, promotion_service, settings_service, ton_service


@pytest.fixture
async def promotion_product(db, user_factory, monkeypatch):
    monkeypatch.setattr(settings, "TON_RECEIVING_ADDRESS", "test-receiving-wallet")
    user = await user_factory()
    category = Category(id=uuid.uuid4(), name_ru="Категория", name_en="Category")
    seller = SellerProfile(id=uuid.uuid4(), user_id=user.id, display_name="Seller", payout_wallet="wallet")
    db.add_all([category, seller])
    await db.flush()
    product = Product(id=uuid.uuid4(), name_ru="Товар", name_en="Product", description_ru="Описание",
        description_en="Description", image_url="/image.jpg", price_usdt=Decimal("10"),
        category_id=category.id, owner_user_id=user.id, is_p2p=True, stock=2)
    db.add(product)
    await db.flush()
    db.add(ProductListing(seller_id=seller.id, product_id=product.id, category_id=category.id,
        name="Product", description="Description", price_usd=Decimal("10"), status=ListingStatus.APPROVED))
    await db.flush()
    return user, product


def transfer(invoice, *, amount=None, timestamp=None, tx_hash="promo-tx"):
    return ton_service.OnChainTx(tx_hash=tx_hash, lt=1,
        utime=timestamp or int(datetime.now(timezone.utc).timestamp()), source="sender",
        value_nano=amount if amount is not None else invoice.amount_nano, comment=invoice.payment_comment)


async def test_invoice_retry_and_price_snapshot(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    assert invoice.amount_nano == 300_000_000
    assert invoice.duration_hours == 24
    assert invoice.payment_comment.startswith("PROMO-")
    assert (await promotion_service.create_invoice(db, product.id, user)).id == invoice.id
    await settings_service.set_setting(db, "promotion_price_nano", 400_000_000)
    assert (await promotion_service.create_invoice(db, product.id, user)).amount_nano == 300_000_000
    assert promotion_service.serialize(invoice)["payment"]["amount_nano"] == "300000000"


async def test_payment_atomic_idempotency_extension_and_overpay(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    tx = transfer(invoice, amount=invoice.amount_nano + 5)
    await promotion_service.verify_invoice(db, invoice.id, [tx])
    until = invoice.promoted_until
    assert invoice.status == "confirmed" and invoice.credited_nano == 5
    assert (await finance_service.user_account(db, user.id, "TON")).balance_minor == 5
    assert (await finance_service.platform_account(db, "TON")).balance_minor == 300_000_000
    await promotion_service.verify_invoice(db, invoice.id, [tx])
    assert invoice.promoted_until == until
    second = await promotion_service.create_invoice(db, product.id, user)
    await promotion_service.verify_invoice(db, second.id, [transfer(second, tx_hash="second-tx")])
    assert second.promoted_until == until + timedelta(hours=24)
    assert (await finance_service.reconcile(db)).ok


@pytest.mark.parametrize("reason", ["underpaid", "late", "ineligible"])
async def test_unsuitable_payment_credited_without_promotion(db, promotion_product, reason):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    amount = 12 if reason == "underpaid" else invoice.amount_nano
    timestamp = int((invoice.expires_at + timedelta(hours=4)).replace(tzinfo=timezone.utc).timestamp()) if reason == "late" else None
    if reason == "ineligible":
        product.is_active = False
        await db.flush()
    await promotion_service.verify_invoice(db, invoice.id, [transfer(invoice, amount=amount, timestamp=timestamp)])
    assert invoice.status == "credited_to_balance" and invoice.credit_reason == reason
    assert invoice.credited_nano == amount
    assert await db.get(ProductPromotion, product.id) is None
    assert (await finance_service.user_account(db, user.id, "TON")).balance_minor == amount
    await promotion_service.verify_invoice(db, invoice.id, [])
    assert (await finance_service.user_account(db, user.id, "TON")).balance_minor == amount
    assert (await finance_service.reconcile(db)).ok


async def test_foreign_owner_and_inactive_listing_rejected(db, promotion_product, user_factory):
    user, product = promotion_product
    other = await user_factory()
    with pytest.raises(promotion_service.PromotionError):
        await promotion_service.create_invoice(db, product.id, other)
    product.is_active = False
    with pytest.raises(promotion_service.PromotionError):
        await promotion_service.create_invoice(db, product.id, user)


async def test_old_wrong_comment_tx_and_changed_network_never_confirm(db, promotion_product, monkeypatch):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    old = transfer(invoice, timestamp=int((invoice.created_at - timedelta(days=2)).replace(tzinfo=timezone.utc).timestamp()))
    wrong = transfer(invoice)
    wrong.comment = "MP-not-a-promotion"
    await promotion_service.verify_invoice(db, invoice.id, [old, wrong])
    assert invoice.status == "pending"
    monkeypatch.setattr(settings, "TON_RECEIVING_ADDRESS", "changed-wallet")
    with pytest.raises(ton_service.TonError):
        await promotion_service.verify_invoice(db, invoice.id, [transfer(invoice)])
    assert await db.get(ProductPromotion, product.id) is None


async def test_confirm_delay_and_expired_recovery(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    await settings_service.set_setting(db, "ton_min_confirm_sec", 30)
    tx = transfer(invoice)
    await promotion_service.verify_invoice(db, invoice.id, [tx])
    assert invoice.status == "seen"
    assert await db.get(ProductPromotion, product.id) is None
    invoice.seen_at -= timedelta(seconds=31)
    await db.flush()
    await promotion_service.verify_invoice(db, invoice.id, [tx])
    assert invoice.status == "confirmed"


async def test_same_hash_cannot_credit_two_promotions(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    await promotion_service.verify_invoice(db, invoice.id, [transfer(invoice)])
    second = await promotion_service.create_invoice(db, product.id, user)
    with pytest.raises(promotion_service.PromotionError):
        await promotion_service.verify_invoice(db, second.id, [transfer(second)])
    assert (await db.execute(select(func.count()).select_from(LedgerEntry))).scalar_one() == 2


async def test_failure_rolls_back_ledger_and_promotion(db, promotion_product, monkeypatch):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    original_id = invoice.id
    await db.commit()
    original_deposit = finance_service.deposit_from_external

    async def fail_after_deposit(*args, **kwargs):
        await original_deposit(*args, **kwargs)
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr(finance_service, "deposit_from_external", fail_after_deposit)
    with pytest.raises(RuntimeError):
        await promotion_service.verify_invoice(db, original_id, [transfer(invoice)])
    await db.rollback()
    persisted = await db.get(PromotionInvoice, original_id)
    assert persisted.status == "pending"
    assert (await db.execute(select(func.count()).select_from(LedgerEntry))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(ProductPromotion))).scalar_one() == 0


async def test_payment_just_after_expiry_is_credited(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    timestamp = int((invoice.expires_at + timedelta(seconds=30)).replace(tzinfo=timezone.utc).timestamp())
    await promotion_service.verify_invoice(db, invoice.id, [transfer(invoice, timestamp=timestamp)])
    assert invoice.status == "credited_to_balance" and invoice.credit_reason == "late"
    assert await db.get(ProductPromotion, product.id) is None
    assert (await finance_service.user_account(db, user.id, "TON")).balance_minor == invoice.amount_nano


async def test_seen_transfer_cannot_be_replaced(db, promotion_product):
    user, product = promotion_product
    invoice = await promotion_service.create_invoice(db, product.id, user)
    await settings_service.set_setting(db, "ton_min_confirm_sec", 30)
    original = transfer(invoice, tx_hash="original")
    await promotion_service.verify_invoice(db, invoice.id, [original])
    invoice.seen_at -= timedelta(seconds=31)
    await db.flush()
    await promotion_service.verify_invoice(db, invoice.id, [transfer(invoice, tx_hash="replacement")])
    assert invoice.tx_hash == "original" and invoice.status != "confirmed"
    await promotion_service.verify_invoice(db, invoice.id, [original])
    assert invoice.status == "confirmed" and invoice.tx_hash == "original"


# Exercise actual FastAPI dependencies, ownership and consent, not only service calls.
from test_http_wiring import client, _bearer

async def test_promotion_http_consent_ownership_and_server_confirmation(client, db, promotion_product, user_factory, monkeypatch):
    from unittest.mock import AsyncMock
    from services import terms_service
    user, product = promotion_product
    stranger = await user_factory()
    headers = _bearer(user)
    url = f"/api/promotions/products/{product.id}/invoice"
    assert (await client.post(url)).status_code == 401
    assert (await client.post(url, headers=headers)).status_code == 400
    await terms_service.record(db, user, context="promotion")
    await db.commit()
    created = await client.post(url, headers=headers)
    assert created.status_code == 200
    invoice = created.json()
    assert invoice["status"] == "pending" and not invoice["paid"]
    assert invoice["payment"]["amount_nano"] == "300000000"
    assert (await client.post(url, headers=headers)).json()["id"] == invoice["id"]
    check = f"/api/promotions/{invoice['id']}/check"
    assert (await client.get(check, headers=_bearer(stranger))).status_code == 403
    monkeypatch.setattr(ton_service, "fetch_incoming_transactions", AsyncMock(return_value=[]))
    assert not (await client.get(check, headers=headers)).json()["paid"]
    assert await db.get(ProductPromotion, product.id) is None
    config = (await client.get("/api/promotions/config")).json()
    assert Decimal(config["price_ton"]) == Decimal("0.3")


async def test_promotion_can_continue_after_accepting_current_terms_page(client, db, promotion_product):
    user, product = promotion_product
    await settings_service.set_setting(db, "terms_version", "1.2")
    await settings_service.set_setting(db, "terms_text", "Current promotion terms")
    headers = _bearer(user)
    url = f"/api/promotions/products/{product.id}/invoice"
    denied = await client.post(url, headers=headers)
    assert denied.status_code == 400
    assert denied.json()["detail"] == {"code":"terms_required", "version":"1.2"}
    assert await db.scalar(select(func.count()).select_from(PromotionInvoice)) == 0
    terms = (await client.get('/api/terms', headers=headers)).json()
    assert terms['text'] == 'Current promotion terms'
    stale = await client.post('/api/terms/accept', headers=headers, json={'version':'1.1'})
    assert not stale.json()['accepted']
    assert (await client.post(url, headers=headers)).status_code == 400
    accepted = await client.post('/api/terms/accept', headers=headers, json={'version':terms['version']})
    assert accepted.json()['accepted']
    created = await client.post(url, headers=headers)
    assert created.status_code == 200 and created.json()['status'] == 'pending'
    assert await db.get(ProductPromotion, product.id) is None
