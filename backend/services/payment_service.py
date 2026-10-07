"""
Оплата заказа через TON Connect.

Заменяет прежний CryptoBotService. Точка выдачи товара — complete_order() из
routes/orders.py — не изменилась: она про платёжку ничего не знает и
переиспользуется как есть.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.finance import LedgerEntryType, LedgerRefType
from models.order import Order, OrderStatus
from models.payment import Payment, PaymentStatus
from services import finance_service, settings_service, ton_service
from services.money import TON_LABEL
from services.ton_service import CURRENCY, TransactionRequest

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    pass


# ---------------------------------------------------------------------------
# Выставление счёта
# ---------------------------------------------------------------------------

async def create_or_refresh_payment(db: AsyncSession, order: Order) -> Payment:
    """
    Готовит платёж по заказу.

    Если по заказу уже есть непросроченный счёт — возвращаем его, а не плодим
    новые: иначе пользователь, дважды нажавший «Оплатить», получил бы два
    разных комментария, заплатил бы по одному, а мы ждали бы второй.

    Просроченный счёт помечается EXPIRED и выставляется новый с актуальным
    курсом.
    """
    if order.status != OrderStatus.PENDING:
        raise PaymentError(f"Заказ уже в статусе {order.status.value}, оплата не нужна")

    address = ton_service.require_receiving_address()
    now = datetime.utcnow()

    existing = (
        await db.execute(
            select(Payment)
            .where(
                Payment.order_id == order.id,
                Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.SEEN]),
            )
            .order_by(Payment.created_at.desc())
        )
    ).scalars().first()

    if existing is not None:
        if existing.expires_at and existing.expires_at > now:
            return existing
        existing.status = PaymentStatus.EXPIRED
        logger.info("[PAY] Счёт %s просрочен, выставляем новый", existing.id)

    rate = await ton_service.get_rate(db)

    # Срок счёта = сроку жизни заказа, а не времени кеширования курса.
    # Раньше здесь стоял ton_rate_ttl_sec (15 мин), из-за чего счёт протухал
    # вдвое раньше, чем отменялся сам заказ и освобождался резерв товара
    # (order_payment_ttl_min, 30 мин). Пользователь видел «время вышло» при
    # живом заказе. Курс при этом фиксируется на весь срок счёта — это
    # обещание цены покупателю, а ton_rate_ttl_sec управляет лишь тем, как
    # часто мы обновляем курс из внешнего источника.
    ttl_minutes = await settings_service.get_int(db, "order_payment_ttl_min")

    usd_amount = Decimal(str(order.total_usdt))
    amount_nano = ton_service.usd_to_nano(usd_amount, rate)

    payment = Payment(
        id=uuid.uuid4(),
        order_id=order.id,
        user_id=order.user_id,
        provider="ton_connect",
        currency=CURRENCY,
        amount_nano=amount_nano,
        usd_amount=usd_amount,
        rate_usd_per_ton=rate,
        rate_locked_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
        destination_address=address,
        payment_comment=ton_service.generate_payment_comment(),
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    await db.flush()

    logger.info(
        "[PAY] Счёт %s по заказу %s: %s нанотон (%s USD по курсу %s), комментарий %s",
        payment.id, order.id, amount_nano, usd_amount, rate, payment.payment_comment,
    )
    return payment


def build_transaction_request(payment: Payment) -> TransactionRequest:
    """Данные для TON Connect sendTransaction."""
    return TransactionRequest(
        address=payment.destination_address,
        amount_nano=payment.amount_nano,
        comment=payment.payment_comment,
        valid_until=int(payment.expires_at.timestamp()),
        network="testnet" if settings.ton_is_testnet else "mainnet",
        rate_usd_per_ton=str(payment.rate_usd_per_ton),
        usd_amount=str(payment.usd_amount),
    )


# ---------------------------------------------------------------------------
# Проверка оплаты
# ---------------------------------------------------------------------------

async def verify_payment(
    db: AsyncSession,
    payment: Payment,
    txs: list | None = None,
) -> PaymentStatus:
    """
    Проверяет платёж по данным блокчейна и, если он прошёл, зачитывает его.

    Возвращает актуальный статус. Идемпотентна: повторный вызов по уже
    подтверждённому платежу ничего не меняет.

    `txs` — уже полученный список транзакций. Нужен поллеру: он забирает их
    один раз на весь прогон и передаёт сюда. Без этого каждый платёж в пачке
    тянул бы индексер заново, и на десяти одновременных оплатах прогон давал
    одиннадцать запросов — при лимите toncenter около запроса в секунду это
    упирается в лимит ровно тогда, когда покупателей много. При ручной
    проверке («я оплатил») список не передаётся: там нужны свежие данные.
    """
    # Терминален только CONFIRMED. EXPIRED — НЕ повод перестать проверять:
    # пользователь вполне может отправить перевод через минуту после того,
    # как счёт протух. Деньги уже ушли из его кошелька, и если мы перестанем
    # искать транзакцию, они просто зависнут на кошельке платформы.
    # Такой платёж зачисляется на внутренний баланс пользователя (см. _confirm).
    if payment.status == PaymentStatus.CONFIRMED:
        return payment.status

    if txs is None:
        txs = await ton_service.fetch_incoming_transactions()
    window_start, window_end = ton_service.payment_window(
        payment.rate_locked_at, payment.expires_at
    )
    match = ton_service.match_payment(
        txs,
        comment=payment.payment_comment,
        expected_nano=payment.amount_nano,
        window_start=window_start,
        window_end=window_end,
    )

    if not match.matched:
        if match.underpaid and match.tx is not None:
            return await _handle_underpaid(db, payment, match.tx)
        if payment.expires_at and payment.expires_at < datetime.utcnow():
            return await _handle_expired(db, payment)
        return payment.status

    tx = match.tx

    # Защита от повторного зачёта одного перевода. UNIQUE по tx_hash в БД —
    # последний рубеж, но проверяем и здесь, чтобы отдать понятную причину.
    duplicate = (
        await db.execute(
            select(Payment).where(Payment.tx_hash == tx.tx_hash, Payment.id != payment.id)
        )
    ).scalars().first()
    if duplicate is not None:
        logger.error(
            "[PAY] Транзакция %s уже зачтена по платежу %s — не зачитываем повторно",
            tx.tx_hash, duplicate.id,
        )
        return payment.status

    payment.tx_hash = tx.tx_hash
    payment.tx_lt = tx.lt
    payment.from_address = tx.source
    payment.received_nano = tx.value_nano
    if payment.seen_at is None:
        payment.seen_at = datetime.utcnow()

    # Выдержка перед выдачей товара, если настроена
    min_confirm = await settings_service.get_int(db, "ton_min_confirm_sec")
    if min_confirm > 0:
        held_for = (datetime.utcnow() - payment.seen_at).total_seconds()
        if held_for < min_confirm:
            payment.status = PaymentStatus.SEEN
            await db.commit()
            logger.info(
                "[PAY] Платёж %s найден, выдержка %.0f/%s сек",
                payment.id, held_for, min_confirm,
            )
            return payment.status

    return await _confirm(db, payment, tx.value_nano)


async def _confirm(db: AsyncSession, payment: Payment, received_nano: int) -> PaymentStatus:
    """Зачитывает платёж: деньги в журнал, заказ — на выдачу."""
    from routes.orders import complete_order  # локальный импорт: циклическая зависимость

    order = await db.get(Order, payment.order_id)
    if order is None:
        payment.status = PaymentStatus.FAILED
        await db.commit()
        raise PaymentError(f"Заказ {payment.order_id} не найден")

    platform = await finance_service.platform_account(db, CURRENCY)
    await finance_service.deposit_from_external(
        db,
        account=platform,
        amount_minor=received_nano,
        ref_type=LedgerRefType.ORDER,
        ref_id=order.id,
        entry_type=LedgerEntryType.PAYMENT_IN,
        comment=f"Оплата заказа {order.id}, tx {payment.tx_hash}",
    )

    payment.status = PaymentStatus.CONFIRMED
    payment.completed_at = datetime.utcnow()

    if received_nano > payment.amount_nano:
        logger.warning(
            "[PAY] Переплата по заказу %s: ожидали %s, пришло %s нанотон. "
            "Товар выдаём, разницу разбирает админ.",
            order.id, payment.amount_nano, received_nano,
        )

    if order.status == OrderStatus.CANCELLED:
        # Платёж пришёл после автоотмены заказа. Товар уже мог уйти другому
        # покупателю, поэтому не выдаём, а зачисляем сумму на внутренний
        # баланс пользователя — деньги не теряются.
        return await _credit_cancelled_order(db, payment, order, received_nano)

    if order.status == OrderStatus.PENDING:
        await complete_order(order, db, received_nano=received_nano)  # внутри делает commit
    else:
        await db.commit()

    logger.info("[PAY] Заказ %s оплачен и обработан", order.id)
    return PaymentStatus.CONFIRMED


async def _credit_cancelled_order(
    db: AsyncSession, payment: Payment, order: Order, received_nano: int
) -> PaymentStatus:
    from services.telegram_service import telegram_service
    from models.user import User

    platform = await finance_service.platform_account(db, CURRENCY)
    user_acc = await finance_service.user_account(db, order.user_id, CURRENCY)

    await finance_service.transfer(
        db,
        src=platform,
        dst=user_acc,
        amount_minor=received_nano,
        entry_type=LedgerEntryType.MANUAL_ADJUST,
        ref_type=LedgerRefType.ORDER,
        ref_id=order.id,
        comment="Платёж поступил после автоотмены заказа — зачислен на баланс",
    )
    await db.commit()

    logger.warning(
        "[PAY] Платёж по отменённому заказу %s зачислен на баланс пользователя", order.id
    )

    user = await db.get(User, order.user_id)
    if user:
        try:
            await telegram_service.send_message(
                user.telegram_id,
                "Оплата поступила после того, как заказ был отменён по таймауту.\n"
                "Сумма зачислена на ваш внутренний баланс — оформите заказ заново "
                "или напишите в поддержку.",
                parse_mode=None,
            )
        except Exception as e:
            logger.error("[PAY] Не удалось уведомить о зачислении: %s", e)

    return PaymentStatus.CONFIRMED


async def _handle_underpaid(db: AsyncSession, payment: Payment, tx) -> PaymentStatus:
    """
    Недоплата: товар не выдаём. Автоматически «доначислять» нельзя — это
    открывает возможность купить товар за копейку.
    """
    payment.status = PaymentStatus.UNDERPAID
    payment.tx_hash = tx.tx_hash
    payment.tx_lt = tx.lt
    payment.from_address = tx.source
    payment.received_nano = tx.value_nano
    await db.commit()

    logger.error(
        "[PAY] НЕДОПЛАТА по заказу %s: ожидали %s, пришло %s нанотон",
        payment.order_id, payment.amount_nano, tx.value_nano,
    )

    from services.telegram_service import telegram_service
    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id,
                f"Недоплата по заказу {payment.order_id}\n"
                f"Ожидали: {payment.amount_nano / 1e9:.9f} {TON_LABEL}\n"
                f"Пришло:  {tx.value_nano / 1e9:.9f} {TON_LABEL}\n"
                f"Отправитель: {tx.source}\n"
                f"Транзакция: {tx.tx_hash}\n\n"
                f"Товар не выдан, требуется решение",
                parse_mode=None,
            )
        except Exception as e:
            logger.error("[PAY] Не удалось отправить алерт о недоплате: %s", e)

    return PaymentStatus.UNDERPAID


async def _handle_expired(db: AsyncSession, payment: Payment) -> PaymentStatus:
    payment.status = PaymentStatus.EXPIRED
    await db.commit()
    logger.info("[PAY] Счёт %s просрочен без оплаты", payment.id)
    return PaymentStatus.EXPIRED


# ---------------------------------------------------------------------------
# Фоновая проверка
# ---------------------------------------------------------------------------

async def poll_pending_payments(db: AsyncSession) -> int:
    """
    Проверяет все ожидающие платежи одним запросом к индексеру.

    Именно одним: опрашивать индексер отдельно на каждый счёт — верный способ
    упереться в лимит запросов. Список транзакций общий, сопоставление
    происходит по комментарию в памяти.
    """
    now = datetime.utcnow()
    window_slack = timedelta(seconds=settings.TON_LOOKAHEAD_SECONDS)

    # EXPIRED сюда включён намеренно. Перевод мог уйти в сеть за секунду до
    # истечения счёта или чуть позже: деньги из кошелька покупателя уже ушли,
    # и перестать их искать значит потерять платёж. Окно ограничено
    # TON_LOOKAHEAD_SECONDS — столько же, сколько окно поиска транзакции,
    # иначе поллер вечно перебирал бы всю историю просроченных счетов.
    pending = (
        await db.execute(
            select(Payment).where(
                Payment.status.in_([
                    PaymentStatus.PENDING, PaymentStatus.SEEN, PaymentStatus.EXPIRED,
                ]),
                Payment.expires_at > now - window_slack,
            )
        )
    ).scalars().all()

    if not pending:
        return 0

    try:
        txs = await ton_service.fetch_incoming_transactions()
    except Exception as e:
        logger.error("[PAY] Индексер недоступен: %s", e)
        return 0

    by_comment = {tx.comment: tx for tx in txs if tx.comment}
    processed = 0

    for payment in pending:
        tx = by_comment.get(payment.payment_comment)
        if tx is None:
            # Уже просроченные помечать повторно незачем
            if (
                payment.status != PaymentStatus.EXPIRED
                and payment.expires_at
                and payment.expires_at < now
            ):
                await _handle_expired(db, payment)
                processed += 1
            continue
        try:
            # Список транзакций уже забран выше — передаём его, чтобы проверка
            # не ходила в индексер повторно на каждый платёж
            await verify_payment(db, payment, txs=txs)
            processed += 1
        except Exception as e:
            logger.exception("[PAY] Ошибка проверки платежа %s: %s", payment.id, e)
            await db.rollback()

    return processed


async def scan_unmatched_transactions(db: AsyncSession, *, limit: int = 100) -> dict:
    """
    Ищет на кошельке платформы переводы, которые не привязаны ни к одному
    подтверждённому платежу, и доводит их до конца.

    Зачем нужно отдельно от поллера: поллер работает в ограниченном временнóм
    окне, иначе он перебирал бы всю историю просроченных счетов при каждом
    прогоне. Но перевод может прийти и через несколько часов после истечения
    счёта — кошелёк лежал, человек отвлёкся. Деньги при этом уже ушли из его
    кошелька и молча зависают у нас.

    Этот метод запускается админом по кнопке и окна не имеет: он сопоставляет
    транзакции с платежами ЛЮБОГО возраста по уникальному комментарию.

    Заказ к этому моменту обычно уже отменён, поэтому сумма попадает на
    внутренний баланс покупателя (см. _confirm -> _credit_cancelled_order).
    """
    txs = await ton_service.fetch_incoming_transactions(limit=limit)
    by_comment = {tx.comment: tx for tx in txs if tx.comment.startswith("MP-")}

    if not by_comment:
        return {"scanned": len(txs), "matched": 0, "settled": [], "orphans": []}

    payments = (
        await db.execute(
            select(Payment).where(Payment.payment_comment.in_(list(by_comment.keys())))
        )
    ).scalars().all()
    by_key = {p.payment_comment: p for p in payments}

    settled: list[dict] = []
    orphans: list[str] = []

    for comment, tx in by_comment.items():
        payment = by_key.get(comment)
        if payment is None:
            # Комментарий нашего формата, но платежа нет: счёт удалили или
            # перевод сделан с чужим комментарием. Разбирается вручную.
            orphans.append(comment)
            continue

        if payment.status == PaymentStatus.CONFIRMED:
            continue
        if tx.value_nano < (payment.amount_nano or 0):
            await _handle_underpaid(db, payment, tx)
            continue

        payment.tx_hash = tx.tx_hash
        payment.tx_lt = tx.lt
        payment.from_address = tx.source
        payment.received_nano = tx.value_nano
        payment.seen_at = payment.seen_at or datetime.utcnow()

        try:
            await _confirm(db, payment, tx.value_nano)
        except Exception as e:
            logger.exception("[PAY] Не удалось зачесть потерянный платёж %s: %s",
                             payment.id, e)
            await db.rollback()
            continue

        settled.append({
            "payment_id": str(payment.id),
            "order_id": str(payment.order_id),
            "comment": comment,
            "received_nano": tx.value_nano,
        })
        logger.warning("[PAY] Потерянный платёж %s зачтён вручную", payment.id)

    return {
        "scanned": len(txs),
        "matched": len(by_comment),
        "settled": settled,
        "orphans": orphans,
    }
