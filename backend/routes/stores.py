"""
Витрины магазинов.

Каждый товар продаётся кем-то: пользователем-продавцом, автором канала или
самой площадкой. Раньше товар площадки не имел лица вовсе — в каталоге он
приходил без автора, и страницы, на которую можно перейти, не было.

Площадка здесь — такой же магазин, как остальные: отдельная строка в
seller_profiles с пометкой is_platform. Разница только в том, что её
заполняет администратор, а не владелец.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.p2p import SellerProfile, SellerStatus
from models.product import Product
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionPlan, SubscriptionStatus,
)

router = APIRouter(prefix="/api/stores", tags=["Stores"])


async def _product_cards(db: AsyncSession, products: list, lang: str) -> list[dict]:
    """
    Товары витрины в том же виде, что и в каталоге.

    Сначала здесь был свой урезанный набор полей — и витрина разошлась с
    каталогом: в каталоге у карточки появились оценка и пометка хита, а здесь
    осталась старая вёрстка. Общий вид — единственный способ не расходиться дальше:
    фронт рисует оба экрана одним компонентом.
    """
    # Импорт внутри функции: модули роутов грузятся по очереди, и верхнеуровневый
    # ссылался бы на порядок регистрации в main.py
    from routes.products import (
        _author_fields, _channels_by_product, _platform_store,
        _ratings_by_product, _sellers_by_user,
    )
    from schemas.product import ProductLocalized

    if not products:
        return []

    sellers = await _sellers_by_user(db, products)
    channels = await _channels_by_product(db, products)
    platform = await _platform_store(db)
    ratings = await _ratings_by_product(db, products)

    return [
        ProductLocalized(
            id=p.id,
            name=p.name_ru if lang == "ru" else p.name_en,
            description=p.description_ru if lang == "ru" else p.description_en,
            price_usdt=p.price_usdt,
            price_ton=p.price_ton,
            image_url=p.image_url,
            category_id=p.category_id,
            is_top=p.is_top,
            type=p.type,
            min_quantity=p.min_quantity,
            max_quantity=p.max_quantity,
            created_at=p.created_at,
            is_active=p.is_active,
            is_p2p=p.is_p2p,
            **_author_fields(p, sellers, channels, platform),
            **ratings.get(p.id, {}),
        ).model_dump(mode="json")
        for p in products
    ]


async def _seller_products(db: AsyncSession, seller: SellerProfile, lang: str) -> list[dict]:
    """
    Товары магазина.

    У площадки товары опознаются пустым владельцем, у продавца — своим
    user_id. Снятые с продажи не показываем: витрина магазина — это то, что
    можно купить сейчас.
    """
    stmt = select(Product).where(Product.is_active.is_(True))

    if seller.is_platform:
        # Товары подписок формально тоже без владельца, но принадлежат каналу
        # автора, а не площадке — их отсекаем по типу
        stmt = stmt.where(
            Product.owner_user_id.is_(None),
            Product.type != "subscription",
        )
    else:
        stmt = stmt.where(Product.owner_user_id == seller.user_id)

    stmt = stmt.order_by(
        Product.is_top.desc(), Product.sort_order.desc(), Product.created_at.desc()
    )
    rows = (await db.execute(stmt)).scalars().all()
    return await _product_cards(db, list(rows), lang)


@router.get("")
async def store_list(
    limit: int = Query(12, ge=1, le=40),
    db: AsyncSession = Depends(get_db),
):
    """
    Магазины, у которых сейчас есть что купить.

    Нужен главной. Товар теперь принадлежит магазину, но попасть в магазин
    можно было только через карточку товара — то есть сначала выбрать вещь,
    а уже потом узнать продавца. Здесь порядок обратный.

    Пустые магазины не показываем: витрина без товаров разочаровывает ровно
    один раз, и больше туда не заходят.
    """
    # --- продавцы: сколько у кого живых товаров, одним запросом
    counted = (
        await db.execute(
            select(Product.owner_user_id, func.count(Product.id))
            .where(Product.is_active.is_(True), Product.owner_user_id.is_not(None))
            .group_by(Product.owner_user_id)
        )
    ).all()
    by_user = {user_id: number for user_id, number in counted}

    sellers: list[SellerProfile] = []
    if by_user:
        sellers = list(
            (
                await db.execute(
                    select(SellerProfile).where(
                        SellerProfile.user_id.in_(by_user.keys()),
                        SellerProfile.status != SellerStatus.BANNED,
                    )
                )
            ).scalars().all()
        )

    # --- площадка: её товары опознаются пустым владельцем, подписки не в счёт
    platform_products = (
        await db.execute(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.owner_user_id.is_(None),
                Product.type != "subscription",
            )
        )
    ).scalar() or 0
    platform = (
        await db.execute(
            select(SellerProfile).where(SellerProfile.is_platform.is_(True))
        )
    ).scalars().first()

    # --- каналы: товар подписки связан с каналом через тариф
    channel_counts = (
        await db.execute(
            select(SubscriptionPlan.channel_id, func.count(Product.id))
            .join(Product, Product.id == SubscriptionPlan.product_id)
            .where(Product.is_active.is_(True))
            .group_by(SubscriptionPlan.channel_id)
        )
    ).all()
    by_channel = {channel_id: number for channel_id, number in channel_counts}

    channels: list[Channel] = []
    if by_channel:
        channels = list(
            (
                await db.execute(
                    select(Channel).where(
                        Channel.id.in_(by_channel.keys()),
                        Channel.status == ChannelStatus.ACTIVE,
                    )
                )
            ).scalars().all()
        )

    items: list[dict] = []

    if platform is not None and platform_products:
        items.append({
            "kind": "platform",
            "id": str(platform.id),
            "name": platform.display_name,
            "avatar_url": platform.avatar_url,
            "is_verified": bool(platform.is_verified),
            "rating": platform.rating,
            "products": platform_products,
        })

    for seller in sellers:
        items.append({
            "kind": "seller",
            "id": str(seller.id),
            "name": seller.display_name,
            "avatar_url": seller.avatar_url,
            "is_verified": bool(seller.is_verified),
            "rating": seller.rating,
            "products": by_user.get(seller.user_id, 0),
        })

    for channel in channels:
        items.append({
            "kind": "channel",
            "id": str(channel.id),
            "name": channel.title,
            "avatar_url": channel.avatar_url,
            "is_verified": bool(channel.is_verified),
            # Рейтинга у канала нет: отзывы собираются по сделкам, а подписка
            # идёт не через сделку
            "rating": None,
            "products": by_channel.get(channel.id, 0),
        })

    # Площадка первой — это лицо маркета. Дальше проверенные, дальше те, у
    # кого товаров больше: у пустоватого магазина меньше причин быть в начале.
    head = items[:1] if items and items[0]["kind"] == "platform" else []
    tail = items[len(head):]
    tail.sort(key=lambda item: (
        not item["is_verified"],
        -item["products"],
        item["name"].lower(),
    ))

    return (head + tail)[:limit]


@router.get("/seller/{seller_id}")
async def seller_store(
    seller_id: uuid.UUID,
    lang: str = Query("ru"),
    db: AsyncSession = Depends(get_db),
):
    seller = await db.get(SellerProfile, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Магазин не найден")

    # Заблокированного продавца не показываем: его товары и так сняты с
    # витрины, а страница создавала бы впечатление работающего магазина
    if seller.status == SellerStatus.BANNED and not seller.is_platform:
        raise HTTPException(status_code=404, detail="Магазин не найден")

    return {
        "kind": "platform" if seller.is_platform else "seller",
        "id": str(seller.id),
        "name": seller.display_name,
        "avatar_url": seller.avatar_url,
        "description": seller.description,
        "is_verified": seller.is_verified,
        "rating": seller.rating,
        "rating_count": seller.rating_count,
        "deals_completed": seller.deals_completed,
        "created_at": seller.created_at.isoformat(),
        "products": await _seller_products(db, seller, lang),
    }


@router.get("/channel/{channel_id}")
async def channel_store(
    channel_id: uuid.UUID,
    lang: str = Query("ru"),
    db: AsyncSession = Depends(get_db),
):
    """
    Витрина канала: то же, что магазин продавца, но товары — тарифы подписки.

    Рейтинга у канала нет: отзывы собираются по сделкам P2P, а подписка идёт
    не через сделку. Показывать пустой рейтинг хуже, чем не показывать.
    """
    channel = await db.get(Channel, channel_id)
    if channel is None or channel.status != ChannelStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Канал не найден")

    product_ids = [
        pid for (pid,) in (
            await db.execute(
                select(SubscriptionPlan.product_id)
                .where(
                    SubscriptionPlan.channel_id == channel.id,
                    SubscriptionPlan.product_id.is_not(None),
                )
            )
        ).all()
    ]

    products: list[dict] = []
    if product_ids:
        rows = (
            await db.execute(
                select(Product)
                .where(Product.id.in_(product_ids), Product.is_active.is_(True))
                .order_by(Product.price_usdt.asc())
            )
        ).scalars().all()
        products = await _product_cards(db, list(rows), lang)

    # Живых подписчиков видно покупателю: это единственный признак, по
    # которому он может оценить канал до покупки — рейтинга у канала нет
    subscribers = (
        await db.execute(
            select(func.count()).select_from(Subscription)
            .where(
                Subscription.channel_id == channel.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
    ).scalar() or 0

    return {
        "kind": "channel",
        "id": str(channel.id),
        "name": channel.title,
        "avatar_url": channel.avatar_url,
        "description": channel.description,
        "is_verified": channel.is_verified,
        "rating": None,
        "rating_count": 0,
        "deals_completed": 0,
        "link": channel.username,
        "subscribers": subscribers,
        "created_at": channel.created_at.isoformat(),
        "products": products,
    }
