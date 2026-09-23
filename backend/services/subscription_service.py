"""
Подписки на закрытые каналы: выдача доступа, продление, отзыв, сплит комиссии.

Ограничения Telegram, которые определяют всю схему (см. WORK_PLAN.md, часть III):

  * бот НЕ может добавить пользователя в канал по user_id — доступ выдаётся
    персональной одноразовой инвайт-ссылкой, по которой человек входит сам;
  * чтобы отозвать доступ, нужен banChatMember + unbanChatMember: один только
    ban оставляет человека в вечном бане и он не сможет купить подписку снова;
  * бот обязан быть администратором канала с правами приглашать и
    ограничивать участников.

Настоящего автопродления в TON не существует: каждая транзакция требует
подписи пользователя в кошельке. Поэтому вместо автосписания — напоминание и
кнопка «продлить».
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.finance import LedgerEntryType, LedgerRefType
from models.product import Product
from models.subscription import (
    AccessAction, Channel, ChannelStatus, Subscription, SubscriptionAccessLog,
    SubscriptionPlan, SubscriptionStatus,
)
from models.user import User
from services import finance_service, settings_service
from services.money import split_by_bp
from services.telegram_service import (
    TelegramApiError, channel_access, telegram_service,
)

logger = logging.getLogger(__name__)

CURRENCY = "TON"
INVITE_TTL_SECONDS = 86_400  # сутки на то, чтобы перейти по ссылке


class SubscriptionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Журнал доступа
# ---------------------------------------------------------------------------

def _log(db: AsyncSession, subscription: Subscription, action: AccessAction, **detail) -> None:
    db.add(SubscriptionAccessLog(
        id=uuid.uuid4(),
        subscription_id=subscription.id,
        action=action,
        detail=detail or None,
    ))


# ---------------------------------------------------------------------------
# Подключение канала
# ---------------------------------------------------------------------------

async def verify_channel(db: AsyncSession, channel: Channel) -> tuple[bool, str | None]:
    """
    Проверяет права бота в канале и запоминает результат.

    Вызывается автором по кнопке «Проверить» и повторно при публикации:
    права могли отозвать уже после подключения.
    """
    ok, error = await channel_access.check_bot_is_admin(channel.telegram_chat_id)

    channel.bot_is_admin = ok
    channel.bot_checked_at = datetime.utcnow()
    channel.bot_check_error = error

    if ok:
        try:
            chat = await channel_access.get_chat(channel.telegram_chat_id)
            channel.title = chat.get("title") or channel.title
            channel.username = chat.get("username")
            await refresh_avatar(channel, chat)
        except TelegramApiError as e:
            logger.warning("[SUB] Не удалось обновить данные канала: %s", e)

    # Название и аватар видны в каталоге, поэтому после каждой проверки
    # подтягиваем их в товары тарифов: иначе канал переименовали, а в витрине
    # висит старое имя.
    await sync_plan_products(db, channel)

    return ok, error


async def refresh_avatar(channel: Channel, chat: dict) -> None:
    """
    Кладёт аватар канала в uploads и прописывает путь каналу.

    Имя файла — id канала, а не случайный uuid: при переименовании аватара в
    Telegram файл перезаписывается, и старые копии не копятся в томе.
    Суффикс времени в ссылке заставляет браузер и nginx (uploads отдаются с
    immutable на 30 дней) забрать новую картинку.
    """
    content = await channel_access.download_chat_photo(chat)
    if not content:
        return

    directory = Path(settings.UPLOAD_DIR) / "channels"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{channel.id}.jpg"

    async with aiofiles.open(directory / name, "wb") as out:
        await out.write(content)

    channel.avatar_url = f"/uploads/channels/{name}?v={int(datetime.utcnow().timestamp())}"


async def sync_plan_products(db: AsyncSession, channel: Channel) -> None:
    """
    Приводит товары тарифов в соответствие каналу.

    Главное здесь — is_active. Товар тарифа заводится в момент создания
    тарифа, то есть до модерации, и без этой связки подписка попадала в
    каталог, пока канал ещё лежал в черновике. Продаваться она должна ровно
    тогда, когда канал опубликован.
    """
    plans = (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.channel_id == channel.id)
        )
    ).scalars().all()

    product_ids = [p.product_id for p in plans if p.product_id]
    if not product_ids:
        return

    products = (
        await db.execute(select(Product).where(Product.id.in_(product_ids)))
    ).scalars().all()
    by_id = {p.id: p for p in products}

    live = channel.status == ChannelStatus.ACTIVE

    for plan in plans:
        product = by_id.get(plan.product_id)
        if product is None:
            continue
        # Тариф могли отключить отдельно от канала
        product.is_active = live and plan.is_active
        product.name_ru = f"{channel.title} — {plan.title_ru}"
        product.name_en = f"{channel.title} — {plan.title_en}"
        if channel.avatar_url:
            product.image_url = channel.avatar_url


# ---------------------------------------------------------------------------
# Выдача доступа
# ---------------------------------------------------------------------------

async def issue_invite(db: AsyncSession, subscription: Subscription) -> str | None:
    """
    Создаёт персональную одноразовую ссылку и сохраняет её в подписке.

    Ошибку Telegram не поднимаем наверх: подписка уже оплачена, и падение
    выдачи не должно откатывать оплату. Проблема фиксируется в журнале, чтобы
    админ мог выдать доступ вручную.
    """
    channel = subscription.channel or await db.get(Channel, subscription.channel_id)
    user = subscription.user or await db.get(User, subscription.user_id)

    # Сначала снимаем бан, если он есть. «Удалить участника» через интерфейс
    # Telegram — это бан: человек остаётся в чёрном списке и не может войти ни
    # по какой ссылке, получая «срок действия ссылки истёк». Выглядит как
    # сломанная оплата, хотя ссылка живая.
    if user:
        try:
            if await channel_access.ensure_not_banned(channel.telegram_chat_id, user.telegram_id):
                logger.info(
                    "[SUB] Снят бан с %s в канале %s перед выдачей доступа",
                    user.telegram_id, channel.telegram_chat_id,
                )
                _log(db, subscription, AccessAction.RESTORED)
        except TelegramApiError as e:
            # Не фатально: возможно, прав не хватает. Ссылку всё равно создадим,
            # а причина останется в журнале.
            logger.warning("[SUB] Не удалось снять бан: %s", e)

    try:
        result = await channel_access.create_invite_link(
            channel.telegram_chat_id,
            expire_seconds=INVITE_TTL_SECONDS,
            name=f"sub-{str(subscription.id)[:8]}",
        )
    except TelegramApiError as e:
        logger.error("[SUB] Не удалось создать инвайт для %s: %s", subscription.id, e)
        _log(db, subscription, AccessAction.INVITE_FAILED, error=str(e))
        await _alert_admins(
            f"Не удалось выдать доступ в канал «{channel.title}»\n"
            f"Подписка: {subscription.id}\n"
            f"Причина: {e.description}\n\n"
            f"Выдайте доступ вручную"
        )
        return None

    subscription.invite_link = result["invite_link"]
    subscription.invite_link_expires_at = datetime.utcnow() + timedelta(seconds=INVITE_TTL_SECONDS)
    _log(db, subscription, AccessAction.INVITE_CREATED, link=result["invite_link"])

    return subscription.invite_link


async def revoke_access(
    db: AsyncSession,
    subscription: Subscription,
    *,
    status: SubscriptionStatus = SubscriptionStatus.EXPIRED,
    reason: str = "срок подписки истёк",
) -> bool:
    """
    Отзывает доступ: удаляет пользователя из канала и закрывает подписку.

    Ошибки Telegram не считаются фатальными — канал мог быть удалён, бота
    могли разжаловать, пользователь мог выйти сам. В этом случае подписка всё
    равно закрывается (иначе она будет висеть активной вечно), но событие
    попадает в журнал и админу уходит алерт.
    """
    channel = subscription.channel or await db.get(Channel, subscription.channel_id)
    user = subscription.user or await db.get(User, subscription.user_id)

    success = True
    if channel and user:
        try:
            await channel_access.kick_member(channel.telegram_chat_id, user.telegram_id)
            _log(db, subscription, AccessAction.KICKED, reason=reason)
        except TelegramApiError as e:
            success = False
            logger.error("[SUB] Не удалось удалить %s из канала %s: %s",
                         user.telegram_id, channel.telegram_chat_id, e)
            _log(db, subscription, AccessAction.KICK_FAILED, error=str(e))
            await _alert_admins(
                f"Не удалось удалить пользователя из канала «{channel.title}»\n"
                f"Подписка: {subscription.id}\n"
                f"Причина: {e.description}"
            )

    # Сгоревшая ссылка не должна остаться рабочей
    if subscription.invite_link and channel:
        try:
            await channel_access.revoke_invite_link(
                channel.telegram_chat_id, subscription.invite_link
            )
        except TelegramApiError:
            pass

    subscription.status = status
    subscription.revoked_at = datetime.utcnow()
    subscription.invite_link = None
    return success


# ---------------------------------------------------------------------------
# Покупка и продление
# ---------------------------------------------------------------------------

async def activate_or_extend(
    db: AsyncSession,
    *,
    user: User,
    plan: SubscriptionPlan,
    order_id: uuid.UUID,
    quantity: int = 1,
) -> Subscription:
    """
    Активирует подписку или продлевает существующую.

    Продление СУММИРУЕТ срок, а не перезаписывает: пользователь, купивший
    второй месяц до окончания первого, не должен терять оплаченные дни.
    """
    days = plan.duration_days * max(quantity, 1)
    now = datetime.utcnow()

    existing = (
        await db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.channel_id == plan.channel_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
    ).scalars().first()

    if existing is not None:
        base = existing.expires_at if existing.expires_at and existing.expires_at > now else now
        existing.expires_at = base + timedelta(days=days)
        existing.plan_id = plan.id
        existing.reminder_sent_for_days = None  # напомнить снова перед новым сроком
        _log(db, existing, AccessAction.EXTENDED, days=days, order_id=str(order_id))
        logger.info("[SUB] Подписка %s продлена на %d дн. до %s",
                    existing.id, days, existing.expires_at)
        return existing

    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=user.id,
        channel_id=plan.channel_id,
        plan_id=plan.id,
        order_id=order_id,
        status=SubscriptionStatus.ACTIVE,
        started_at=now,
        expires_at=now + timedelta(days=days),
    )
    db.add(subscription)
    await db.flush()

    subscription.channel = await db.get(Channel, plan.channel_id)
    await issue_invite(db, subscription)

    logger.info("[SUB] Подписка %s создана до %s", subscription.id, subscription.expires_at)
    return subscription


async def split_subscription_payment(
    db: AsyncSession,
    *,
    channel: Channel,
    order_id: uuid.UUID,
    amount_nano: int,
    key_suffix: str,
) -> None:
    """
    Делит поступившую сумму: комиссия остаётся платформе, остаток начисляется
    автору канала.

    Деньги уже лежат на счёте платформы (их зачислил payment_service при
    подтверждении оплаты), поэтому здесь только внутренний перевод.

    Выплата автору наружу — отдельное ручное действие через заявку на вывод.
    Автоматический перевод в блокчейн требовал бы приватного ключа горячего
    кошелька на сервере, что для площадки, держащей чужие деньги, лишний риск.
    """
    if amount_nano <= 0:
        return

    bp = await settings_service.get_int(db, "commission_subscription_bp")
    commission_nano, author_nano = split_by_bp(amount_nano, bp)

    if author_nano <= 0:
        return

    platform = await finance_service.platform_account(db, CURRENCY)
    author = await finance_service.user_account(db, channel.owner_user_id, CURRENCY)

    await finance_service.post(
        db,
        ref_type=LedgerRefType.ORDER,
        ref_id=order_id,
        comment=f"Подписка на «{channel.title}», комиссия {bp / 100:g}%",
        postings=[
            finance_service.Posting(
                account=platform, entry_type=LedgerEntryType.AUTHOR_ACCRUAL,
                amount_minor=-author_nano, key_suffix=f"{key_suffix}:src",
            ),
            finance_service.Posting(
                account=author, entry_type=LedgerEntryType.AUTHOR_ACCRUAL,
                amount_minor=author_nano, key_suffix=f"{key_suffix}:dst",
            ),
        ],
    )

    logger.info(
        "[SUB] Сплит по каналу %s: автору %d, комиссия %d нанотон",
        channel.id, author_nano, commission_nano,
    )


# ---------------------------------------------------------------------------
# Фоновые задачи
# ---------------------------------------------------------------------------

async def expire_due_subscriptions(db: AsyncSession) -> int:
    """Закрывает подписки с истёкшим сроком и отзывает доступ."""
    now = datetime.utcnow()
    due = (
        await db.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= now,
            )
        )
    ).scalars().all()

    if not due:
        return 0

    logger.info("[SUB] Истекло подписок: %d", len(due))

    for subscription in due:
        subscription.channel = await db.get(Channel, subscription.channel_id)
        subscription.user = await db.get(User, subscription.user_id)

        await revoke_access(db, subscription)

        if subscription.user:
            try:
                await telegram_service.send_message(
                    subscription.user.telegram_id,
                    f"Подписка на «{subscription.channel.title}» закончилась.\n"
                    f"Доступ в канал закрыт. Продлить можно в приложении.",
                    parse_mode=None,
                )
            except Exception as e:
                logger.warning("[SUB] Не удалось уведомить об окончании: %s", e)

    await db.commit()
    return len(due)


async def send_expiry_reminders(db: AsyncSession) -> int:
    """
    Напоминает об окончании подписки за 3 дня и за 1 день.

    reminder_sent_for_days не даёт слать одно и то же напоминание при каждом
    прогоне джобы.
    """
    now = datetime.utcnow()
    sent = 0

    for days_left in (3, 1):
        window_end = now + timedelta(days=days_left)
        window_start = window_end - timedelta(days=1)

        subscriptions = (
            await db.execute(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at > window_start,
                    Subscription.expires_at <= window_end,
                )
            )
        ).scalars().all()

        for subscription in subscriptions:
            if subscription.reminder_sent_for_days is not None and \
                    subscription.reminder_sent_for_days <= days_left:
                continue

            channel = await db.get(Channel, subscription.channel_id)
            user = await db.get(User, subscription.user_id)
            if not channel or not user:
                continue

            try:
                await telegram_service.send_message(
                    user.telegram_id,
                    f"Подписка на «{channel.title}» заканчивается "
                    f"{'завтра' if days_left == 1 else f'через {days_left} дня'}.\n"
                    f"Продлить можно в приложении.",
                    parse_mode=None,
                )
                subscription.reminder_sent_for_days = days_left
                sent += 1
            except Exception as e:
                logger.warning("[SUB] Не удалось отправить напоминание: %s", e)

    if sent:
        await db.commit()
    return sent


async def _alert_admins(text: str) -> None:
    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(chat_id, text, parse_mode=None)
        except Exception as e:
            logger.error("[SUB] Не удалось отправить алерт админу: %s", e)
