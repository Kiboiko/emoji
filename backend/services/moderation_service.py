"""
Модерация заявок продавцов: публикация, уведомления, автопубликация.

Раньше всё это жило в роутах: публикация — в админском роуте модерации,
уведомление о новой заявке — только в submit_listing. Поэтому правка уже
опубликованного товара снимала его с витрины и отправляла на повторную
проверку, но модераторам об этом не говорила — второй раз уведомление не
приходило. Теперь одно место отвечает за оба случая.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.p2p import ListingStatus, ProductListing, SellerProfile, SellerStatus
from models.product import Product
from models.user import User
from services import audit_service, settings_service, stock_service

logger = logging.getLogger(__name__)

# Картинка для заявки без фото. Файл рисуется при старте бэкенда — см.
# utils/placeholder.py
PLACEHOLDER_IMAGE = "/uploads/products/placeholder.png"

AUTO_PUBLISH_COMMENT = "Опубликовано автоматически: проверенный продавец"


class ModerationError(Exception):
    """Заявку нельзя опубликовать — причина понятна человеку."""


async def approve_listing(
    db: AsyncSession,
    listing: ProductListing,
    seller: SellerProfile,
    *,
    moderator_id: uuid.UUID | None,
    comment: str | None = None,
) -> Product:
    """
    Публикует заявку: заводит товар в каталоге или обновляет существующий.

    Коммит остаётся за вызывающим. moderator_id пустой — публикация без
    проверки (автопубликация проверенного продавца).

    Категория обязательна. Раньше заявка без категории падала в служебную
    «Товары пользователей» — туда сваливалось всё, что продавцы не удосужились
    разложить, и покупатель находил такие товары только случайно.
    """
    if listing.category_id is None:
        raise ModerationError(
            "Продавец не выбрал категорию. Отклоните заявку с комментарием — "
            "пусть выберет и отправит снова."
        )

    listing.moderator_id = moderator_id
    listing.moderation_comment = comment
    listing.moderated_at = datetime.utcnow()

    # Все фотографии, а не только первая: заявка принимает до трёх, и в
    # товар раньше доезжала одна — остальные покупатель не видел никогда
    gallery = [img.url for img in listing.images]
    image_url = gallery[0] if gallery else PLACEHOLDER_IMAGE

    # Заявку могли править после одобрения — тогда она вернулась на модерацию
    # вместе с уже существующим товаром. Заводить второй нельзя: на первый
    # ссылаются корзины и заказы, и в каталоге оказалось бы два одинаковых.
    product = await db.get(Product, listing.product_id) if listing.product_id else None

    if product is None:
        product = Product(
            id=uuid.uuid4(),
            category_id=listing.category_id,
            type="p2p",
            min_quantity=1,
            content_data={"listing_id": str(listing.id)},
            owner_user_id=seller.user_id,
            is_p2p=True,
        )
        db.add(product)

    product.name_ru = listing.name
    # Английского названия может не быть: тогда в каталоге на обоих языках
    # стоит русское — так было всегда, и это лучше пустой строки
    product.name_en = listing.name_en or listing.name
    product.description_ru = listing.description
    # Английского описания может не быть у старых заявок — тогда русское
    product.description_en = listing.description_en or listing.description
    product.price_usdt = listing.price_usd
    product.image_url = image_url
    product.images = gallery
    product.category_id = listing.category_id
    product.max_quantity = listing.quantity
    product.is_active = True
    await db.flush()

    listing.product_id = product.id
    listing.status = ListingStatus.APPROVED
    seller.rejected_streak = 0    # серия отказов прервана

    # Сток — заявленное количество за вычетом проданного и того, что ждёт
    # оплаты. Без стока одну и ту же вещь могли бы оплатить сразу несколько
    # покупателей: max_quantity ограничивает только одну корзину.
    #
    # Считается уже для одобренной заявки: после правки она возвращается
    # на модерацию вместе с товаром, который уже покупали, и полное
    # количество продало бы проданное повторно.
    await stock_service.refresh_p2p_stock(db, product.id)
    return product


async def can_publish_without_review(db: AsyncSession, seller: SellerProfile) -> bool:
    """
    Публикуется ли товар этого продавца без проверки.

    Три условия сразу: опция включена в админке, продавец проверенный
    (галочку ставит администратор) и он не ограничен и не заблокирован.
    Ограниченному продавцу отказы подряд уже стоили доверия — вернуть ему
    публикацию без проверки можно, только сняв ограничение.
    """
    if not seller.is_verified or seller.is_platform:
        return False
    if seller.status != SellerStatus.ACTIVE:
        return False
    return bool(await settings_service.get(db, "p2p_auto_publish_verified"))


def _moderation_keyboard(listing: ProductListing) -> dict:
    # Кнопки прямо в уведомлении: типовое решение по заявке — «да» или «нет»,
    # и заставлять ради него открывать админку на телефоне незачем. Отказ
    # кнопкой уходит без комментария, поэтому кнопка отказа ведёт в админку,
    # где причину можно написать: без причины продавец не знает, что чинить.
    return {
        "inline_keyboard": [[
            {"text": "Одобрить", "callback_data": f"mod:approve:{listing.id}"},
            {"text": "Отклонить", "callback_data": f"mod:reject:{listing.id}"},
        ]]
    }


async def notify_moderators(
    listing: ProductListing,
    seller: SellerProfile,
    *,
    edited: bool = False,
    published: bool = False,
) -> None:
    """
    Сообщает в админский чат о заявке.

    edited — товар правили после публикации и он вернулся на проверку:
    сообщение другое, чтобы по нему было видно, что это не новая заявка.
    published — заявка ушла в каталог без проверки: кнопок нет, сообщение
    только информирует.
    """
    from services.telegram_service import telegram_service

    if published:
        title = "Опубликовано без проверки (проверенный продавец)"
        keyboard = None
    elif edited:
        title = "Товар изменён и снова ждёт проверки"
        keyboard = _moderation_keyboard(listing)
    else:
        title = "Новая заявка на размещение"
        keyboard = _moderation_keyboard(listing)

    text = (
        f"{title}\n"
        f"Продавец: {seller.display_name}\n"
        f"Товар: {listing.name}\n"
        f"Цена: ${listing.price_usd}\n"
        f"Фото: {len(listing.images)}"
    )
    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id, text, parse_mode=None, reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("[P2P] Не удалось уведомить о заявке: %s", e)


async def submit_for_review(
    db: AsyncSession,
    listing: ProductListing,
    seller: SellerProfile,
    *,
    edited: bool,
) -> str:
    """
    Заявка только что перешла в PENDING — решаем, что с ней делать дальше.

    Возвращает «published» (ушла в каталог без проверки) или «pending»
    (ждёт модератора, ему отправлено уведомление). Вызывать после коммита
    самой заявки: уведомление — сетевой запрос, а ждать его в открытой
    транзакции незачем.

    Уведомление уходит КАЖДЫЙ раз, когда заявка попадает на проверку, а не
    только при первой отправке: правка опубликованного товара снимает его с
    витрины, и без уведомления он висел бы в очереди, о которой никто не знает.
    """
    # Фото могли добавить в этой же сессии — коллекция в памяти устарела
    await db.refresh(listing, attribute_names=["images"])

    if await can_publish_without_review(db, seller):
        try:
            await approve_listing(
                db, listing, seller, moderator_id=None, comment=AUTO_PUBLISH_COMMENT,
            )
            # Решение принято системой, а не человеком — это тоже в журнале
            audit_service.log_action(
                db, None, "listing.auto_publish", target_type="listing", target_id=listing.id,
                details={"name": listing.name, "seller": seller.display_name,
                         "edited": edited},
            )
            await db.commit()
        except ModerationError as e:
            # Например, нет категории у старой заявки: доверие не отменяет
            # обязательных полей, заявка идёт к модератору как обычная.
            # Откат не нужен — approve_listing проверяет всё до первой записи
            logger.info("[P2P] Автопубликация невозможна, нужна проверка: %s", e)
        else:
            await notify_moderators(listing, seller, published=True)
            return "published"

    await notify_moderators(listing, seller, edited=edited)
    return "pending"
