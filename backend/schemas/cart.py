from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class CartItemCreate(BaseModel):
    """Schema for adding item to cart"""
    product_id: UUID
    quantity: int = Field(default=1, gt=0)
    user_data: Optional[dict] = None


class CartItemUpdate(BaseModel):
    """Schema for updating cart item quantity"""
    quantity: int = Field(..., gt=0)


class CartItemResponse(BaseModel):
    """Schema for cart item response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    product_id: UUID
    quantity: int
    user_data: Optional[dict] = None
    created_at: datetime


class CartResponse(BaseModel):
    """Schema for full cart response with product details"""
    items: list[dict]  # Will include product details
    total_usdt: float
    total_ton: Optional[float]
