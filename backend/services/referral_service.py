import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import LedgerEntryType, LedgerRefType
from models.order import Order, OrderItem
from models.referral import ReferralTransaction
from models.user import User
from services import finance_service, settings_service
from services.money import from_minor, split_by_bp, to_minor

logger = logging.getLogger(__name__)

REFERRAL_CURRENCY = "USD"


def item_source(snapshot: dict) -> str:
    """
    К какому типу отнести позицию заказа: product | subscription | p2p.

    Читаем снимок позиции, а не товар: товар могли снять с продажи или
    переделать, а начислять надо по тому, что человек купил.
    """
    if snapshot.get("is_p2p"):
        return "p2p"
    if snapshot.get("type") == "subscription":
        return "subscription"
    return "product"


async def eligible_cents(db: AsyncSession, order: Order) -> tuple[int, dict[str, int]]:
    """
    Сумма заказа, с которой положены реферальные, в центах.

    Считается по позициям, а не по order.total_usdt: настройка
    referral_applies_to включает и выключает типы покупок по отдельности, и
    заказ из подписки и обычного товара должен дать комиссию только с той
    части, которая разрешена.
    """
    applies_to = set(await settings_service.get_list(db, "referral_applies_to"))

    items = (
        await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars().all()

    by_source: dict[str, int] = {}
    for item in items:
        source = item_source(item.product_snapshot or {})
        if source not in applies_to:
            continue
        cents = to_minor(
            Decimal(str(item.price_usdt)) * item.quantity, REFERRAL_CURRENCY
        )
        by_source[source] = by_source.get(source, 0) + cents

    return sum(by_source.values()), by_source


async def _accrue(
    db: AsyncSession,
    *,
    order: Order,
    buyer: User,
    beneficiary: User,
    level: int,
    bp: int,
    base_cents: int,
    source: str,
) -> bool:
    """Одно начисление конкретному рефереру. True, если деньги реально ушли."""
    commission_cents, _ = split_by_bp(base_cents, bp)
    if commission_cents <= 0:
        return False

    account = await finance_service.user_account(db, beneficiary.id, REFERRAL_CURRENCY)

    # key_suffix обязателен: без него оба уровня дают одинаковый ключ на
    # проводке по внешнему счёту, и начисление второго уровня молча теряется
    # как мнимый повтор. Повторный же вызов по тому же заказу и уровню
    # по-прежнему не удваивает сумму.
    result = await finance_service.deposit_from_external(
        db,
        account=account,
        amount_minor=commission_cents,
        ref_type=LedgerRefType.ORDER,
        ref_id=order.id,
        entry_type=LedgerEntryType.REFERRAL_ACCRUAL,
        comment=f"Реферальные {bp / 100:g}% (ур. {level}) с заказа {order.id}",
        key_suffix=f"l{level}",
    )

    if result.already_applied:
        logger.info(
            "[REFERRAL] Начисление ур.%s по заказу %s уже сделано, пропускаем",
            level, order.id,
        )
        return False

    db.add(ReferralTransaction(
        id=uuid.uuid4(),
        referrer_id=beneficiary.id,
        referral_id=buyer.id,
        order_id=order.id,
        amount=from_minor(commission_cents, REFERRAL_CURRENCY),
        amount_minor=commission_cents,
        currency=REFERRAL_CURRENCY,
        level=level,
        percent_bp_applied=bp,
        source=source,
    ))

    # Денормализованный кеш для существующего API
    beneficiary.referral_earnings = float(
        from_minor(account.balance_minor, REFERRAL_CURRENCY)
    )

    logger.info(
        "[REFERRAL] Ур.%s: начислено %s центов пользователю %s с заказа %s",
        level, commission_cents, beneficiary.id, order.id,
    )
    return True


async def process_referral_commission(
    db: AsyncSession,
    order: Order,
    referral_user: User,
) -> None:
    """
    Начисляет реферальную комиссию с оплаченного заказа.

    Проценты и перечень типов покупок берутся из настроек и меняются в админке
    без передеплоя. Второй уровень (реферер реферера) включается ненулевым
    referral_l2_bp.

    Расчёт целочисленный, в центах: в исходной версии комиссия считалась в
    Decimal, а складывалась в поле типа Float, и погрешность накапливалась.

    Начисление идёт через журнал проводок и потому идемпотентно — повторный
    вызов (ретрай, двойное срабатывание) не удвоит сумму.

    db.commit() отсюда не делается: функция вызывается из complete_order()
    внутри его транзакции, и коммитить чужую транзакцию на середине нельзя.
    """
    if not referral_user.referrer_id:
        return

    base_cents, by_source = await eligible_cents(db, order)
    if base_cents <= 0:
        return

    # Если типов несколько, в source пишем преобладающий по сумме: поле нужно
    # для отчётности, а не для расчёта, и дробить одно начисление на несколько
    # записей ради него значило бы усложнять журнал без пользы.
    source = max(by_source, key=by_source.get)

    l1 = await db.get(User, referral_user.referrer_id)
    if l1 is None:
        return

    bp_l1 = await settings_service.get_int(db, "referral_l1_bp")
    if bp_l1 > 0:
        await _accrue(
            db, order=order, buyer=referral_user, beneficiary=l1,
            level=1, bp=bp_l1, base_cents=base_cents, source=source,
        )

    bp_l2 = await settings_service.get_int(db, "referral_l2_bp")
    if bp_l2 <= 0 or not l1.referrer_id:
        return

    l2 = await db.get(User, l1.referrer_id)
    if l2 is None:
        return

    # Защита от замкнутых цепочек (A пригласил B, B значится реферером A):
    # без неё один и тот же человек получил бы оба уровня с одной покупки.
    if l2.id in (l1.id, referral_user.id):
        logger.warning(
            "[REFERRAL] Цепочка рефералов зациклена на пользователе %s, "
            "второй уровень пропущен", l2.id,
        )
        return

    await _accrue(
        db, order=order, buyer=referral_user, beneficiary=l2,
        level=2, bp=bp_l2, base_cents=base_cents, source=source,
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

    # Разносим по прямым рефералам только первый уровень: у начислений
    # второго referral_id — это покупатель-внук, которого в списке прямых
    # рефералов нет, и его сумма в разбивке по людям оказалась бы потеряна.
    # Поэтому второй уровень показываем отдельной строкой.
    commission_by_user: dict[uuid.UUID, Decimal] = {}
    level2_total = Decimal(0)
    for tx in transactions:
        if tx.level == 2:
            level2_total += Decimal(str(tx.amount))
            continue
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

    # Ставку показываем самому рефереру: без неё он видит начисления, но не
    # понимает, от чего они считаются, и не может проверить сумму.
    percent_bp = await settings_service.get_int(db, "referral_l1_bp")

    return {
        "referral_code": user.referral_code,
        "referral_count": len(referrals),
        "total_earnings": user.referral_earnings,
        "level2_earnings": float(level2_total),
        "referral_percent": percent_bp / 100,
        "paid_orders_count": len(orders),
        "referrals": referral_details,
    }
