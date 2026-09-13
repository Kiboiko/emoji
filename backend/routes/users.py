from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.user import User
from schemas.user import ReferralStats
from utils.auth import get_current_user, require_admin
from services.referral_service import get_referral_statistics

router = APIRouter(prefix="/api/users", tags=["Users"])


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
