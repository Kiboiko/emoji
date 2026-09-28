from pydantic import BaseModel, Field, ConfigDict, field_validator
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Optional
from models.order import OrderStatus, CurrencyType


class OrderItemCreate(BaseModel):
    """Schema for creating an order item"""
    product_id: UUID
    quantity: int = Field(..., gt=0)


class OrderItemResponse(BaseModel):
    """Schema for order item response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    product_id: Optional[UUID]
    quantity: int
    price_usdt: Decimal
    price_ton: Optional[Decimal]
    product_snapshot: dict
    user_data: Optional[dict] = None
    is_reviewed: bool = False

    @field_validator("product_snapshot")
    @classmethod
    def _hide_content_data(cls, snapshot: dict) -> dict:
        """
        Снапшот уходит наружу без content_data.

        У инструкции там лежит сам проданный текст, а снапшот пишется при
        оформлении заказа — до оплаты. Любой мог оформить заказ, не платить
        и прочитать инструкцию в ответе GET /api/orders/{id}.

        Покупатель получает инструкцию сообщением в Telegram после оплаты
        (complete_order читает её из снапшота в базе, а не отсюда). Витрине
        и админке это поле не нужно. Словарь собирается заново: исходный —
        это данные строки заказа, и менять их нельзя.
        """
        return {key: value for key, value in snapshot.items() if key != "content_data"}


class OrderCreate(BaseModel):
    """Schema for creating an order from cart"""
    currency: CurrencyType
    # Галочка «согласен с условиями площадки». Нужна, только если пользователь
    # ещё не принимал текущую редакцию — повторно на каждом заказе не требуется.
    accept_terms: bool = False


class OrderUpdate(BaseModel):
    """Schema for updating order status (admin)"""
    status: OrderStatus


class OrderResponse(BaseModel):
    """Schema for order response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    user_id: UUID
    total_usdt: Decimal
    total_ton: Optional[Decimal]
    currency: CurrencyType
    status: OrderStatus
    cryptobot_invoice_id: Optional[str]
    created_at: datetime
    paid_at: Optional[datetime]
    items: list[OrderItemResponse]
