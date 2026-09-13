from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class ReviewCreate(BaseModel):
    """Schema for creating a review"""
    product_id: UUID
    order_id: UUID
    text: str = Field(..., min_length=1, max_length=150)
    rating: Optional[int] = Field(None, ge=1, le=5)


class FakeReviewCreate(BaseModel):
    """Schema for creating a fake review from admin"""
    product_id: UUID
    fake_username: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1, max_length=500)
    rating: Optional[int] = Field(None, ge=1, le=5)
    fake_quantity: Optional[int] = Field(None, ge=1)


class ReviewUser(BaseModel):
    """Simplified user schema for reviews"""
    model_config = ConfigDict(from_attributes=True)

    first_name: str


class ReviewProduct(BaseModel):
    """Simplified product schema for reviews"""
    model_config = ConfigDict(from_attributes=True)

    name_ru: str


class ReviewResponse(BaseModel):
    """Schema for review response"""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: Optional[UUID] = None
    user: Optional[ReviewUser] = None
    product_id: UUID
    product: Optional[ReviewProduct] = None
    order_id: Optional[UUID] = None
    text: str
    rating: Optional[int]
    telegram_message_id: Optional[int]
    is_hidden: bool
    is_fake: bool = False
    fake_username: Optional[str] = None
    fake_quantity: Optional[int] = None
    created_at: datetime
