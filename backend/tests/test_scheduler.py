"""
Фоновые задачи.

Планировщик не был покрыт ничем, хотя именно он крутит опрос платежей,
отмену неоплаченных заказов, автоподтверждение сделок, истечение подписок и
ежедневную сверку. Особенность этого кода в том, что **каждая задача глотает
исключения**: так задумано — упавшая задача не должна убивать планировщик и
уносить с собой все остальные. Обратная сторона в том, что сломанная задача
внешне неотличима от работающей, она просто перестаёт что-либо делать.

Отсюда две группы проверок: задачи действительно зарегистрированы (забыть
`add_job` легко, и заметить это невозможно) и падение сервиса внутри задачи не
выходит наружу.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from models.category import Category
from models.order import CurrencyType, Order, OrderItem, OrderStatus
from models.product import Product
from services import scheduler as sched

pytestmark = pytest.mark.asyncio


class _SessionProxy:
    """
    Подменяет AsyncSessionLocal тестовой сессией.

    Задачи открывают собственную сессию (`async with AsyncSessionLocal()`), и
    без подмены они ходили бы в рабочую базу мимо тестовой транзакции.
    Закрывать сессию нельзя — ей ещё пользуется тест.
    """

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc):
        return False


@pytest.fixture
def use_test_session(db, monkeypatch):
    monkeypatch.setattr(sched, "AsyncSessionLocal", lambda: _SessionProxy(db))
    return db


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Тест", name_en="Test")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def p2p_product(db, category, user_factory):
    seller = await user_factory(username=f"sched_seller_{uuid.uuid4().hex[:6]}")
    product = Product(
        id=uuid.uuid4(),
        name_ru="Вещь продавца", name_en="Seller item",
        description_ru="Описание", description_en="Description",
        price_usdt=Decimal("10.00"), image_url="/uploads/x.jpg",
        category_id=category.id, stock=0, type="digital",
        owner_user_id=seller.id, is_p2p=True, content_data={},
    )
    db.add(product)
    await db.flush()
    return product


async def _order_with_p2p_item(db, user_factory, product, *, age: timedelta, status=OrderStatus.PENDING):
    buyer = await user_factory(username=f"sched_buyer_{uuid.uuid4().hex[:6]}")
    order = Order(
        id=uuid.uuid4(), user_id=buyer.id, total_usdt=Decimal("10.00"),
        currency=CurrencyType.TON, status=status,
        created_at=datetime.utcnow() - age,
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(
        id=uuid.uuid4(), order_id=order.id, product_id=product.id,
        product_snapshot={"name_ru": product.name_ru, "type": "digital", "is_p2p": True},
        quantity=1, price_usdt=Decimal("10.00"),
    ))
    await db.flush()
    return order


# ---------------------------------------------------------------------------
# Регистрация задач
# ---------------------------------------------------------------------------

class TestJobRegistration:
    """
    Тесты асинхронные не ради базы, а потому что APScheduler при старте
    забирает текущий event loop и без него падает.
    """

    async def test_all_jobs_are_registered(self):
        """
        Все шесть задач попадают в планировщик.

        Написать функцию и забыть `add_job` — ошибка без единого симптома:
        приложение стартует, логи чистые, задача просто никогда не выполняется.
        Обнаруживается это тем, что деньги не начислились или доступ не отозвался.
        """
        try:
            sched.start_scheduler()

            registered = {job.id for job in sched.scheduler.get_jobs()}
            assert registered == {
                "cleanup_reservations",
                "poll_ton_payments",
                "notify_deal_messages",
                "auto_confirm_deals",
                "process_subscriptions",
                "reconcile_finances",
            }
        finally:
            sched.shutdown_scheduler()

    async def test_payment_polling_is_the_frequent_one(self):
        """
        Опрос платежей идёт секундами, остальное — минутами и часами.

        Человек стоит у экрана и ждёт товар, поэтому платежи опрашиваются часто.
        Всё остальное частым быть не должно: каждый прогон подписок — это вызовы
        Telegram API по каждой истёкшей подписке.
        """
        try:
            sched.start_scheduler()
            intervals = {
                job.id: job.trigger.interval.total_seconds()
                for job in sched.scheduler.get_jobs()
            }

            assert intervals["poll_ton_payments"] <= 60
            # Уведомление о сообщении в сделке не должно ждать минутами
            assert intervals["notify_deal_messages"] <= 60
            assert intervals["cleanup_reservations"] >= 60
            assert intervals["auto_confirm_deals"] >= 3600
            assert intervals["process_subscriptions"] >= 3600
            assert intervals["reconcile_finances"] >= 3600
        finally:
            sched.shutdown_scheduler()

    async def test_second_start_does_not_duplicate_jobs(self):
        """Повторный запуск не должен удваивать задачи."""
        try:
            sched.start_scheduler()
            sched.start_scheduler()

            assert len(sched.scheduler.get_jobs()) == 6
        finally:
            sched.shutdown_scheduler()


# ---------------------------------------------------------------------------
# Изоляция ошибок
# ---------------------------------------------------------------------------

class TestFailuresAreContained:
    """
    Упавший сервис не выносит задачу наружу.

    Если исключение уйдёт в APScheduler, он снимет задачу с расписания — и
    дальше молча не будет опрашивать платежи или отзывать доступ. Поэтому
    каждая задача обязана пережить падение своего сервиса.
    """

    async def test_payment_polling_survives_indexer_failure(self, use_test_session, monkeypatch):
        from services import payment_service

        async def boom(_db):
            raise RuntimeError("индексер недоступен")

        monkeypatch.setattr(payment_service, "poll_pending_payments", boom)

        await sched.poll_ton_payments()  # не должно бросить

    async def test_deal_confirmation_survives_failure(self, use_test_session, monkeypatch):
        from services import deal_service

        async def boom(_db):
            raise RuntimeError("сделки сломались")

        monkeypatch.setattr(deal_service, "auto_confirm_due_deals", boom)

        await sched.auto_confirm_deals()

    async def test_subscriptions_survive_telegram_failure(self, use_test_session, monkeypatch):
        from services import subscription_service

        async def boom(_db):
            raise RuntimeError("Telegram недоступен")

        monkeypatch.setattr(subscription_service, "expire_due_subscriptions", boom)

        await sched.process_subscriptions()

    async def test_reconciliation_survives_failure(self, use_test_session, monkeypatch):
        from services import finance_service

        async def boom(_db):
            raise RuntimeError("сверка сломалась")

        monkeypatch.setattr(finance_service, "reconcile", boom)

        await sched.reconcile_finances()

    async def test_reconciliation_alerts_admin_on_mismatch(self, use_test_session, monkeypatch):
        """
        Несошедшаяся сверка обязана дойти до админа.

        Расхождение означает, что деньги двигали в обход финансового слоя.
        Молчаливая запись в лог тут бесполезна: её никто не читает ежедневно.
        """
        from services import finance_service
        from services.telegram_service import telegram_service

        class FakeReport:
            ok = False
            checked_accounts = 3
            issues = ["счёт X: баланс 100, журнал 90"]
            global_sum_by_currency = {"TON": 10}

        async def mismatch(_db):
            return FakeReport()

        sent = []

        async def fake_send(chat_id, text, **_kwargs):
            sent.append((chat_id, text))

        monkeypatch.setattr(finance_service, "reconcile", mismatch)
        monkeypatch.setattr(telegram_service, "admin_chat_ids", [555])
        monkeypatch.setattr(telegram_service, "send_message", fake_send)

        await sched.reconcile_finances()

        assert len(sent) == 1
        assert "СВЕРКА ФИНАНСОВ НЕ СОШЛАСЬ" in sent[0][1]

    async def test_no_alert_when_reconciliation_is_fine(self, use_test_session, monkeypatch):
        """Сошедшаяся сверка молчит: ежедневный шум приучает не читать алерты."""
        from services import finance_service
        from services.telegram_service import telegram_service

        class FakeReport:
            ok = True

        async def fine(_db):
            return FakeReport()

        sent = []

        async def fake_send(chat_id, text, **_kwargs):
            sent.append((chat_id, text))

        monkeypatch.setattr(finance_service, "reconcile", fine)
        monkeypatch.setattr(telegram_service, "admin_chat_ids", [555])
        monkeypatch.setattr(telegram_service, "send_message", fake_send)

        await sched.reconcile_finances()

        assert sent == []


# ---------------------------------------------------------------------------
# Отмена неоплаченных заказов
# ---------------------------------------------------------------------------

class TestCleanupReservations:

    async def test_expired_order_is_cancelled_and_stock_returns(
        self, use_test_session, db, user_factory, p2p_product
    ):
        """
        Брошенный заказ возвращает вещь на витрину.

        Товар пользователя резервируется стоком: при оформлении заказа остаток
        становится нулём. Если неоплаченный заказ не вернёт его обратно, вещь
        исчезнет из продажи навсегда — продавец потеряет её из-за чужого
        незавершённого checkout.
        """
        order = await _order_with_p2p_item(
            db, user_factory, p2p_product, age=timedelta(days=3)
        )

        await sched.cleanup_reservations()
        await db.refresh(order)
        await db.refresh(p2p_product)

        assert order.status == OrderStatus.CANCELLED
        assert p2p_product.stock == 1

    async def test_fresh_order_is_untouched(
        self, use_test_session, db, user_factory, p2p_product
    ):
        """Свежий заказ не трогаем: человек ещё подписывает транзакцию."""
        order = await _order_with_p2p_item(
            db, user_factory, p2p_product, age=timedelta(minutes=1)
        )

        await sched.cleanup_reservations()
        await db.refresh(order)
        await db.refresh(p2p_product)

        assert order.status == OrderStatus.PENDING
        assert p2p_product.stock == 0

    async def test_paid_order_is_never_cancelled(
        self, use_test_session, db, user_factory, p2p_product
    ):
        """
        Оплаченный заказ не отменяется, даже если он старый.

        Заказ может долго висеть оплаченным: услуга ждёт обработки, P2P-сделка
        ждёт подтверждения получения. Отмена здесь означала бы возврат в продажу
        уже проданной вещи.
        """
        order = await _order_with_p2p_item(
            db, user_factory, p2p_product, age=timedelta(days=3), status=OrderStatus.PAID
        )

        await sched.cleanup_reservations()
        await db.refresh(order)
        await db.refresh(p2p_product)

        assert order.status == OrderStatus.PAID
        assert p2p_product.stock == 0

    async def test_nothing_to_do_is_harmless(self, use_test_session):
        """Пустой прогон — обычное состояние: задача крутится каждые пять минут."""
        await sched.cleanup_reservations()
