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


def _product_card(product: Product, lang: str) -> dict:
    """
    Карточка товара для витрины магазина.

    Автора сюда не кладём: на странице магазина он один и назван сверху,
    повторять его у каждого товара незачем.
    """
    return {
        "id": str(product.id),
        "name": product.name_ru if lang == "ru" else product.name_en,
        "price_usdt": str(product.price_usdt),
        "image_url": product.image_url,
        "type": product.type,
        "is_top": product.is_top,
    }


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
    return [_product_card(p, lang) for p in rows]


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
        products = [_product_card(p, lang) for p in rows]

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
        "products": products,
    }
