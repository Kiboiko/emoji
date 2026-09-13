from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
import uuid
from uuid import UUID
from datetime import datetime
from typing import Optional

from database import get_db
from models.user import User
from models.withdrawal import Withdrawal, WithdrawalStatus
from schemas.withdrawal import WithdrawalCreate, WithdrawalUpdate, WithdrawalResponse
from utils.auth import get_current_user, require_admin
from services.telegram_service import telegram_service

router = APIRouter(prefix="/api/withdrawals", tags=["Withdrawals"])


@router.post("", response_model=WithdrawalResponse)
async def request_withdrawal(
    withdrawal_data: WithdrawalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Request a referral balance withdrawal"""
    # Validate amount
    if withdrawal_data.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
        
    if withdrawal_data.amount > user.referral_earnings:
        raise HTTPException(status_code=400, detail="Insufficient referral balance")
        
    # Create withdrawal request
    withdrawal = Withdrawal(
        id=uuid.uuid4(),
        user_id=user.id,
        amount=withdrawal_data.amount,
        wallet=withdrawal_data.wallet,
        status=WithdrawalStatus.PENDING
    )
    
    # Deduct from user balance immediately to "reserve" it
    user.referral_earnings -= withdrawal_data.amount
    
    db.add(withdrawal)
    db.add(user)
    await db.commit()
    await db.refresh(withdrawal)
    
    # Notify admin
    try:
        user_id_display = f"@{user.username}" if user.username else str(user.telegram_id)
        await telegram_service.send_withdrawal_request_notification(
            user_identifier=user_id_display,
            wallet=withdrawal.wallet,
            amount=withdrawal.amount,
            balance_after=float(user.referral_earnings)
        )
    except Exception as e:
        print(f"[WITHDRAWAL] Failed to send admin notification: {e}")
    
    return WithdrawalResponse.model_validate(withdrawal)


@router.get("/my", response_model=list[WithdrawalResponse])
async def get_my_withdrawals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's withdrawal history"""
    stmt = select(Withdrawal).where(Withdrawal.user_id == user.id).order_by(Withdrawal.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/admin/all", response_model=dict)
async def get_all_withdrawals(
    status: Optional[WithdrawalStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all withdrawals for admin with pagination and filtering"""
    stmt = select(Withdrawal).options(selectinload(Withdrawal.user)).order_by(Withdrawal.created_at.desc())
    
    if status:
        stmt = stmt.where(Withdrawal.status == status)
        
    # Count total for pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0
    
    # Get paginated results
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    withdrawals = result.scalars().all()
    
    # Format response
    items = []
    for w in withdrawals:
        data = WithdrawalResponse.model_validate(w)
        data.user_first_name = w.user.first_name
        data.user_telegram_id = w.user.telegram_id
        items.append(data)
        
    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.patch("/admin/{withdrawal_id}", response_model=WithdrawalResponse)
async def update_withdrawal_status(
    withdrawal_id: UUID,
    update_data: WithdrawalUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update withdrawal status (admin only)"""
    stmt = select(Withdrawal).options(selectinload(Withdrawal.user)).where(Withdrawal.id == withdrawal_id)
    result = await db.execute(stmt)
    withdrawal = result.scalar_one_or_none()
    
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")
        
    if withdrawal.status == update_data.status:
        return withdrawal
        
    withdrawal.status = update_data.status
    if update_data.status == WithdrawalStatus.COMPLETED:
        withdrawal.completed_at = datetime.utcnow()
        
        # Notify user via Telegram
        try:
            message = (
                f"<b>Ваш реф.баланс выведен.</b>\n"
                f"Кошелек - <code>{withdrawal.wallet}</code>\n"
                f"Сумма - {withdrawal.amount:.2f} USDT"
            )
            await telegram_service.send_message(withdrawal.user.telegram_id, message)
        except Exception as e:
            print(f"[WITHDRAWAL] Error sending notification: {e}")
            
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)
    
    # Attach user info for response
    data = WithdrawalResponse.model_validate(withdrawal)
    data.user_first_name = withdrawal.user.first_name
    data.user_telegram_id = withdrawal.user.telegram_id
    
    return data
