"""
Условия площадки, закрытие заказа по сделкам, отзывы о продавце.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.order import OrderItem, OrderStatus
from models.p2p import Deal, DealStatus, SellerProfile, TermsAcceptance
from services import deal_service, settings_service, terms_service

pytestmark = pytest.mark.asyncio


class TestTerms:
    async def test_purchase_blocked_without_acceptance(self, db, user_factory):
        user = await user_factory()
        with pytest.raises(terms_service.TermsNotAccepted):
            await terms_service.require(db, user, accepted_now=False, context="purchase")

    async def test_checkbox_records_acceptance(self, db, user_factory):
        user = await user_factory()
        await terms_service.require(db, user, accepted_now=True, context="purchase")
        await db.flush()

        record = (
            await db.execute(select(TermsAcceptance).where(TermsAcceptance.user_id == user.id))
        ).scalars().one()
        assert record.context == "purchase"
        # telegram_id дублируется: запись должна пережить удаление аккаунта
        assert record.telegram_id == user.telegram_id

    async def test_asked_once_per_version_not_every_purchase(self, db, user_factory):
        """
        Галочка на каждом заказе приучает щёлкать не читая. Приняв текущую
        редакцию, пользователь покупает дальше без повторного вопроса.
        """
        user = await user_factory()
        await terms_service.require(db, user, accepted_now=True, context="purchase")
        await db.flush()

        # Второй заказ без галочки проходит
        await terms_service.require(db, user, accepted_now=False, context="purchase")

    async def test_new_version_requires_new_acceptance(self, db, user_factory):
        """Владелец обновил текст и повысил версию — согласие со старой не действует."""
        user = await user_factory()
        await terms_service.require(db, user, accepted_now=True, context="purchase")
        await db.flush()

        await settings_service.set_setting(db, "terms_version", "2.0")
        try:
            with pytest.raises(terms_service.TermsNotAccepted) as exc:
                await terms_service.require(db, user, accepted_now=False, context="purchase")
            assert exc.value.version == "2.0"
        finally:
            settings_service.invalidate_cache()


@pytest.fixture
async def p2p_parties(db, user_factory):
    buyer = await user_factory(username="rv_buyer")
    seller = await user_factory(username="rv_seller")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=seller.id,
        display_name="Продавец", payout_wallet="EQWallet",
    ))
    await db.flush()
    return buyer, seller


async def _deal(db, order, buyer, seller, status):
    deal = Deal(
        id=uuid.uuid4(), order_id=order.id,
        buyer_id=buyer.id, seller_id=seller.id,
        product_name="Товар",
        amount_nano=1_000, commission_nano=20, seller_amount_nano=980,
        status=status,
        confirm_deadline_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(deal)
    await db.flush()
    return deal


class TestOrderSettlement:
    async def test_order_closes_when_all_deals_final(self, db, p2p_parties, order_factory):
        """
        Без этого заказ с P2P-товаром висел бы в PAID вечно: отзыв по нему
        было бы не оставить, а в отчётах он выглядел бы незакрытым.
        """
        buyer, seller = p2p_parties
        order = await order_factory(buyer, status=OrderStatus.PAID)
        await _deal(db, order, buyer, seller, DealStatus.RELEASED)
        await _deal(db, order, buyer, seller, DealStatus.REFUNDED)

        assert await deal_service.complete_order_if_settled(db, order.id) is True
        assert order.status == OrderStatus.COMPLETED

    async def test_order_stays_paid_while_a_deal_is_open(self, db, p2p_parties, order_factory):
        buyer, seller = p2p_parties
        order = await order_factory(buyer, status=OrderStatus.PAID)
        await _deal(db, order, buyer, seller, DealStatus.RELEASED)
        await _deal(db, order, buyer, seller, DealStatus.DELIVERED_CLAIMED)

        assert await deal_service.complete_order_if_settled(db, order.id) is False
        assert order.status == OrderStatus.PAID

    async def test_pending_service_keeps_order_open(self, db, p2p_parties, order_factory):
        """Услугу закрывает админ отдельно — сделки не должны закрывать заказ за него."""
        buyer, seller = p2p_parties
        order = await order_factory(buyer, status=OrderStatus.PAID)
        await _deal(db, order, buyer, seller, DealStatus.RELEASED)
        db.add(OrderItem(
            id=uuid.uuid4(), order_id=order.id, product_id=None, quantity=1,
            price_usdt=Decimal("1.00"),
            product_snapshot={"name_ru": "Услуга", "type": "service"},
        ))
        await db.flush()

        assert await deal_service.complete_order_if_settled(db, order.id) is False
        assert order.status == OrderStatus.PAID
