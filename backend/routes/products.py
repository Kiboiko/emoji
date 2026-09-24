from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, desc
from typing import Optional, List
import uuid
import shutil
import aiofiles
from pathlib import Path
from fastapi.encoders import jsonable_encoder

from database import get_db
from models.product import Product
from models.category import Category
from models.digital_item import DigitalItem
from schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductLocalized
from utils.auth import require_admin
from config import settings
from utils.websockets import manager

router = APIRouter(prefix="/api/products", tags=["Products"])

# Helper to save image
async def save_image(image: UploadFile) -> str:
    file_extension = Path(image.filename).suffix
    file_name = f"{uuid.uuid4()}{file_extension}"
    file_path = Path(settings.UPLOAD_DIR) / "products" / file_name
    
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await image.read()
        await out_file.write(content)
        
    return f"/uploads/products/{file_name}"

@router.get("", response_model=List[ProductLocalized])
async def get_products(
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    lang: str = Query("ru"),
    skip: int = 0,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db)
):
    """Get products with pagination, search and filtering"""
    # Снятые с продажи в каталог не попадают. До этого такого состояния не
    # было вовсе, и подписки висели в витрине с момента создания тарифа —
    # то есть до модерации канала.
    stmt = select(Product).where(Product.is_active.is_(True))
    
    if category_id:
        stmt = stmt.where(Product.category_id == uuid.UUID(category_id))
        
    # For digital products, we need to check actual available digital_items
    # For other products, check stock field
    from datetime import datetime
    
    # Subquery to count available digital items
    available_digital_items_subquery = (
        select(func.count(DigitalItem.id))
        .where(DigitalItem.product_id == Product.id)
        .where(DigitalItem.is_sold == False)
        .where(
            or_(
                DigitalItem.order_id.is_(None),
                DigitalItem.reserved_until < datetime.utcnow()
            )
        )
        .scalar_subquery()
    )
    
    # Filter: show if (type != 'digital' AND (stock IS NULL OR stock > 0)) OR (type == 'digital' AND available_count > 0)
    from sqlalchemy import and_
    
    stmt = stmt.where(
        or_(
            # Non-digital products (service, instruction): check stock (NULL means unlimited)
            and_(
                Product.type != 'digital',
                or_(Product.stock.is_(None), Product.stock > 0)
            ),
            # Digital products: check available digital_items
            and_(
                Product.type == 'digital',
                available_digital_items_subquery > 0
            )
        )
    )
        
    if search:
        search_filter = or_(
            Product.name_ru.ilike(f"%{search}%"),
            Product.name_en.ilike(f"%{search}%")
        )
        stmt = stmt.where(search_filter)
        
    # Sort by TOP first, then Sort Order, then Date
    stmt = stmt.order_by(Product.is_top.desc(), Product.sort_order.desc(), Product.created_at.desc())
    stmt = stmt.offset(skip).limit(limit)
    
    # Здесь на КАЖДЫЙ запрос каталога печатался скомпилированный SQL и строка
    # по каждому товару. Фронт грузит каталог с limit=1000 при каждом открытии
    # главной, так что лог забивался мгновенно. Убрано.
    result = await db.execute(stmt)
    products = result.scalars().all()

    # Авторы нужны, чтобы показать на странице товара, чей он, и дать
    # ссылку на магазин. Тремя запросами на весь каталог, а не по товару.
    sellers = await _sellers_by_user(db, products)
    channels = await _channels_by_product(db, products)
    platform = await _platform_store(db)
    ratings = await _ratings_by_product(db, products)

    localized = []
    for p in products:
        item = ProductLocalized(
            id=p.id,
            name=p.name_ru if lang == "ru" else p.name_en,
            description=p.description_ru if lang == "ru" else p.description_en,
            price_usdt=p.price_usdt,
            price_ton=p.price_ton,
            image_url=p.image_url,
            category_id=p.category_id,
            is_top=p.is_top,
            type=p.type,
            min_quantity=p.min_quantity,
            max_quantity=p.max_quantity,
            created_at=p.created_at,
            is_active=p.is_active,
            is_p2p=p.is_p2p,
            # content_data is NOT included in ProductLocalized purposefully to hide instructions
            **_author_fields(p, sellers, channels, platform),
            **ratings.get(p.id, {}),
        )
        localized.append(item)
        
    return localized


# ---------------------------------------------------------------------------
# Автор товара
# ---------------------------------------------------------------------------

async def _sellers_by_user(db: AsyncSession, products: list) -> dict:
    """Профили продавцов для товаров пользователей — одним запросом."""
    seller_ids = {p.owner_user_id for p in products if p.owner_user_id}
    if not seller_ids:
        return {}

    from models.p2p import SellerProfile
    rows = (
        await db.execute(
            select(SellerProfile).where(SellerProfile.user_id.in_(seller_ids))
        )
    ).scalars().all()
    return {s.user_id: s for s in rows}


async def _channels_by_product(db: AsyncSession, products: list) -> dict:
    """
    Каналы для товаров-подписок — одним запросом.

    Прямой связи «товар → канал» нет: товар заводится под тариф, и связь
    живёт в subscription_plans.product_id. Идём оттуда.
    """
    product_ids = [p.id for p in products if p.type == "subscription"]
    if not product_ids:
        return {}

    from models.subscription import Channel, SubscriptionPlan
    rows = (
        await db.execute(
            select(SubscriptionPlan.product_id, Channel)
            .join(Channel, Channel.id == SubscriptionPlan.channel_id)
            .where(SubscriptionPlan.product_id.in_(product_ids))
        )
    ).all()
    return {product_id: channel for product_id, channel in rows}


async def _platform_store(db: AsyncSession):
    """
    Магазин самой площадки.

    Заводится миграцией, здесь только читается: создавать строку на
    GET-запросе каталога нельзя. Если его нет — товары площадки просто
    придут без магазина, как раньше.
    """
    from models.p2p import SellerProfile
    return (
        await db.execute(
            select(SellerProfile).where(SellerProfile.is_platform.is_(True))
        )
    ).scalars().first()


async def _ratings_by_product(db: AsyncSession, products: list) -> dict:
    """
    Средняя оценка и число отзывов — одним запросом на весь каталог.

    До этого оценка считалась только на странице товара, и в сетке её не было
    вовсе. Считаем только по отзывам с оценкой и не скрытым модератором:
    отзыв без оценки не должен тянуть среднее вниз, а скрытый — влиять вообще.
    """
    from models.review import Review

    product_ids = [p.id for p in products]
    if not product_ids:
        return {}

    rows = (
        await db.execute(
            select(
                Review.product_id,
                func.avg(Review.rating),
                func.count(Review.id),
            )
            .where(
                Review.product_id.in_(product_ids),
                Review.rating.is_not(None),
                Review.is_hidden.is_(False),
            )
            .group_by(Review.product_id)
        )
    ).all()

    return {
        product_id: {
            "rating": round(float(average), 1),
            "reviews_count": count,
        }
        for product_id, average, count in rows
    }


def _author_fields(product, sellers: dict, channels: dict, platform=None) -> dict:
    """
    Кто стоит за товаром — в виде, одинаковом для витрины.

    Три источника и один набор полей: продавец, автор канала и сама площадка.
    У последней теперь тоже есть магазин: товар без владельца продаёт не
    «никто», а площадка, и покупатель должен мочь перейти на её витрину.
    """
    channel = channels.get(product.id)
    if channel is not None:
        return {
            "author_kind": "channel",
            "author_id": channel.id,
            "author_name": channel.title,
            "author_avatar": channel.avatar_url,
            "author_verified": channel.is_verified,
            "author_link": channel.username,
        }

    seller = sellers.get(product.owner_user_id)
    if seller is not None:
        return {
            "author_kind": "seller",
            "author_id": seller.id,
            "author_name": seller.display_name,
            "author_avatar": seller.avatar_url,
            "author_verified": seller.is_verified,
            "author_rating": seller.rating,
            "author_deals": seller.deals_completed,
        }

    if platform is not None:
        return {
            "author_kind": "platform",
            "author_id": platform.id,
            "author_name": platform.display_name,
            "author_avatar": platform.avatar_url,
            "author_verified": platform.is_verified,
        }

    # Магазин площадки ещё не заведён — выдумывать автора не надо
    return {}

# Admin Endpoint for raw products table
@router.get("/admin", response_model=dict)
async def get_admin_products(
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * limit
    
    stmt = select(Product)
    count_stmt = select(func.count(Product.id))
    
    # Optional: Join category if sorting by category
    if sort_by == 'category':
        stmt = stmt.join(Category, Product.category_id == Category.id, isouter=True)
    
    if search:
        search_filter = or_(
            Product.name_ru.ilike(f"%{search}%"),
            Product.name_en.ilike(f"%{search}%")
        )
        stmt = stmt.where(search_filter)
        count_stmt = count_stmt.where(search_filter)
    
    # Sorting
    sort_column = None
    if sort_by == 'name':
        sort_column = Product.name_ru
    elif sort_by == 'price':
        sort_column = Product.price_usdt
    elif sort_by == 'category':
        sort_column = Category.name_ru
    elif sort_by == 'type':
        sort_column = Product.type
    elif sort_by == 'stock':
        sort_column = Product.stock
    elif sort_by == 'is_top':
        sort_column = Product.is_top
    else:
        sort_column = Product.created_at # default
        
    if sort_order == 'asc':
        stmt = stmt.order_by(sort_column.asc())
    else:
        stmt = stmt.order_by(sort_column.desc())
        
    # Always secondary sort by creation for stability
    if sort_by != 'created_at':
        stmt = stmt.order_by(Product.created_at.desc())
        
    stmt = stmt.offset(offset).limit(limit)
    
    total = (await db.execute(count_stmt)).scalar() or 0
    result = await db.execute(stmt)
    products = result.scalars().all()
    
    return {
        "items": [ProductResponse.model_validate(p) for p in products],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/{product_id}", response_model=ProductLocalized)
async def get_product(
    product_id: str,
    lang: str = Query("ru"),
    db: AsyncSession = Depends(get_db)
):
    """Get product by ID with localization"""
    product = await db.get(Product, uuid.UUID(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Снятый с продажи товар отдаём, а не прячем: на него ведут ссылки из
    # истории заказов и из чата сделки. Купить его не дадут в корзине, а
    # витрина по is_active нарисует «снято с продажи».
    sellers = await _sellers_by_user(db, [product])
    channels = await _channels_by_product(db, [product])
    platform = await _platform_store(db)
    ratings = await _ratings_by_product(db, [product])

    return ProductLocalized(
        id=product.id,
        name=product.name_ru if lang == "ru" else product.name_en,
        description=product.description_ru if lang == "ru" else product.description_en,
        price_usdt=product.price_usdt,
        price_ton=product.price_ton,
        image_url=product.image_url,
        category_id=product.category_id,
        is_top=product.is_top,
        type=product.type,
        min_quantity=product.min_quantity,
        max_quantity=product.max_quantity,
        created_at=product.created_at,
        is_active=product.is_active,
        is_p2p=product.is_p2p,
        **_author_fields(product, sellers, channels, platform),
        **ratings.get(product.id, {}),
    )

@router.post("")
async def create_product(
    name_ru: str = Form(...),
    name_en: str = Form(...),
    description_ru: str = Form(...),
    description_en: str = Form(...),
    price_usdt: float = Form(...),
    category_id: str = Form(...),
    type: str = Form("digital"),
    is_top: bool = Form(False),
    min_quantity: int = Form(1),
    image: Optional[UploadFile] = File(None),
    digital_file: Optional[UploadFile] = File(None),
    instruction_text: Optional[str] = Form(None),
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    # Save Image
    if image:
        image_url = await save_image(image)
    else:
        # Default placeholder if no image provided
        image_url = "/uploads/products/placeholder.png"
    
    # Handle content data
    content_data = {}
    if type == "instruction" and instruction_text:
        content_data = {"instruction": instruction_text}
    
    # Set initial stock: None (unlimited) for service/instruction, 0 for digital (will be updated when items added)
    initial_stock = None if type in ['service', 'instruction'] else 0
    
    new_product = Product(
        id=uuid.uuid4(),
        name_ru=name_ru,
        name_en=name_en,
        description_ru=description_ru,
        description_en=description_en,
        price_usdt=price_usdt,
        category_id=uuid.UUID(category_id),
        type=type,
        is_top=is_top,
        min_quantity=min_quantity,
        image_url=image_url,
        stock=initial_stock,
        content_data=content_data
    )
    
    db.add(new_product)
    
    # Handle Digital File
    if type == "digital" and digital_file:
        content = await digital_file.read()
        text_content = content.decode("utf-8")
        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        
        for line in lines:
            digital_item = DigitalItem(
                id=uuid.uuid4(),
                product_id=new_product.id,
                content=line,
                is_sold=False
            )
            db.add(digital_item)
            
        new_product.stock = len(lines)
        
    await db.commit()
    await db.refresh(new_product)
    
    # Broadcast
    await manager.broadcast({
        "type": "product_created",
        "data": jsonable_encoder(ProductResponse.model_validate(new_product))
    })
    
    return ProductResponse.model_validate(new_product)


@router.put("/{product_id}")
async def update_product(
    product_id: str,
    name_ru: Optional[str] = Form(None),
    name_en: Optional[str] = Form(None),
    description_ru: Optional[str] = Form(None),
    description_en: Optional[str] = Form(None),
    price_usdt: Optional[float] = Form(None),
    category_id: Optional[str] = Form(None),
    is_top: Optional[bool] = Form(None),
    is_active: Optional[bool] = Form(None),
    type: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    digital_file: Optional[UploadFile] = File(None),
    instruction_text: Optional[str] = Form(None),
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    product = await db.get(Product, uuid.UUID(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    if name_ru: product.name_ru = name_ru
    if name_en: product.name_en = name_en
    if description_ru: product.description_ru = description_ru
    if description_en: product.description_en = description_en
    if price_usdt is not None: product.price_usdt = price_usdt
    if category_id: product.category_id = uuid.UUID(category_id)
    if is_top is not None: product.is_top = is_top
    if is_active is not None: product.is_active = is_active
    if type: product.type = type
    
    # Handle content data for instructions
    if (type == "instruction" or product.type == "instruction") and instruction_text:
        # If content_data is None/empty, init dict
        if not product.content_data:
            product.content_data = {}
        # We need to assign a new dict to trigger SQLAlchemy detection or use flag_modified
        new_data = dict(product.content_data)
        new_data["instruction"] = instruction_text
        product.content_data = new_data
    
    if image:
        product.image_url = await save_image(image)
        
    # Handle Digital File (Add to existing stock)
    if type == "digital" and digital_file:
        content = await digital_file.read()
        text_content = content.decode("utf-8")
        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        
        for line in lines:
            digital_item = DigitalItem(
                id=uuid.uuid4(),
                product_id=product.id,
                content=line,
                is_sold=False
            )
            db.add(digital_item)
            
        # Update stock count logic will be handled below by reclac
    
    await db.commit()
    
    # Recalculate stock accurately if digital
    if product.type == "digital":
        count_stmt = select(func.count(DigitalItem.id)).where(
            DigitalItem.product_id == product.id,
            DigitalItem.is_sold == False
        )
        product.stock = (await db.execute(count_stmt)).scalar() or 0
        await db.commit()
        
    await db.refresh(product)

    await manager.broadcast({
        "type": "product_updated",
        "data": jsonable_encoder(ProductResponse.model_validate(product))
    })
    
    return ProductResponse.model_validate(product)

@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    product = await db.get(Product, uuid.UUID(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    await db.delete(product)
    await db.commit()
    
    await manager.broadcast({
        "type": "product_deleted",
        "data": {"id": product_id}
    })
    
    return {"message": "Product deleted"}
