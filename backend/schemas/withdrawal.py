from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Optional
from models.withdrawal import WithdrawalStatus


class WithdrawalCreate(BaseModel):
    """Schema for creating a withdrawal request"""
    # Decimal, а не float: сумма приходит от пользователя и идёт в денежную
    # логику, где float запрещён (см. services/money.py).
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    wallet: str = Field(..., min_length=1, max_length=255)


class WithdrawalUpdate(BaseModel):
    """Schema for updating withdrawal status (admin)"""
    status: WithdrawalStatus


class WithdrawalResponse(BaseModel):
    """Schema for withdrawal response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    user_id: UUID
    amount: float
    wallet: str
    status: WithdrawalStatus
    created_at: datetime
    completed_at: Optional[datetime]
    
    # Optional user info for admin view
    user_first_name: Optional[str] = None
    user_telegram_id: Optional[int] = None
