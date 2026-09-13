from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class CategoryBase(BaseModel):
    """Base category schema"""
    name_ru: str = Field(..., min_length=1, max_length=255)
    name_en: str = Field(..., min_length=1, max_length=255)
    sort_order: int = 0


class CategoryCreate(CategoryBase):
    """Schema for creating a category"""
    pass


class CategoryUpdate(BaseModel):
    """Schema for updating a category"""
    name_ru: Optional[str] = Field(None, min_length=1, max_length=255)
    name_en: Optional[str] = Field(None, min_length=1, max_length=255)
    sort_order: Optional[int] = None


class CategoryResponse(CategoryBase):
    """Schema for category response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    created_at: datetime


class CategoryLocalized(BaseModel):
    """Schema for localized category"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str  # name_ru or name_en based on language
    sort_order: int
