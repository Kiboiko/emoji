import uuid
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.user import User
from models.referral import ReferralTransaction
from models.order import Order
from config import settings


async def process_referral_commission(
    db: AsyncSession,
    order: Order,
    referral_user: User
) -> None:
    """
    Process referral commission when a referred user makes a purchase
    """
    # Check if user has a referrer
    if not referral_user.referrer_id:
        return
    
    # Get referrer
    referrer = await db.get(User, referral_user.referrer_id)
    if not referrer:
        return
    
    # Calculate commission (3% of order total in USDT)
    commission = Decimal(str(order.total_usdt)) * (Decimal(str(settings.REFERRAL_PERCENTAGE)) / Decimal('100'))
    
    # Create referral transaction
    transaction = ReferralTransaction(
        id=uuid.uuid4(),
        referrer_id=referrer.id,
        referral_id=referral_user.id,
        order_id=order.id,
        amount=commission
    )
    db.add(transaction)
    
    # Update referrer's earnings
    referrer.referral_earnings += float(commission)
    
    await db.commit()


async def get_referral_statistics(db: AsyncSession, user: User) -> dict:
    """
    Get detailed referral statistics for a user
    """
    # Get all referrals (users referred by this user)
    stmt = select(User).where(User.referrer_id == user.id)
    result = await db.execute(stmt)
    referrals = result.scalars().all()
    
    # Get all referral transactions
    stmt = select(ReferralTransaction).where(ReferralTransaction.referrer_id == user.id)
    result = await db.execute(stmt)
    transactions = result.scalars().all()
    
    # Build detailed statistics
    referral_details = []
    for referral in referrals:
        # Get orders from this referral
        stmt = (
            select(Order)
            .where(Order.user_id == referral.id)
            .where(Order.status == "paid")
        )
        result = await db.execute(stmt)
        orders = result.scalars().all()
        
        # Get transactions for this referral
        referral_transactions = [t for t in transactions if t.referral_id == referral.id]
        
        referral_details.append({
            "user_id": str(referral.id),
            "telegram_id": referral.telegram_id,
            "username": referral.username,
            "orders_count": len(orders),
            "total_spent": sum(float(order.total_usdt) for order in orders),
            "commission_earned": sum(float(t.amount) for t in referral_transactions)
        })
    
    return {
        "referral_code": user.referral_code,
        "referral_count": len(referrals),
        "total_earnings": user.referral_earnings,
        "referrals": referral_details
    }
