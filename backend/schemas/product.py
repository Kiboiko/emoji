from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class ProductType(str, Enum):
    DIGITAL = "digital"
    SERVICE = "service"
    INSTRUCTION = "instruction"


class ProductBase(BaseModel):
    """Base product schema"""
    name_ru: str = Field(..., min_length=1, max_length=500)
    name_en: str = Field(..., min_length=1, max_length=500)
    description_ru: str
    description_en: str
    price_usdt: Decimal = Field(..., gt=0)
    price_ton: Optional[Decimal] = Field(None, gt=0)
    category_id: UUID
    is_top: bool = False
    sort_order: int = 0
    stock: Optional[int] = Field(None, ge=0)
    content_data: dict = Field(default_factory=dict)
    
    # New fields
    type: str = "digital"
    min_quantity: int = 1
    max_quantity: Optional[int] = None


class ProductCreate(ProductBase):
    """Schema for creating a product"""
    image_url: str  # Will be set after image upload


class ProductUpdate(BaseModel):
    """Schema for updating a product"""
    name_ru: Optional[str] = Field(None, min_length=1, max_length=500)
    name_en: Optional[str] = Field(None, min_length=1, max_length=500)
    description_ru: Optional[str] = None
    description_en: Optional[str] = None
    price_usdt: Optional[Decimal] = Field(None, gt=0)
    price_ton: Optional[Decimal] = Field(None, gt=0)
    category_id: Optional[UUID] = None
    is_top: Optional[bool] = None
    sort_order: Optional[int] = None
    stock: Optional[int] = Field(None, ge=0)
    content_data: Optional[dict] = None
    image_url: Optional[str] = None
    type: Optional[str] = None
    min_quantity: Optional[int] = None
    max_quantity: Optional[int] = None


class ProductResponse(ProductBase):
    """Schema for product response (localized)"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    image_url: str
    created_at: datetime


class ProductLocalized(BaseModel):
    """Schema for localized product (single language)"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str  # name_ru or name_en based on language
    description: str  # description_ru or description_en
    price_usdt: Decimal
    price_ton: Optional[Decimal]
    image_url: str
    category_id: UUID
    is_top: bool
    type: str = "digital"
    min_quantity: int = 1
    max_quantity: Optional[int] = None
    created_at: datetime

    # Товар пользователя: витрина рисует пометку, а покупка уходит в escrow
    is_p2p: bool = False
    seller_name: Optional[str] = None
    seller_rating: Optional[float] = None
    seller_deals: int = 0
