"""
Верификация TON-платежа: недоплата, переплата, дубль, истечение.

Самая дорогая ошибка в проекте живёт здесь. Эта функция решает, считать ли
заказ оплаченным, и ошибка в любую сторону означает либо выданный бесплатно
товар, либо потерянные деньги покупателя.

Индексер замокан: тесты не должны зависеть от доступности toncenter и от
того, что сейчас лежит в блокчейне.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from models.finance import Account, AccountOwnerType
from models.order import OrderStatus
from models.payment import Payment, PaymentStatus
from services import payment_service as pay
from services import finance_service as fin
from services.ton_service import OnChainTx

pytestmark = pytest.mark.asyncio

TON = "TON"
PRICE_NANO = 10_000_000_000          # 10 TON
INDEXER = "services.ton_service.fetch_incoming_transactions"
NOTIFY = "services.telegram_service.telegram_service.send_message"


def make_tx(*, comment: str, value_nano: int, tx_hash: str = "tx-1", utime: int | None = None):
    return OnChainTx(
        tx_hash=tx_hash,
        lt=1,
        utime=utime if utime is not None else int(datetime.utcnow().timestamp()),
        source="0QSenderWallet",
        value_nano=value_nano,
        comment=comment,
    )


@pytest.fixture
async def invoice(db, user_factory, order_factory):
    """Выставленный счёт на 10 TON по заказу в ожидании оплаты."""
    async def make(status=OrderStatus.PENDING, expires_in_min=30):
        user = await user_factory(username=f"payer_{uuid.uuid4().hex[:6]}")
        order = await order_factory(user, total_usdt="30.00", status=status)

        now = datetime.utcnow()
        payment = Payment(
            id=uuid.uuid4(),
            order_id=order.id,
            user_id=user.id,
            amount_nano=PRICE_NANO,
            usd_amount=Decimal("30.00"),
            rate_usd_per_ton=Decimal("3.000000000"),
            rate_locked_at=now,
            expires_at=now + timedelta(minutes=expires_in_min),
            destination_address="0QPlatformWallet",
            payment_comment=f"MP-{uuid.uuid4().hex[:12].upper()}",
            status=PaymentStatus.PENDING,
        )
        db.add(payment)
        await db.flush()
        return payment, order, user

    return make


async def _verify(db, payment, txs):
    """Проверка платежа с подменённым индексером и молчаливым Telegram."""
    with patch(INDEXER, new=AsyncMock(return_value=txs)), \
         patch(NOTIFY, new=AsyncMock()):
        return await pay.verify_payment(db, payment)


async def _platform_balance(db) -> int:
    account = (await db.execute(
        select(Account).where(
            Account.owner_type == AccountOwnerType.PLATFORM,
            Account.currency == TON,
        )
    )).scalars().first()
    return account.balance_minor if account else 0


# ---------------------------------------------------------------------------
# Точная оплата
# ---------------------------------------------------------------------------

async def test_exact_payment_confirms(db, invoice):
    payment, order, _ = await invoice()
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO)

    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.CONFIRMED
    assert payment.tx_hash == "tx-1"
    assert payment.received_nano == PRICE_NANO
    await db.refresh(order)
    assert order.status in (OrderStatus.PAID, OrderStatus.COMPLETED)
    # Деньги попали на счёт платформы, а не появились из воздуха
    assert await _platform_balance(db) == PRICE_NANO


async def test_no_transaction_leaves_pending(db, invoice):
    """Пока перевода нет, заказ остаётся неоплаченным."""
    payment, order, _ = await invoice()

    status = await _verify(db, payment, [])

    assert status == PaymentStatus.PENDING
    await db.refresh(order)
    assert order.status == OrderStatus.PENDING


async def test_foreign_comment_ignored(db, invoice):
    """
    Чужой перевод на тот же кошелёк не должен зачитываться.

    Комментарий — единственное, что связывает транзакцию с заказом: на кошелёк
    платформы приходят платежи всех покупателей сразу.
    """
    payment, _, _ = await invoice()
    tx = make_tx(comment="MP-СОВСЕМ-ДРУГОЙ", value_nano=PRICE_NANO)

    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.PENDING
    assert payment.tx_hash is None


# ---------------------------------------------------------------------------
# Недоплата
# ---------------------------------------------------------------------------

async def test_underpayment_does_not_release_goods(db, invoice):
    """
    Недоплата не выдаёт товар.

    Автоматически «доначислять» нельзя: иначе товар покупается за копейку с
    обещанием доплатить.
    """
    payment, order, _ = await invoice()
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO // 2)

    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.UNDERPAID
    assert payment.received_nano == PRICE_NANO // 2
    await db.refresh(order)
    assert order.status == OrderStatus.PENDING
    # Недоплата в журнал не попадает: деньги на кошельке есть, но заказ не
    # оплачен, и разбирается это вручную
    assert await _platform_balance(db) == 0


async def test_underpayment_alerts_admin(db, invoice):
    """Администратор должен узнать о недоплате — сама она не рассосётся."""
    payment, _, _ = await invoice()
    tx = make_tx(comment=payment.payment_comment, value_nano=1)

    notify = AsyncMock()
    with patch(INDEXER, new=AsyncMock(return_value=[tx])), \
         patch(NOTIFY, new=notify), \
         patch("services.telegram_service.telegram_service.admin_chat_ids", ["123"]):
        await pay.verify_payment(db, payment)

    assert notify.await_count == 1
    assert "Недоплата" in notify.await_args.args[1]


# ---------------------------------------------------------------------------
# Переплата
# ---------------------------------------------------------------------------

async def test_overpayment_confirms_and_credits_full_amount(db, invoice):
    """
    Переплата не должна блокировать выдачу.

    Человек заплатил больше, чем просили, — это не повод не отдать товар. В
    журнал попадает фактически полученная сумма, иначе журнал разойдётся с
    кошельком.
    """
    payment, order, _ = await invoice()
    overpaid = PRICE_NANO + 3_000_000_000
    tx = make_tx(comment=payment.payment_comment, value_nano=overpaid)

    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.CONFIRMED
    assert payment.received_nano == overpaid
    assert await _platform_balance(db) == overpaid
    await db.refresh(order)
    assert order.status in (OrderStatus.PAID, OrderStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Повторы и дубли
# ---------------------------------------------------------------------------

async def test_repeated_verification_is_idempotent(db, invoice):
    """
    Повторная проверка не зачисляет деньги дважды.

    Вызывается она часто: фронт опрашивает статус каждые пять секунд, плюс
    фоновая джоба.
    """
    payment, _, _ = await invoice()
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO)

    await _verify(db, payment, [tx])
    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.CONFIRMED
    assert await _platform_balance(db) == PRICE_NANO


async def test_same_transaction_not_credited_to_two_orders(db, invoice):
    """
    Один перевод нельзя зачесть по двум заказам.

    Сценарий: индексер отдал ту же транзакцию ещё раз, а комментарий в ней
    совпал со вторым счётом. Защита стоит на хеше транзакции — он в блокчейне
    уникален, и повторное зачисление означало бы выдачу товара за чужие
    деньги.

    Подменить второму счёту комментарий на тот же нельзя: UNIQUE в БД не даст,
    и это правильно — совпадение комментариев само по себе означало бы зачёт
    чужого платежа.
    """
    first_payment, _, _ = await invoice()
    second_payment, second_order, _ = await invoice()

    shared_hash = "tx-shared"
    first_tx = make_tx(
        comment=first_payment.payment_comment, value_nano=PRICE_NANO, tx_hash=shared_hash,
    )
    second_tx = make_tx(
        comment=second_payment.payment_comment, value_nano=PRICE_NANO, tx_hash=shared_hash,
    )

    await _verify(db, first_payment, [first_tx])
    status = await _verify(db, second_payment, [second_tx])

    assert status != PaymentStatus.CONFIRMED
    assert second_payment.tx_hash is None
    await db.refresh(second_order)
    assert second_order.status == OrderStatus.PENDING
    # На счёт платформы попал ровно один платёж
    assert await _platform_balance(db) == PRICE_NANO


# ---------------------------------------------------------------------------
# Истечение
# ---------------------------------------------------------------------------

async def test_expired_invoice_without_payment(db, invoice):
    payment, _, _ = await invoice(expires_in_min=-1)

    status = await _verify(db, payment, [])

    assert status == PaymentStatus.EXPIRED


async def test_payment_after_expiry_is_still_credited(db, invoice):
    """
    Перевод, пришедший после истечения счёта, всё равно зачитывается.

    Деньги уже ушли из кошелька покупателя. Если перестать искать транзакцию,
    они просто зависнут на кошельке платформы, а человек останется и без
    товара, и без денег. Именно так был потерян реальный платёж на тестнете.
    """
    payment, _, _ = await invoice(expires_in_min=-1)

    # Сначала счёт признаётся просроченным
    assert await _verify(db, payment, []) == PaymentStatus.EXPIRED

    # Затем приходит перевод
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO)
    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.CONFIRMED
    assert await _platform_balance(db) == PRICE_NANO


async def test_confirmed_is_terminal(db, invoice):
    """
    Подтверждённый платёж больше не перепроверяется.

    Единственный по-настоящему конечный статус: всё остальное может измениться
    приходом транзакции.
    """
    payment, _, _ = await invoice()
    payment.status = PaymentStatus.CONFIRMED
    await db.flush()

    indexer = AsyncMock(return_value=[])
    with patch(INDEXER, new=indexer):
        status = await pay.verify_payment(db, payment)

    assert status == PaymentStatus.CONFIRMED
    # К индексеру даже не обращались
    indexer.assert_not_awaited()


# ---------------------------------------------------------------------------
# Оплата отменённого заказа
# ---------------------------------------------------------------------------

async def test_payment_for_cancelled_order_credits_balance(db, invoice):
    """
    Оплата пришла после автоотмены заказа.

    Товар мог уже уйти другому покупателю, поэтому не выдаём его, но и деньги
    не присваиваем: сумма попадает на внутренний баланс покупателя.
    """
    payment, order, user = await invoice(status=OrderStatus.CANCELLED)
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO)

    status = await _verify(db, payment, [tx])

    assert status == PaymentStatus.CONFIRMED

    user_account = (await db.execute(
        select(Account).where(
            Account.owner_type == AccountOwnerType.USER,
            Account.owner_id == user.id,
            Account.currency == TON,
        )
    )).scalars().first()
    assert user_account is not None
    assert user_account.balance_minor == PRICE_NANO

    await db.refresh(order)
    assert order.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Сверка
# ---------------------------------------------------------------------------

async def test_ledger_balances_after_payment(db, invoice):
    """
    После зачёта платежа журнал сходится.

    Двойная запись: сколько пришло на счёт платформы, столько же ушло с
    внешнего счёта. Сумма по валюте всегда ноль.
    """
    payment, _, _ = await invoice()
    tx = make_tx(comment=payment.payment_comment, value_nano=PRICE_NANO)
    await _verify(db, payment, [tx])

    report = await fin.reconcile(db)

    assert report.ok is True
    assert report.issues == []
    assert report.global_sum_by_currency[TON] == 0
