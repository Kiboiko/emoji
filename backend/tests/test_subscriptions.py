"""
Подписки: продление, сплит комиссии с автором, истечение.

Вызовы Telegram API замоканы — проверяется логика сроков и денег.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models.finance import LedgerEntryType
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionPlan, SubscriptionStatus,
)
from services import finance_service as fin
from services import subscription_service as subs
from services.money import to_minor

pytestmark = pytest.mark.asyncio

TON = "TON"


@pytest.fixture
async def channel(db, user_factory):
    author = await user_factory(username="author")
    ch = Channel(
        id=uuid.uuid4(),
        owner_user_id=author.id,
        telegram_chat_id=-1001234567890,
        title="Закрытый канал",
        status=ChannelStatus.ACTIVE,
        bot_is_admin=True,
        payout_wallet="EQAuthorWallet",
    )
    db.add(ch)
    await db.flush()
    ch.owner = author
    return ch


@pytest.fixture
async def plan(db, channel):
    p = SubscriptionPlan(
        id=uuid.uuid4(),
        channel_id=channel.id,
        title_ru="Месяц", title_en="Month",
        duration_days=30,
        price_usd=Decimal("10.00"),
    )
    db.add(p)
    await db.flush()
    return p


class TestActivateAndExtend:
    async def test_creates_active_subscription(self, db, user_factory, order_factory, plan, channel):
        buyer = await user_factory(username="buyer")
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value="https://t.me/+abc")):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )

        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.expires_at is not None
        assert 29 <= (sub.expires_at - datetime.utcnow()).days <= 30

    async def test_quantity_multiplies_duration(self, db, user_factory, order_factory, plan):
        buyer = await user_factory()
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id, quantity=3
            )

        assert 89 <= (sub.expires_at - datetime.utcnow()).days <= 90

    async def test_extension_adds_days_not_overwrites(self, db, user_factory, order_factory, plan):
        """
        Пользователь, купивший второй месяц до окончания первого, не должен
        терять оплаченные дни.
        """
        buyer = await user_factory()
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            first = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )
            first_expiry = first.expires_at

            second = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )

        assert second.id == first.id                       # та же подписка
        assert second.expires_at == first_expiry + timedelta(days=30)

    async def test_extension_after_expiry_starts_from_now(self, db, user_factory, order_factory, plan):
        """Если подписка уже истекла, новый срок считается от сегодня."""
        buyer = await user_factory()
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )
            # Срок вышел, но статус ещё ACTIVE (джоба не отработала)
            sub.expires_at = datetime.utcnow() - timedelta(days=5)
            await db.flush()

            again = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )

        # Не 25 дней (30 минус просроченные), а полные 30 от сегодня
        assert 29 <= (again.expires_at - datetime.utcnow()).days <= 30


class TestCommissionSplit:
    async def test_author_gets_amount_minus_commission(self, db, channel):
        """Пример из ТЗ: 25 TON, комиссия 2% -> автору 24.5, платформе 0.5."""
        order_id = uuid.uuid4()
        amount = to_minor(Decimal("25"), TON)

        platform = await fin.platform_account(db, TON)
        await fin.deposit_from_external(
            db, account=platform, amount_minor=amount,
            ref_type=fin.LedgerRefType.ORDER, ref_id=order_id,
        )

        await subs.split_subscription_payment(
            db, channel=channel, order_id=order_id,
            amount_nano=amount, key_suffix="item1",
        )

        author_acc = await fin.user_account(db, channel.owner_user_id, TON)
        assert author_acc.balance_minor == to_minor(Decimal("24.5"), TON)
        assert platform.balance_minor == to_minor(Decimal("0.5"), TON)

    async def test_split_is_idempotent(self, db, channel):
        """Повторная обработка того же заказа не должна начислить автору дважды."""
        order_id = uuid.uuid4()
        amount = to_minor(Decimal("25"), TON)

        platform = await fin.platform_account(db, TON)
        await fin.deposit_from_external(
            db, account=platform, amount_minor=amount,
            ref_type=fin.LedgerRefType.ORDER, ref_id=order_id,
        )

        for _ in range(3):
            await subs.split_subscription_payment(
                db, channel=channel, order_id=order_id,
                amount_nano=amount, key_suffix="item1",
            )

        author_acc = await fin.user_account(db, channel.owner_user_id, TON)
        assert author_acc.balance_minor == to_minor(Decimal("24.5"), TON)

    async def test_books_stay_balanced(self, db, channel):
        order_id = uuid.uuid4()
        amount = to_minor(Decimal("7.77"), TON)

        platform = await fin.platform_account(db, TON)
        await fin.deposit_from_external(
            db, account=platform, amount_minor=amount,
            ref_type=fin.LedgerRefType.ORDER, ref_id=order_id,
        )
        await subs.split_subscription_payment(
            db, channel=channel, order_id=order_id,
            amount_nano=amount, key_suffix="i",
        )

        report = await fin.reconcile(db)
        assert report.ok

    async def test_zero_amount_does_nothing(self, db, channel):
        await subs.split_subscription_payment(
            db, channel=channel, order_id=uuid.uuid4(),
            amount_nano=0, key_suffix="i",
        )
        author_acc = await fin.user_account(db, channel.owner_user_id, TON)
        assert author_acc.balance_minor == 0


class TestExpiry:
    async def test_expires_and_revokes_access(self, db, user_factory, order_factory, plan, channel):
        buyer = await user_factory()
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )
        sub.expires_at = datetime.utcnow() - timedelta(hours=1)
        await db.flush()

        kick = AsyncMock()
        with patch.object(subs.channel_access, "kick_member", kick), \
             patch.object(subs.telegram_service, "send_message", AsyncMock()):
            count = await subs.expire_due_subscriptions(db)

        assert count == 1
        assert sub.status == SubscriptionStatus.EXPIRED
        # Именно kick_member: внутри он делает ban + unban, иначе пользователь
        # остался бы в вечном бане и не смог купить подписку снова
        kick.assert_awaited_once()

    async def test_active_subscription_is_not_touched(self, db, user_factory, order_factory, plan):
        buyer = await user_factory()
        order = await order_factory(buyer)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )

        with patch.object(subs.channel_access, "kick_member", AsyncMock()):
            count = await subs.expire_due_subscriptions(db)

        assert count == 0
        assert sub.status == SubscriptionStatus.ACTIVE

    async def test_telegram_failure_still_closes_subscription(
        self, db, user_factory, order_factory, plan, channel
    ):
        """
        Канал могли удалить, бота разжаловать. Подписка всё равно обязана
        закрыться, иначе будет висеть активной вечно и блокировать повторную
        покупку.
        """
        from services.telegram_service import TelegramApiError

        buyer = await user_factory()
        order = await order_factory(buyer)
        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            sub = await subs.activate_or_extend(
                db, user=buyer, plan=plan, order_id=order.id
            )
        sub.expires_at = datetime.utcnow() - timedelta(hours=1)
        await db.flush()

        failing = AsyncMock(side_effect=TelegramApiError("banChatMember", "CHAT_NOT_FOUND"))
        with patch.object(subs.channel_access, "kick_member", failing), \
             patch.object(subs.telegram_service, "send_message", AsyncMock()), \
             patch.object(subs, "_alert_admins", AsyncMock()):
            await subs.expire_due_subscriptions(db)

        assert sub.status == SubscriptionStatus.EXPIRED
