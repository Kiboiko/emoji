from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    """Base user schema"""
    username: Optional[str] = None
    first_name: str
    language_code: str = "ru"


class UserCreate(UserBase):
    """Schema for creating a user"""
    telegram_id: int
    referral_code: str
    referrer_id: Optional[UUID] = None


class UserUpdate(BaseModel):
    """Schema for updating a user"""
    username: Optional[str] = None
    first_name: Optional[str] = None
    language_code: Optional[str] = None


class UserResponse(UserBase):
    """Schema for user response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    telegram_id: int
    is_admin: bool
    referral_code: str
    referral_earnings: float
    created_at: datetime
    # Язык, выбранный в приложении; None — ещё не выбирал
    app_language: Optional[str] = None


class LanguageIn(BaseModel):
    language: str = Field(..., pattern="^(ru|en)$")


class ReferralStats(BaseModel):
    """Schema for referral statistics"""
    referral_code: str
    referral_count: int
    total_earnings: float
    level2_earnings: float = 0.0
    # Процент первого уровня: реферер должен понимать, от чего считается
    # его вознаграждение, иначе сумму начисления нечем проверить
    referral_percent: float = 0.0
    # Сколько оплаченных заказов сделали приглашённые
    paid_orders_count: int = 0
    referrals: list[dict]  # List of referrals with their purchases
