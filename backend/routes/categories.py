from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.category import Category
from schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse, CategoryLocalized
from utils.auth import require_admin

router = APIRouter(prefix="/api/categories", tags=["Categories"])


@router.get("", response_model=list[CategoryLocalized])
async def get_categories(
    lang: str = Query("ru"),
    db: AsyncSession = Depends(get_db)
):
    """Get all categories with localization"""
    stmt = select(Category).order_by(Category.sort_order.desc(), Category.created_at.desc())
    result = await db.execute(stmt)
    categories = result.scalars().all()
    
    # Localize
    localized = []
    for category in categories:
        localized.append(CategoryLocalized(
            id=category.id,
            name=category.name_ru if lang == "ru" else category.name_en,
            sort_order=category.sort_order
        ))
    
    return localized



@router.get("/all", response_model=list[CategoryResponse])
async def get_all_categories(
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all categories (full info for admin)"""
    stmt = select(Category).order_by(Category.sort_order.asc(), Category.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get category by ID"""
    category = await db.get(Category, uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    return CategoryResponse.model_validate(category)


from utils.websockets import manager

from fastapi.encoders import jsonable_encoder

@router.post("", response_model=CategoryResponse)
async def create_category(
    category_data: CategoryCreate,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create new category (admin only)"""
    category = Category(
        id=uuid.uuid4(),
        **category_data.model_dump()
    )
    
    db.add(category)
    await db.commit()
    await db.refresh(category)
    
    await manager.broadcast({
        "type": "category_created",
        "data": jsonable_encoder(CategoryResponse.model_validate(category))
    })
    
    return CategoryResponse.model_validate(category)


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    category_data: CategoryUpdate,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update category (admin only)"""
    category = await db.get(Category, uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    update_data = category_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)
    
    await db.commit()
    await db.refresh(category)
    
    await manager.broadcast({
        "type": "category_updated",
        "data": jsonable_encoder(CategoryResponse.model_validate(category))
    })
    
    return CategoryResponse.model_validate(category)


@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete category (admin only)"""
    category = await db.get(Category, uuid.UUID(category_id))
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    await db.delete(category)
    await db.commit()
    
    await manager.broadcast({
        "type": "category_deleted",
        "data": {"id": category_id}
    })
    
    return {"message": "Category deleted successfully"}
