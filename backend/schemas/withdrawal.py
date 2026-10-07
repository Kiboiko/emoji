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
    #
    # decimal_places=9, а не 2: у TON девять знаков, и с двумя вывести можно
    # было бы только круглые суммы, а остаток навсегда застрял бы на счёте.
    amount: Decimal = Field(..., gt=0, max_digits=20, decimal_places=9)
    wallet: str = Field(..., min_length=1, max_length=255)
    # USD (реферальный баланс) или TON (заработок продавца). По умолчанию USD —
    # так работает существующий вызов с витрины.
    currency: Optional[str] = Field(None, max_length=10)


class WithdrawalUpdate(BaseModel):
    """Schema for updating withdrawal status (admin)"""
    status: WithdrawalStatus


class WithdrawalResponse(BaseModel):
    """Schema for withdrawal response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    user_id: UUID
    amount: float
    currency: str = "USD"
    wallet: str
    status: WithdrawalStatus
    created_at: datetime
    completed_at: Optional[datetime]
    sent_at: Optional[datetime] = None
    tx_hash: Optional[str] = None
    reject_reason: Optional[str] = None

    # Optional user info for admin view
    user_first_name: Optional[str] = None
    user_telegram_id: Optional[int] = None
