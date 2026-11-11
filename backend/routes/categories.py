from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from models.product import Product
import uuid

from database import get_db
from models.category import Category
from schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse, CategoryLocalized
from utils.auth import require_admin

router = APIRouter(prefix="/api/categories", tags=["Categories"])

# Английское имя служебной категории, которую заводила публикация заявок без
# категории (см. services/moderation_service.py)
LEGACY_USER_ITEMS = "User items"


@router.get("", response_model=list[CategoryLocalized])
async def get_categories(
    lang: str = Query("ru"),
    db: AsyncSession = Depends(get_db)
):
    """
    Категории для каталога и формы объявления.

    Служебной «Товары пользователей» здесь нет: в неё раньше падали заявки без
    категории, и покупатель видел в списке раздел-свалку. Товары, уже лежащие
    в ней, остаются в общем каталоге, а администратор может перенести их по
    настоящим категориям (список для админки — /all, там она видна).
    """
    stmt = (
        select(Category)
        .where(Category.name_en != LEGACY_USER_ITEMS)
        .order_by(Category.sort_order.desc(), Category.created_at.desc())
    )
    result = await db.execute(stmt)
    categories = result.scalars().all()
    
    # Localize
    localized = []
    for category in categories:
        localized.append(CategoryLocalized(
            id=category.id,
            name=category.name_ru if lang == "ru" else category.name_en,
            parent_id=category.parent_id,
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
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get category by ID"""
    category = await db.get(Category, category_id)
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
    await _lock_tree(db)
    await _validate_parent(db, category_data.parent_id)
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
    category_id: uuid.UUID,
    category_data: CategoryUpdate,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update category (admin only)"""
    await _lock_tree(db)
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    update_data = category_data.model_dump(exclude_unset=True)
    if "parent_id" in update_data:
        await _validate_parent(db, update_data["parent_id"], category.id)
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
    category_id: uuid.UUID,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete category (admin only)"""
    await _lock_tree(db)
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    has_children = await db.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1))
    has_products = await db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1))
    if has_children or has_products:
        raise HTTPException(status_code=409, detail="Category contains products or subcategories")
    await db.delete(category)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category contains products or subcategories")
    
    await manager.broadcast({
        "type": "category_deleted",
        "data": {"id": str(category_id)}
    })
    
    return {"message": "Category deleted successfully"}


async def _lock_tree(db: AsyncSession):
    # Serialize administrative tree edits, including concurrent reparenting.
    await db.execute(text("SELECT pg_advisory_xact_lock(782347120)"))


async def _validate_parent(db: AsyncSession, parent_id, category_id=None):
    if parent_id is None:
        return
    if parent_id == category_id:
        raise HTTPException(status_code=422, detail="Category cannot be its own parent")
    parent = await db.get(Category, parent_id)
    if parent is None:
        raise HTTPException(status_code=422, detail="Parent category not found")
    if parent.parent_id is not None:
        raise HTTPException(status_code=422, detail="Only two category levels are allowed")
    if category_id is not None:
        child = await db.scalar(select(Category.id).where(Category.parent_id == category_id).limit(1))
        if child is not None:
            raise HTTPException(status_code=422, detail="Category with children must remain a root")
