"""
P2P-сделки: escrow, переходы состояний, споры.

Самая денежная логика в проекте: между оплатой и подтверждением средства
покупателя удерживаются платформой, и ошибка здесь означает либо потерянные
деньги, либо выданный бесплатно товар.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from models.p2p import Deal, DealStatus, SellerProfile
from services import deal_service as deals
from services import finance_service as fin
from services.money import to_minor

pytestmark = pytest.mark.asyncio

TON = "TON"
AMOUNT = to_minor(Decimal("25"), TON)          # 25 TON
COMMISSION = to_minor(Decimal("0.5"), TON)     # 2%
SELLER_SHARE = to_minor(Decimal("24.5"), TON)


@pytest.fixture
async def seller(db, user_factory):
    user = await user_factory(username="p2p_seller")
    profile = SellerProfile(
        id=uuid.uuid4(), user_id=user.id,
        display_name="Продавец", payout_wallet="EQSellerWallet",
    )
    db.add(profile)
    await db.flush()
    return user


@pytest.fixture
async def buyer(db, user_factory):
    return await user_factory(username="p2p_buyer")


@pytest.fixture
async def funded_deal(db, buyer, seller, order_factory):
    """Сделка на 25 TON с деньгами, уже замороженными в escrow."""
    order = await order_factory(buyer, total_usdt="25.00")
    platform = await fin.platform_account(db, TON)
    await fin.deposit_from_external(
        db, account=platform, amount_minor=AMOUNT,
        ref_type=fin.LedgerRefType.ORDER, ref_id=order.id,
    )

    deal = Deal(
        id=uuid.uuid4(), order_id=order.id,
        buyer_id=buyer.id, seller_id=seller.id,
        product_name="Ноутбук",
        amount_nano=AMOUNT, commission_nano=COMMISSION, seller_amount_nano=SELLER_SHARE,
        status=DealStatus.PAID_ESCROW,
        confirm_deadline_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(deal)
    await db.flush()

    await fin.hold(
        db, account=platform, amount_minor=AMOUNT,
        entry_type=fin.LedgerEntryType.ESCROW_HOLD,
        ref_type=fin.LedgerRefType.DEAL, ref_id=deal.id,
    )
    return deal


class TestEscrow:
    async def test_money_is_held_not_spendable(self, db, funded_deal):
        """
        Смысл escrow: деньги физически на счёте платформы, но потратить их
        нельзя, пока сделка не закрыта.
        """
        platform = await fin.platform_account(db, TON)
        assert platform.balance_minor == AMOUNT
        assert platform.hold_minor == AMOUNT
        assert platform.available_minor == 0

    async def test_seller_gets_nothing_before_confirmation(self, db, funded_deal, seller):
        seller_account = await fin.user_account(db, seller.id, TON)
        assert seller_account.balance_minor == 0

    async def test_confirmation_releases_to_seller(self, db, funded_deal, buyer, seller):
        await deals.confirm_receipt(db, funded_deal, buyer)

        seller_account = await fin.user_account(db, seller.id, TON)
        platform = await fin.platform_account(db, TON)

        assert funded_deal.status == DealStatus.RELEASED
        assert seller_account.balance_minor == SELLER_SHARE
        # Комиссия осталась платформе и больше не заморожена
        assert platform.balance_minor == COMMISSION
        assert platform.hold_minor == 0

        report = await fin.reconcile(db)
        assert report.ok

    async def test_chat_closes_on_release(self, db, funded_deal, buyer):
        await deals.confirm_receipt(db, funded_deal, buyer)
        assert funded_deal.chat_closed is True

    async def test_seller_deal_counter_grows(self, db, funded_deal, buyer, seller):
        await deals.confirm_receipt(db, funded_deal, buyer)
        profile = (
            await db.execute(select(SellerProfile).where(SellerProfile.user_id == seller.id))
        ).scalars().first()
        assert profile.deals_completed == 1


class TestTransitions:
    async def test_only_seller_marks_delivered(self, db, funded_deal, buyer):
        with pytest.raises(deals.DealError):
            await deals.mark_delivered(db, funded_deal, buyer)

    async def test_only_buyer_confirms(self, db, funded_deal, seller):
        with pytest.raises(deals.DealError):
            await deals.confirm_receipt(db, funded_deal, seller)

    async def test_deadline_counts_from_delivery_not_payment(self, db, funded_deal, seller):
        """
        Продавец мог отправить товар не сразу. Если бы срок считался от
        оплаты, покупатель терял бы время на проверку.
        """
        original = funded_deal.confirm_deadline_at
        funded_deal.confirm_deadline_at = datetime.utcnow() + timedelta(days=1)

        await deals.mark_delivered(db, funded_deal, seller)

        assert funded_deal.status == DealStatus.DELIVERED_CLAIMED
        assert funded_deal.confirm_deadline_at > original

    async def test_double_confirmation_is_harmless(self, db, funded_deal, buyer, seller):
        await deals.confirm_receipt(db, funded_deal, buyer)
        await deals.confirm_receipt(db, funded_deal, buyer)   # повтор

        seller_account = await fin.user_account(db, seller.id, TON)
        assert seller_account.balance_minor == SELLER_SHARE   # НЕ удвоилось

    async def test_cannot_confirm_while_disputed(self, db, funded_deal, buyer):
        await deals.open_dispute(db, funded_deal, buyer, "товар не пришёл")
        with pytest.raises(deals.DealError):
            await deals.confirm_receipt(db, funded_deal, buyer)


class TestDispute:
    async def test_dispute_blocks_auto_confirmation(self, db, funded_deal, buyer):
        """Открытый спор обнуляет дедлайн — иначе деньги ушли бы продавцу сами."""
        await deals.open_dispute(db, funded_deal, buyer, "товар не соответствует")

        assert funded_deal.status == DealStatus.DISPUTED
        assert funded_deal.confirm_deadline_at is None

        count = await deals.auto_confirm_due_deals(db)
        assert count == 0

    async def test_outsider_cannot_open_dispute(self, db, funded_deal, user_factory):
        stranger = await user_factory(username="stranger")
        with pytest.raises(deals.DealError):
            await deals.open_dispute(db, funded_deal, stranger, "хочу денег")

    async def test_no_dispute_after_confirmation(self, db, funded_deal, buyer):
        """
        После подтверждения получения деньги уже у продавца — откатывать
        нечего. Это записано в условиях площадки.
        """
        await deals.confirm_receipt(db, funded_deal, buyer)
        with pytest.raises(deals.DealError):
            await deals.open_dispute(db, funded_deal, buyer, "передумал")

    async def test_resolution_for_seller(self, db, funded_deal, buyer, seller, user_factory):
        admin = await user_factory(username="admin_p2p", is_admin=True)
        await deals.open_dispute(db, funded_deal, buyer, "спор")

        await deals.resolve_dispute(db, funded_deal, admin, release=True)

        seller_account = await fin.user_account(db, seller.id, TON)
        assert funded_deal.status == DealStatus.RELEASED
        assert seller_account.balance_minor == SELLER_SHARE
        assert (await fin.reconcile(db)).ok

    async def test_refund_returns_full_amount_with_commission(
        self, db, funded_deal, buyer, seller, user_factory
    ):
        """
        Сделка не состоялась — удерживать комиссию не за что. Покупателю
        возвращается ВСЯ сумма, включая её.
        """
        admin = await user_factory(username="admin_p2p2", is_admin=True)
        await deals.open_dispute(db, funded_deal, buyer, "товар не пришёл")

        await deals.resolve_dispute(db, funded_deal, admin, release=False)

        buyer_account = await fin.user_account(db, buyer.id, TON)
        seller_account = await fin.user_account(db, seller.id, TON)
        platform = await fin.platform_account(db, TON)

        assert funded_deal.status == DealStatus.REFUNDED
        assert buyer_account.balance_minor == AMOUNT     # все 25, не 24.5
        assert seller_account.balance_minor == 0
        assert platform.balance_minor == 0
        assert platform.hold_minor == 0
        assert (await fin.reconcile(db)).ok

    async def test_cannot_resolve_deal_without_dispute(self, db, funded_deal, user_factory):
        admin = await user_factory(username="admin_p2p3", is_admin=True)
        with pytest.raises(deals.DealError):
            await deals.resolve_dispute(db, funded_deal, admin, release=True)


class TestAutoConfirm:
    async def test_expired_deadline_releases_to_seller(self, db, funded_deal, seller):
        """
        Без автоподтверждения деньги продавца зависали бы навсегда, если
        покупатель получил товар и просто не нажал кнопку.
        """
        funded_deal.status = DealStatus.DELIVERED_CLAIMED
        funded_deal.confirm_deadline_at = datetime.utcnow() - timedelta(hours=1)
        await db.flush()

        with patch.object(deals, "__name__", deals.__name__):
            from services.telegram_service import telegram_service
            with patch.object(telegram_service, "send_message", AsyncMock()):
                count = await deals.auto_confirm_due_deals(db)

        seller_account = await fin.user_account(db, seller.id, TON)
        assert count == 1
        assert funded_deal.status == DealStatus.RELEASED
        assert seller_account.balance_minor == SELLER_SHARE

    async def test_live_deadline_is_untouched(self, db, funded_deal):
        funded_deal.status = DealStatus.DELIVERED_CLAIMED
        funded_deal.confirm_deadline_at = datetime.utcnow() + timedelta(days=3)
        await db.flush()

        assert await deals.auto_confirm_due_deals(db) == 0
        assert funded_deal.status == DealStatus.DELIVERED_CLAIMED

    async def test_unshipped_deal_is_not_auto_confirmed(self, db, funded_deal):
        """
        Продавец не отмечал отправку — автоподтверждать нечего, иначе товар
        оплачен, не отправлен, а деньги ушли.
        """
        funded_deal.confirm_deadline_at = datetime.utcnow() - timedelta(hours=1)
        await db.flush()

        assert await deals.auto_confirm_due_deals(db) == 0
        assert funded_deal.status == DealStatus.PAID_ESCROW
