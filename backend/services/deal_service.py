"""
P2P-сделки: escrow, конечный автомат, разрешение споров.

Деньги покупателя лежат замороженными на счёте платформы с момента оплаты и
до подтверждения получения. Продавцу они не начислены — он видит сделку, но
не баланс. Это и есть смысл escrow: платформа держит средства, пока стороны
не закроют сделку.

    [created] --оплата--> [paid_escrow] --> [chat_opened]
                                                 |
                        продавец «отправил» ------+
                                                 v
                                        [delivered_claimed]
                                          |            |
            покупатель подтвердил / дедлайн|            | спор
                                          v            v
                                    [confirmed]    [disputed]
                                          |            |
                                  выплата |            | решение админа
                                          v            v
                                    [released]   [released] | [refunded]

Выплата продавцу наружу — отдельное ручное действие через заявку на вывод.
Здесь только внутреннее начисление.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import LedgerEntryType, LedgerRefType
from models.p2p import Deal, DealStatus, MessageDirection, SellerProfile
from models.user import User
from services import finance_service, settings_service
from services.money import split_by_bp

logger = logging.getLogger(__name__)

CURRENCY = "TON"

# Из каких состояний сделка ещё может быть оспорена
DISPUTABLE = (
    DealStatus.PAID_ESCROW,
    DealStatus.CHAT_OPENED,
    DealStatus.DELIVERED_CLAIMED,
)

# Терминальные состояния: дальше сделка не меняется
FINAL = (DealStatus.RELEASED, DealStatus.REFUNDED, DealStatus.CANCELLED)


class DealError(Exception):
    pass


# ---------------------------------------------------------------------------
# Создание сделок при оплате заказа
# ---------------------------------------------------------------------------

async def create_deals_for_order(
    db: AsyncSession,
    *,
    order,
    buyer: User,
    items: list,
    received_nano: int,
) -> list[Deal]:
    """
    Создаёт сделки по P2P-позициям заказа и замораживает деньги.

    Одна позиция = одна сделка. Если покупатель взял товары двух продавцов,
    сделок будет две: у каждой свой чат, свой срок подтверждения и свой исход.
    Смешивать их нельзя — один продавец может отправить товар, другой нет.

    Сумма делится пропорционально стоимости позиции в заказе и считается от
    ФАКТИЧЕСКИ поступивших нанотон: курс на момент оплаты уже зафиксирован.
    """
    from models.product import Product
    from services.money import to_minor
    from decimal import Decimal

    p2p_items = [i for i in items if i.product_snapshot.get("is_p2p")]
    if not p2p_items:
        return []

    if not received_nano:
        logger.error(
            "[DEAL] Заказ %s содержит P2P-товары, но сумма платежа не передана — "
            "сделки не созданы", order.id,
        )
        return []

    total_cents = to_minor(Decimal(str(order.total_usdt)), "USD")
    if not total_cents:
        return []

    commission_bp = await settings_service.get_int(db, "commission_p2p_bp")
    deadline_days = await settings_service.get_int(db, "p2p_confirm_deadline_days")

    platform = await finance_service.platform_account(db, CURRENCY)
    deals: list[Deal] = []

    for item in p2p_items:
        seller_id = item.product_snapshot.get("owner_user_id")
        if not seller_id:
            logger.error("[DEAL] У P2P-позиции %s нет владельца — сделка не создана", item.id)
            continue

        item_cents = to_minor(Decimal(str(item.price_usdt)) * item.quantity, "USD")
        item_nano = received_nano * item_cents // total_cents
        commission_nano, seller_nano = split_by_bp(item_nano, commission_bp)

        deal = Deal(
            id=uuid.uuid4(),
            order_id=order.id,
            order_item_id=item.id,
            buyer_id=buyer.id,
            seller_id=uuid.UUID(seller_id),
            product_id=item.product_id,
            product_name=item.product_snapshot.get("name_ru", "Товар"),
            amount_nano=item_nano,
            commission_nano=commission_nano,
            seller_amount_nano=seller_nano,
            status=DealStatus.PAID_ESCROW,
            confirm_deadline_at=datetime.utcnow() + timedelta(days=deadline_days),
        )
        db.add(deal)
        await db.flush()

        # Замораживаем сумму сделки на счёте платформы. Деньги физически там,
        # но платформа не может их потратить: available = balance - hold.
        await finance_service.hold(
            db,
            account=platform,
            amount_minor=item_nano,
            entry_type=LedgerEntryType.ESCROW_HOLD,
            ref_type=LedgerRefType.DEAL,
            ref_id=deal.id,
            comment=f"Escrow по сделке #{deal.number}",
        )

        deals.append(deal)
        logger.info(
            "[DEAL] Сделка #%s создана: %s нанотон в escrow, дедлайн %s",
            deal.number, item_nano, deal.confirm_deadline_at,
        )

    return deals


# ---------------------------------------------------------------------------
# Переходы
# ---------------------------------------------------------------------------

async def mark_delivered(db: AsyncSession, deal: Deal, seller: User) -> Deal:
    """Продавец отмечает, что отправил товар. Запускает отсчёт автоподтверждения."""
    if deal.seller_id != seller.id:
        raise DealError("Только продавец может отметить отправку")
    if deal.status not in (DealStatus.PAID_ESCROW, DealStatus.CHAT_OPENED):
        raise DealError(f"Нельзя отметить отправку в статусе {deal.status.value}")

    deadline_days = await settings_service.get_int(db, "p2p_confirm_deadline_days")

    deal.status = DealStatus.DELIVERED_CLAIMED
    deal.delivered_claimed_at = datetime.utcnow()
    # Дедлайн отсчитывается от отправки, а не от оплаты: продавец мог
    # отправить товар не сразу, и покупателю нужно время на проверку
    deal.confirm_deadline_at = deal.delivered_claimed_at + timedelta(days=deadline_days)

    logger.info("[DEAL] #%s: продавец отметил отправку", deal.number)
    return deal


async def confirm_receipt(
    db: AsyncSession, deal: Deal, buyer: User | None = None, *, auto: bool = False
) -> Deal:
    """
    Покупатель подтвердил получение — деньги уходят продавцу.

    auto=True для автоподтверждения по дедлайну: без него деньги продавца
    зависали бы навсегда, если покупатель просто исчез.
    """
    if buyer is not None and deal.buyer_id != buyer.id:
        raise DealError("Только покупатель может подтвердить получение")
    if deal.status in FINAL:
        return deal
    if deal.status == DealStatus.DISPUTED:
        raise DealError("По сделке открыт спор, подтверждение недоступно")
    if deal.status not in (DealStatus.PAID_ESCROW, DealStatus.CHAT_OPENED,
                           DealStatus.DELIVERED_CLAIMED):
        raise DealError(f"Нельзя подтвердить в статусе {deal.status.value}")

    deal.status = DealStatus.CONFIRMED
    deal.confirmed_at = datetime.utcnow()

    await _release_to_seller(db, deal, reason="автоподтверждение" if auto else "подтверждено покупателем")
    return deal


async def _release_to_seller(db: AsyncSession, deal: Deal, *, reason: str) -> None:
    """Снимает заморозку и начисляет продавцу его долю. Комиссия остаётся платформе."""
    platform = await finance_service.platform_account(db, CURRENCY)
    seller_account = await finance_service.user_account(db, deal.seller_id, CURRENCY)

    # Сначала разморозка, иначе перевод упрётся в проверку доступных средств
    await finance_service.release_hold(
        db,
        account=platform,
        amount_minor=deal.amount_nano,
        entry_type=LedgerEntryType.ESCROW_RELEASE,
        ref_type=LedgerRefType.DEAL,
        ref_id=deal.id,
        comment=f"Сделка #{deal.number}: {reason}",
    )
    await finance_service.post(
        db,
        ref_type=LedgerRefType.DEAL,
        ref_id=deal.id,
        comment=f"Сделка #{deal.number}: выплата продавцу",
        postings=[
            finance_service.Posting(
                account=platform, entry_type=LedgerEntryType.SELLER_ACCRUAL,
                amount_minor=-deal.seller_amount_nano, key_suffix="src",
            ),
            finance_service.Posting(
                account=seller_account, entry_type=LedgerEntryType.SELLER_ACCRUAL,
                amount_minor=deal.seller_amount_nano, key_suffix="dst",
            ),
        ],
    )

    deal.status = DealStatus.RELEASED
    deal.released_at = datetime.utcnow()
    deal.chat_closed = True

    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == deal.seller_id))
    ).scalars().first()
    if profile:
        profile.deals_completed += 1

    logger.info(
        "[DEAL] #%s завершена: продавцу %s, комиссия %s нанотон",
        deal.number, deal.seller_amount_nano, deal.commission_nano,
    )
    await db.flush()
    await complete_order_if_settled(db, deal.order_id)


async def complete_order_if_settled(db: AsyncSession, order_id: uuid.UUID) -> bool:
    """
    Переводит заказ в COMPLETED, когда по нему больше нечего доделывать.

    Заказ с P2P-товаром остаётся в PAID, пока идут сделки. Без этой функции он
    висел бы в PAID вечно: отзыв по нему было бы не оставить, а в отчётах он
    выглядел бы незакрытым.

    Условия: все сделки заказа в финальном статусе И в заказе нет услуг,
    ждущих ручной обработки админом (их закрывает отдельный сценарий).
    """
    from models.order import Order, OrderItem, OrderStatus

    order = await db.get(Order, order_id)
    if order is None or order.status != OrderStatus.PAID:
        return False

    statuses = (
        await db.execute(select(Deal.status).where(Deal.order_id == order_id))
    ).scalars().all()
    if not statuses or any(st not in FINAL for st in statuses):
        return False

    items = (
        await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    ).scalars().all()
    if any(i.product_snapshot.get("type") == "service" for i in items):
        return False

    order.status = OrderStatus.COMPLETED
    logger.info("[DEAL] Заказ %s закрыт: все сделки завершены", order_id)
    return True


async def open_dispute(db: AsyncSession, deal: Deal, user: User, reason: str) -> Deal:
    """
    Открытие спора.

    Доступно только ДО подтверждения получения: после того как покупатель
    сказал «всё в порядке» и деньги ушли продавцу, откатывать нечего. Это
    записано в условиях площадки.
    """
    if user.id not in (deal.buyer_id, deal.seller_id):
        raise DealError("Спор может открыть только участник сделки")
    if deal.status not in DISPUTABLE:
        raise DealError(
            f"Спор недоступен в статусе {deal.status.value}. "
            "Сообщить о проблеме нужно до подтверждения получения."
        )

    deal.status = DealStatus.DISPUTED
    deal.dispute_opened_at = datetime.utcnow()
    deal.dispute_opened_by = user.id
    deal.dispute_reason = reason
    # Автоподтверждение не должно сработать, пока спор не разобран
    deal.confirm_deadline_at = None

    logger.warning("[DEAL] #%s: открыт спор пользователем %s", deal.number, user.id)
    return deal


async def resolve_dispute(
    db: AsyncSession, deal: Deal, admin: User, *, release: bool, comment: str | None = None
) -> Deal:
    """
    Решение админа по спору: деньги продавцу или возврат покупателю.

    Возврат зачисляется на внутренний баланс покупателя, а не отправляется в
    блокчейн: выплаты наружу делаются вручную через заявку на вывод, чтобы не
    держать приватный ключ горячего кошелька на сервере.
    """
    if deal.status != DealStatus.DISPUTED:
        raise DealError(f"Сделка не в споре (статус {deal.status.value})")

    deal.resolved_by_admin_id = admin.id
    deal.resolution_comment = comment

    if release:
        await _release_to_seller(db, deal, reason="решение по спору в пользу продавца")
        return deal

    platform = await finance_service.platform_account(db, CURRENCY)
    buyer_account = await finance_service.user_account(db, deal.buyer_id, CURRENCY)

    await finance_service.release_hold(
        db,
        account=platform,
        amount_minor=deal.amount_nano,
        entry_type=LedgerEntryType.ESCROW_REFUND,
        ref_type=LedgerRefType.DEAL,
        ref_id=deal.id,
        comment=f"Сделка #{deal.number}: возврат покупателю",
    )
    # Возвращаем ВСЮ сумму, включая комиссию: сделка не состоялась,
    # удерживать комиссию не за что
    await finance_service.post(
        db,
        ref_type=LedgerRefType.DEAL,
        ref_id=deal.id,
        comment=f"Сделка #{deal.number}: возврат покупателю",
        postings=[
            finance_service.Posting(
                account=platform, entry_type=LedgerEntryType.ESCROW_REFUND,
                amount_minor=-deal.amount_nano, key_suffix="refund_src",
            ),
            finance_service.Posting(
                account=buyer_account, entry_type=LedgerEntryType.ESCROW_REFUND,
                amount_minor=deal.amount_nano, key_suffix="refund_dst",
            ),
        ],
    )

    deal.status = DealStatus.REFUNDED
    deal.refunded_at = datetime.utcnow()
    deal.chat_closed = True

    logger.warning("[DEAL] #%s: возврат покупателю %s нанотон", deal.number, deal.amount_nano)
    await db.flush()
    await complete_order_if_settled(db, deal.order_id)
    return deal


# ---------------------------------------------------------------------------
# Фоновая задача
# ---------------------------------------------------------------------------

async def auto_confirm_due_deals(db: AsyncSession) -> int:
    """
    Автоподтверждение сделок, по которым истёк срок.

    Без него деньги продавца зависали бы навсегда, если покупатель получил
    товар и просто не нажал кнопку. Спор блокирует автоподтверждение:
    confirm_deadline_at обнуляется при открытии спора.
    """
    from services.telegram_service import telegram_service

    now = datetime.utcnow()
    due = (
        await db.execute(
            select(Deal).where(
                Deal.status == DealStatus.DELIVERED_CLAIMED,
                Deal.confirm_deadline_at.isnot(None),
                Deal.confirm_deadline_at <= now,
            )
        )
    ).scalars().all()

    if not due:
        return 0

    for deal in due:
        try:
            await confirm_receipt(db, deal, auto=True)
        except DealError as e:
            logger.error("[DEAL] Автоподтверждение #%s не удалось: %s", deal.number, e)
            continue

        for user_id, text in (
            (deal.buyer_id, f"Сделка #{deal.number} закрыта автоматически: "
                            f"срок подтверждения истёк."),
            (deal.seller_id, f"Сделка #{deal.number} завершена, деньги начислены "
                             f"на ваш баланс."),
        ):
            user = await db.get(User, user_id)
            if user:
                try:
                    await telegram_service.send_message(user.telegram_id, text, parse_mode=None)
                except Exception as e:
                    logger.warning("[DEAL] Не удалось уведомить %s: %s", user_id, e)

    await db.commit()
    logger.info("[DEAL] Автоподтверждено сделок: %d", len(due))
    return len(due)
