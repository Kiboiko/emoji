"""
Подписки: продление, сплит комиссии с автором, истечение.

Вызовы Telegram API замоканы — проверяется логика сроков и денег.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

import pytest

from models.finance import LedgerEntryType
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionPlan, SubscriptionStatus,
)
from services import finance_service as fin
from services import subscription_service as subs
from services.money import to_minor
from services.telegram_service import TelegramApiError

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


class TestOrderWiring:
    """
    Регрессия: сплит вызывается из complete_order.

    Баг, найденный на реальном платеже: _activate_subscriptions искала сумму
    платежа запросом к БД, но в проекте autoflush=False — статус платежа,
    выставленный вызывающим кодом, ещё не был записан, запрос ничего не
    находил, и начисление автору молча пропускалось. Тесты это не ловили,
    потому что проверяли split_subscription_payment напрямую, в обход связки.
    """

    async def _order_with_subscription(self, db, buyer, plan, order_factory):
        import uuid as _uuid
        from decimal import Decimal as D
        from models.order import OrderItem

        order = await order_factory(buyer, total_usdt="0.10")
        item = OrderItem(
            id=_uuid.uuid4(),
            order_id=order.id,
            product_id=None,
            quantity=1,
            price_usdt=D("0.10"),
            product_snapshot={
                "name_ru": "Подписка", "name_en": "Subscription",
                "type": "subscription",
                "content_data": {"subscription_plan_id": str(plan.id)},
            },
        )
        db.add(item)
        await db.flush()
        return order, item

    async def test_split_happens_when_amount_passed(
        self, db, user_factory, order_factory, plan, channel
    ):
        from routes.orders import _activate_subscriptions
        from services import finance_service as fin

        buyer = await user_factory(username="sub_buyer")
        order, item = await self._order_with_subscription(db, buyer, plan, order_factory)

        received = 74_626_866
        platform = await fin.platform_account(db, TON)
        await fin.deposit_from_external(
            db, account=platform, amount_minor=received,
            ref_type=fin.LedgerRefType.ORDER, ref_id=order.id,
        )

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            await _activate_subscriptions(db, order, buyer, [item], received)

        author = await fin.user_account(db, channel.owner_user_id, TON)
        # 2% платформе, остальное автору — ровно как в примере из ТЗ
        assert author.balance_minor == 73_134_329
        assert platform.balance_minor == 1_492_537

        report = await fin.reconcile(db)
        assert report.ok

    async def test_no_amount_still_activates_but_skips_split(
        self, db, user_factory, order_factory, plan, channel
    ):
        """
        Подписку всё равно выдаём: покупатель заплатил. Но автору ничего не
        начисляем вслепую — это разбирается вручную по логу ошибки.
        """
        from routes.orders import _activate_subscriptions
        from services import finance_service as fin
        from models.subscription import Subscription

        buyer = await user_factory(username="sub_buyer2")
        order, item = await self._order_with_subscription(db, buyer, plan, order_factory)

        with patch.object(subs, "issue_invite", AsyncMock(return_value=None)):
            await _activate_subscriptions(db, order, buyer, [item], 0)

        sub = (
            await db.execute(
                select(Subscription).where(Subscription.user_id == buyer.id)
            )
        ).scalars().first()
        assert sub is not None and sub.status == SubscriptionStatus.ACTIVE

        author = await fin.user_account(db, channel.owner_user_id, TON)
        assert author.balance_minor == 0


# ---------------------------------------------------------------------------
# Проверка прав бота в канале
# ---------------------------------------------------------------------------

class TestChannelVerification:
    """
    Без прав бота канал бесполезен: выдать доступ и отозвать его невозможно.
    Поэтому результат проверки запоминается, а публикация без него запрещена.
    """

    async def test_admin_rights_are_recorded(self, db, channel):
        channel.bot_is_admin = False
        with patch.object(subs.channel_access, "check_bot_is_admin",
                          AsyncMock(return_value=(True, None))), \
             patch.object(subs.channel_access, "get_chat",
                          AsyncMock(return_value={"title": "Новое имя", "username": "chan"})):
            ok, error = await subs.verify_channel(db, channel)

        assert ok is True
        assert error is None
        assert channel.bot_is_admin is True
        assert channel.bot_checked_at is not None
        # Заодно подтянули актуальное имя канала — автор мог его переименовать
        assert channel.title == "Новое имя"
        assert channel.username == "chan"

    async def test_missing_rights_are_recorded_with_reason(self, db, channel):
        """
        Причина отказа сохраняется.

        Автору надо сказать, чего именно не хватает, иначе он будет
        добавлять бота заново и получать тот же результат.
        """
        with patch.object(subs.channel_access, "check_bot_is_admin",
                          AsyncMock(return_value=(False, "Бот не администратор"))):
            ok, error = await subs.verify_channel(db, channel)

        assert ok is False
        assert error == "Бот не администратор"
        assert channel.bot_is_admin is False
        assert channel.bot_check_error == "Бот не администратор"

    async def test_chat_info_failure_does_not_break_verification(self, db, channel):
        """Права подтверждены — неудача с получением имени канала не важна."""
        with patch.object(subs.channel_access, "check_bot_is_admin",
                          AsyncMock(return_value=(True, None))), \
             patch.object(subs.channel_access, "get_chat",
                          AsyncMock(side_effect=TelegramApiError("getChat", "недоступен"))):
            ok, _ = await subs.verify_channel(db, channel)

        assert ok is True
        assert channel.bot_is_admin is True
        assert channel.title == "Закрытый канал"


# ---------------------------------------------------------------------------
# Выдача ссылки
# ---------------------------------------------------------------------------

class TestInviteIssuing:

    @pytest.fixture
    async def subscription(self, db, user_factory, channel, plan):
        buyer = await user_factory(username="sub_buyer")
        row = Subscription(
            id=uuid.uuid4(),
            user_id=buyer.id,
            plan_id=plan.id,
            channel_id=channel.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(row)
        await db.flush()
        row.channel = channel
        row.user = buyer
        return row

    async def test_link_is_saved_with_expiry(self, db, subscription):
        with patch.object(subs.channel_access, "ensure_not_banned",
                          AsyncMock(return_value=False)), \
             patch.object(subs.channel_access, "create_invite_link",
                          AsyncMock(return_value={"invite_link": "https://t.me/+abc"})):
            link = await subs.issue_invite(db, subscription)

        assert link == "https://t.me/+abc"
        assert subscription.invite_link == "https://t.me/+abc"
        # Ссылка одноразовая и с сроком — иначе её передадут дальше
        assert subscription.invite_link_expires_at > datetime.utcnow()

    async def test_ban_is_lifted_before_issuing(self, db, subscription):
        """
        Перед выдачей снимается бан.

        «Удалить участника» через интерфейс Telegram — это бан. Забаненный не
        войдёт ни по какой ссылке и увидит «срок действия ссылки истёк»:
        выглядит как сломанная оплата, хотя ссылка живая.
        """
        unban = AsyncMock(return_value=True)
        with patch.object(subs.channel_access, "ensure_not_banned", unban), \
             patch.object(subs.channel_access, "create_invite_link",
                          AsyncMock(return_value={"invite_link": "https://t.me/+xyz"})):
            await subs.issue_invite(db, subscription)

        assert unban.await_count == 1

    async def test_telegram_failure_does_not_break_paid_subscription(self, db, subscription):
        """
        Отказ Telegram не откатывает оплату.

        Подписка уже оплачена. Падение выдачи фиксируется в журнале, админу
        уходит алерт, доступ выдаётся вручную — но деньги остаются учтёнными.
        """
        alerts = []

        async def capture(text):
            alerts.append(text)

        with patch.object(subs.channel_access, "ensure_not_banned",
                          AsyncMock(return_value=False)), \
             patch.object(subs.channel_access, "create_invite_link",
                          AsyncMock(side_effect=TelegramApiError(
                              "createChatInviteLink", "not enough rights"))), \
             patch.object(subs, "_alert_admins", capture):
            link = await subs.issue_invite(db, subscription)

        assert link is None
        assert subscription.invite_link is None
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert len(alerts) == 1
        assert "вручную" in alerts[0]

    async def test_unban_failure_does_not_stop_issuing(self, db, subscription):
        """Не удалось снять бан — ссылку всё равно создаём, причина в журнале."""
        with patch.object(subs.channel_access, "ensure_not_banned",
                          AsyncMock(side_effect=TelegramApiError("unbanChatMember", "нет прав"))), \
             patch.object(subs.channel_access, "create_invite_link",
                          AsyncMock(return_value={"invite_link": "https://t.me/+ok"})):
            link = await subs.issue_invite(db, subscription)

        assert link == "https://t.me/+ok"


# ---------------------------------------------------------------------------
# Напоминания
# ---------------------------------------------------------------------------

class TestExpiryReminders:

    @pytest.fixture
    async def expiring(self, db, user_factory, channel, plan):
        async def make(days_left: float):
            buyer = await user_factory(username=f"rem_{uuid.uuid4().hex[:6]}")
            row = Subscription(
                id=uuid.uuid4(),
                user_id=buyer.id,
                plan_id=plan.id,
                channel_id=channel.id,
                status=SubscriptionStatus.ACTIVE,
                started_at=datetime.utcnow() - timedelta(days=27),
                expires_at=datetime.utcnow() + timedelta(days=days_left),
            )
            db.add(row)
            await db.flush()
            return row

        return make

    async def test_reminder_is_sent_three_days_before(self, db, expiring):
        subscription = await expiring(2.5)
        sender = AsyncMock()

        with patch.object(subs.telegram_service, "send_message", sender):
            sent = await subs.send_expiry_reminders(db)

        assert sent == 1
        assert sender.await_count == 1
        assert subscription.reminder_sent_for_days == 3

    async def test_same_reminder_is_not_repeated(self, db, expiring):
        """
        Джоба крутится каждый час — без отметки человек получал бы напоминание
        двадцать четыре раза в сутки.
        """
        await expiring(2.5)
        sender = AsyncMock()

        with patch.object(subs.telegram_service, "send_message", sender):
            first = await subs.send_expiry_reminders(db)
            second = await subs.send_expiry_reminders(db)

        assert first == 1
        assert second == 0
        assert sender.await_count == 1

    async def test_day_before_reminder_still_goes_out(self, db, expiring):
        """Напоминание за сутки приходит, даже если за три дня уже приходило."""
        subscription = await expiring(2.5)
        sender = AsyncMock()

        with patch.object(subs.telegram_service, "send_message", sender):
            await subs.send_expiry_reminders(db)
            subscription.expires_at = datetime.utcnow() + timedelta(hours=12)
            await db.flush()
            second = await subs.send_expiry_reminders(db)

        assert second == 1
        assert subscription.reminder_sent_for_days == 1

    async def test_failed_send_is_retried_later(self, db, expiring):
        """
        Не доставленное напоминание не помечается отправленным.

        Человек мог заблокировать бота временно; отметить отправку означало бы
        молча лишить его единственного предупреждения об окончании доступа.
        """
        subscription = await expiring(2.5)

        with patch.object(subs.telegram_service, "send_message",
                          AsyncMock(side_effect=RuntimeError("bot blocked"))):
            sent = await subs.send_expiry_reminders(db)

        assert sent == 0
        assert subscription.reminder_sent_for_days is None

    async def test_distant_expiry_gets_no_reminder(self, db, expiring):
        await expiring(20)
        sender = AsyncMock()

        with patch.object(subs.telegram_service, "send_message", sender):
            sent = await subs.send_expiry_reminders(db)

        assert sent == 0
        assert sender.await_count == 0
