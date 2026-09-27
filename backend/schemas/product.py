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
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """Schema for product response (localized)"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    image_url: str
    created_at: datetime
    is_active: bool = True


class ProductLocalized(BaseModel):
    """Schema for localized product (single language)"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str  # name_ru or name_en based on language
    description: str  # description_ru or description_en
    price_usdt: Decimal
    price_ton: Optional[Decimal]
    image_url: str
    # Остальные фотографии. Карточке каталога хватает image_url, а странице
    # товара — нет: продавец грузит до восьми фотографий, и до этого
    # покупатель видел только первую.
    images: list[str] = Field(default_factory=list)
    # Сколько штук осталось. None — товар не кончается (услуга, подписка).
    # Нужен странице товара: без него она предлагала выбрать количество
    # больше, чем есть, и упиралась в отказ корзины.
    stock: Optional[int] = None
    category_id: UUID
    is_top: bool
    type: str = "digital"
    min_quantity: int = 1
    max_quantity: Optional[int] = None
    created_at: datetime

    # Товар существует, но снят с продажи. Каталог такие не отдаёт вовсе;
    # поле нужно странице товара, куда можно прийти по старой ссылке.
    is_active: bool = True

    # Товар пользователя: витрина рисует пометку, а покупка уходит в escrow
    is_p2p: bool = False

    # --- Оценка товара ---------------------------------------------
    # Считалась только на странице товара, и в сетке каталога её не было.
    # None — отзывов нет: карточка не рисует ни звёзд, ни нуля.
    rating: Optional[float] = None
    reviews_count: int = 0

    # --- Автор товара ---------------------------------------------------
    # Одна пара полей на два разных источника: продавца и канал. Раньше тут
    # были только seller_*, и подписка приходила в витрину вообще без автора —
    # покупатель не видел, чей это канал.
    #
    # author_kind: "seller" — товар пользователя, "channel" — доступ в канал,
    # "platform" — магазин самой площадки. Пустой теперь только там,
    # где магазин площадки ещё не заведён.
    author_kind: Optional[str] = None
    # id магазина: по нему строится ссылка на витрину продавца. У
    # продавца и площадки это SellerProfile.id, у подписки — Channel.id.
    author_id: Optional[UUID] = None
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    author_verified: bool = False
    author_rating: Optional[float] = None
    # Сколько отзывов стоит за этой оценкой. Заполняется только на
    # странице товара: в сетке каталога подпись продавца не рисуется.
    author_reviews: int = 0
    author_deals: int = 0
    # @username канала: по нему покупатель может посмотреть витрину автора до
    # покупки. У продавца такого адреса нет — там None.
    author_link: Optional[str] = None
