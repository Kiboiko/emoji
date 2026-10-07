from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select
import uuid

from database import get_db
from models.order import Order
from models.p2p import Deal, DealStatus, ProductListing, ListingStatus, SellerProfile
from models.subscription import Channel, Subscription, SubscriptionStatus
from models.user import User
from schemas.user import LanguageIn, ReferralStats
from utils.auth import get_current_user, require_admin
from services.referral_service import get_referral_statistics

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("/me/summary")
async def my_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Счётчики разделов личного кабинета.

    Кабинет разошёлся на отдельные экраны, и на главной его странице
    нужны только числа рядом со строками. Одним запросом, а не пятью
    походами за полными списками, которые здесь всё равно не показываются.
    """
    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar() or 0

    seller = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()

    listings = 0
    if seller is not None:
        # Архивные заявки в счётчик не идут: он показывает, сколько у
        # человека товаров в работе, а не сколько их было за историю
        listings = await count(
            select(func.count()).select_from(ProductListing).where(
                ProductListing.seller_id == seller.id,
                ProductListing.status != ListingStatus.ARCHIVED,
            )
        )

    channels = await count(
        select(func.count()).select_from(Channel).where(Channel.owner_user_id == user.id)
    )
    orders = await count(
        select(func.count()).select_from(Order).where(Order.user_id == user.id)
    )
    subscriptions = await count(
        select(func.count()).select_from(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )

    # Сделки считаем и как покупателя, и как продавца: в кабинете они лежат
    # в одном списке. Обе стороны в Deal — это users, а не seller_profiles.
    deals = await count(
        select(func.count()).select_from(Deal).where(
            or_(Deal.buyer_id == user.id, Deal.seller_id == user.id),
            Deal.status.notin_([DealStatus.CANCELLED, DealStatus.REFUNDED]),
        )
    )

    return {
        "is_seller": seller is not None,
        "seller_id": str(seller.id) if seller else None,
        "listings": listings,
        "channels": channels,
        "orders": orders,
        "subscriptions": subscriptions,
        "deals": deals,
    }


@router.put("/me/language")
async def set_language(
    payload: LanguageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Язык, выбранный в приложении.

    Раньше выбор жил только в памяти приложения и сбрасывался на русский
    при каждом запуске, а бот о нём не знал вовсе. Теперь на нём бот пишет
    уведомления, и с ним приложение открывается в следующий раз.
    """
    user.app_language = payload.language
    await db.commit()
    return {"language": user.app_language}


@router.get("/referral-stats", response_model=ReferralStats)
async def get_user_referral_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get referral statistics for current user"""
    stats = await get_referral_statistics(db, user)
    return ReferralStats(**stats)


@router.get("/admin/all")
async def get_all_users(
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all users (admin only)"""
    stmt = select(User).where(User.is_admin == False).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    return [
        {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "is_admin": user.is_admin,
            "referral_code": user.referral_code,
            "referral_earnings": user.referral_earnings,
            "created_at": user.created_at.isoformat()
        }
        for user in users
    ]


@router.get("/admin/referrals")
async def get_all_referral_stats(
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed referral statistics for all users (admin only)"""
    stmt = select(User).where(User.referral_earnings > 0).order_by(User.referral_earnings.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    stats_list = []
    for user in users:
        stats = await get_referral_statistics(db, user)
        stats_list.append({
            "user_id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            **stats
        })
    
    return stats_list
