import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import LedgerEntryType, LedgerRefType
from models.order import Order
from models.referral import ReferralTransaction
from models.user import User
from services import finance_service, settings_service
from services.money import from_minor, split_by_bp, to_minor

logger = logging.getLogger(__name__)

REFERRAL_CURRENCY = "USD"


async def process_referral_commission(
    db: AsyncSession,
    order: Order,
    referral_user: User,
) -> None:
    """
    Начисляет реферальную комиссию с оплаченного заказа.

    Что изменилось против исходной версии:

      * процент берётся из настроек (referral_l1_bp), а не из зашитого в .env
        REFERRAL_PERCENTAGE — заказчик меняет его в админке без передеплоя;
      * расчёт целочисленный, в центах: раньше комиссия считалась в Decimal,
        а потом клалась в поле типа Float, и погрешность накапливалась;
      * начисление идёт через журнал проводок и потому идемпотентно — повторный
        вызов (ретрай вебхука, двойное срабатывание) не удвоит сумму. Раньше
        защиты не было вообще: два вебхука по одному заказу = двойная выплата;
      * db.commit() отсюда убран. Функция вызывается из complete_order() внутри
        его транзакции, и коммитить чужую транзакцию на середине нельзя —
        при последующей ошибке откатить уже нечего.

    users.referral_earnings продолжает обновляться как денормализованный кеш:
    его читает API и фронт. Источник правды — журнал.
    """
    if not referral_user.referrer_id:
        return

    referrer = await db.get(User, referral_user.referrer_id)
    if not referrer:
        return

    applies_to = await settings_service.get_list(db, "referral_applies_to")
    if "product" not in applies_to:
        return

    bp = await settings_service.get_int(db, "referral_l1_bp")
    if bp <= 0:
        return

    order_cents = to_minor(Decimal(str(order.total_usdt)), REFERRAL_CURRENCY)
    commission_cents, _ = split_by_bp(order_cents, bp)
    if commission_cents <= 0:
        return

    account = await finance_service.user_account(db, referrer.id, REFERRAL_CURRENCY)

    # Источник — внешний счёт: оплата заказа пока проходит мимо журнала
    # (CryptoBot). На этапе 3, когда платежи начнут зачисляться на счёт
    # платформы, источником станет он.
    result = await finance_service.deposit_from_external(
        db,
        account=account,
        amount_minor=commission_cents,
        ref_type=LedgerRefType.ORDER,
        ref_id=order.id,
        entry_type=LedgerEntryType.REFERRAL_ACCRUAL,
        comment=f"Реферальные {bp / 100:g}% с заказа {order.id}",
    )

    if result.already_applied:
        logger.info(
            "[REFERRAL] Комиссия по заказу %s уже начислена, пропускаем", order.id
        )
        return

    db.add(ReferralTransaction(
        id=uuid.uuid4(),
        referrer_id=referrer.id,
        referral_id=referral_user.id,
        order_id=order.id,
        amount=from_minor(commission_cents, REFERRAL_CURRENCY),
    ))

    # Денормализованный кеш для существующего API
    referrer.referral_earnings = float(
        from_minor(account.balance_minor, REFERRAL_CURRENCY)
    )

    logger.info(
        "[REFERRAL] Начислено %s центов рефереру %s с заказа %s",
        commission_cents, referrer.id, order.id,
    )


async def get_referral_statistics(db: AsyncSession, user: User) -> dict:
    """
    Детальная статистика по рефералам пользователя.

    Исходная версия делала запрос за заказами внутри цикла по рефералам —
    классический N+1. Теперь заказы и транзакции забираются двумя запросами
    и раскладываются в памяти.
    """
    referrals = (
        await db.execute(select(User).where(User.referrer_id == user.id))
    ).scalars().all()

    transactions = (
        await db.execute(
            select(ReferralTransaction).where(ReferralTransaction.referrer_id == user.id)
        )
    ).scalars().all()

    referral_ids = [r.id for r in referrals]

    orders: list[Order] = []
    if referral_ids:
        orders = (
            await db.execute(
                select(Order).where(
                    Order.user_id.in_(referral_ids),
                    Order.status.in_(["paid", "completed"]),
                )
            )
        ).scalars().all()

    orders_by_user: dict[uuid.UUID, list[Order]] = {}
    for order in orders:
        orders_by_user.setdefault(order.user_id, []).append(order)

    commission_by_user: dict[uuid.UUID, Decimal] = {}
    for tx in transactions:
        commission_by_user[tx.referral_id] = (
            commission_by_user.get(tx.referral_id, Decimal(0)) + Decimal(str(tx.amount))
        )

    referral_details = []
    for referral in referrals:
        user_orders = orders_by_user.get(referral.id, [])
        referral_details.append({
            "user_id": str(referral.id),
            "telegram_id": referral.telegram_id,
            "username": referral.username,
            "orders_count": len(user_orders),
            "total_spent": float(sum((Decimal(str(o.total_usdt)) for o in user_orders), Decimal(0))),
            "commission_earned": float(commission_by_user.get(referral.id, Decimal(0))),
        })

    return {
        "referral_code": user.referral_code,
        "referral_count": len(referrals),
        "total_earnings": user.referral_earnings,
        "referrals": referral_details,
    }
