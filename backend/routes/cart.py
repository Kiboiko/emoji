from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.user import User
from models.cart import CartItem
from models.product import Product
from schemas.cart import CartItemCreate, CartItemUpdate, CartResponse
from utils.auth import get_current_user

router = APIRouter(prefix="/api/cart", tags=["Cart"])


def _quantity_ceiling(product: Product) -> int | None:
    """
    Сколько штук этого товара можно держать в корзине. None — без ограничений.

    Ограничений два и они разные: max_quantity — сколько разрешено взять в одни
    руки, stock — сколько вообще есть. Витрине важен меньший из двух: именно о
    него упрётся покупатель.
    """
    limits = [value for value in (product.max_quantity, product.stock) if value is not None]
    return min(limits) if limits else None


def _limit_message(product: Product, in_cart: int, ceiling: int) -> str:
    """
    Почему больше взять нельзя — по-русски и по делу.

    Раньше отсюда уходило «Maximum quantity is 1»: английская строка
    всплывала поверх русского интерфейса и не говорила главного — что
    товар уже лежит в корзине покупателя и ничего не сломалось.
    """
    if in_cart >= ceiling:
        if ceiling == 1:
            return "Этот товар уже в корзине: он продаётся в одном экземпляре"
        return f"В корзине уже {in_cart} шт. — больше по этому товару взять нельзя"

    # Про остаток говорим прямо: покупателю полезнее знать, что товара
    # просто нет, чем что ему «не положено»
    if product.stock is not None and product.stock <= ceiling:
        return f"Осталось всего {product.stock} шт."
    return f"Больше {ceiling} шт. в одни руки взять нельзя"


@router.get("", response_model=CartResponse)
async def get_cart(
    lang: str = "ru",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's cart with product details"""
    stmt = select(CartItem).where(CartItem.user_id == user.id)
    result = await db.execute(stmt)
    cart_items = result.scalars().all()
    
    items_with_products = []
    total_usdt = 0.0
    total_ton = 0.0
    
    for cart_item in cart_items:
        product = await db.get(Product, cart_item.product_id)
        if product:
            item_total_usdt = float(product.price_usdt) * cart_item.quantity
            item_total_ton = float(product.price_ton or 0) * cart_item.quantity if product.price_ton else None
            
            total_usdt += item_total_usdt
            if item_total_ton:
                total_ton += item_total_ton
            
            items_with_products.append({
                "id": str(cart_item.id),
                "product_id": str(product.id),
                "name": product.name_ru if lang == "ru" else product.name_en,
                "image_url": product.image_url,
                "price_usdt": float(product.price_usdt),
                "price_ton": float(product.price_ton) if product.price_ton else None,
                "quantity": cart_item.quantity,
                "user_data": cart_item.user_data,
                "type": product.type,
                # Потолок количества нужен витрине, чтобы погасить «плюс»
                # заранее. Без него корзина рисовала новое число и сумму до
                # ответа сервера, а сервер отказывал — цифра успевала мигнуть.
                "max_quantity": _quantity_ceiling(product),
                "subtotal_usdt": item_total_usdt,
                "subtotal_ton": item_total_ton
            })
    
    return CartResponse(
        items=items_with_products,
        total_usdt=total_usdt,
        total_ton=total_ton if total_ton > 0 else None
    )


@router.post("", response_model=dict)
async def add_to_cart(
    item_data: CartItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add product to cart or update quantity if exists"""
    # Verify product exists
    product = await db.get(Product, item_data.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Снятый с продажи в корзину не кладём. Каталог такие не показывает, но
    # ссылка на товар могла остаться открытой, а карточка — висеть в чужой
    # вкладке с прошлого захода.
    if not product.is_active:
        raise HTTPException(status_code=400, detail="Товар снят с продажи")

    if product.min_quantity and item_data.quantity < product.min_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Меньше {product.min_quantity} шт. заказать нельзя",
        )

    # Потолок считаем сразу по обоим ограничениям. Раньше здесь смотрели
    # только на max_quantity, а сток — лишь при добавлении к уже лежащей
    # позиции: первым же нажатием в корзину можно было положить больше,
    # чем есть на складе, и упереться в отказ только при оплате.
    ceiling = _quantity_ceiling(product)
    if ceiling is not None and item_data.quantity > ceiling:
        raise HTTPException(
            status_code=400,
            detail=_limit_message(product, 0, ceiling),
        )

    # Check if item already in cart
    # For digital products (no user_data required), check only product_id
    # For service products, also check user_data to allow multiple orders with different links
    stmt = select(CartItem).where(
        CartItem.user_id == user.id,
        CartItem.product_id == item_data.product_id
    )
    
    # For service products, also match user_data
    if product.type == "service" and item_data.user_data:
        stmt = stmt.where(CartItem.user_data == item_data.user_data)
    
    result = await db.execute(stmt)
    existing_item = result.scalar_one_or_none()
    
    if existing_item:
        # Проверять нужно ИТОГ, а не приходящую добавку: проверка выше видит
        # только item_data.quantity. Без этого «добавить в корзину» дважды по
        # одной штуке обходит лимит — в корзине оказывается две единицы товара
        # с max_quantity=1. Для товара пользователя это вещь в единственном
        # экземпляре, и заказ уходил бы на количество, которого не существует.
        new_quantity = existing_item.quantity + item_data.quantity

        ceiling = _quantity_ceiling(product)
        if ceiling is not None and new_quantity > ceiling:
            raise HTTPException(
                status_code=400,
                detail=_limit_message(product, existing_item.quantity, ceiling),
            )

        existing_item.quantity = new_quantity
        await db.commit()
        return {"message": "Cart updated", "item_id": str(existing_item.id)}
    else:
        # Create new cart item
        cart_item = CartItem(
            id=uuid.uuid4(),
            user_id=user.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
            user_data=item_data.user_data
        )
        db.add(cart_item)
        await db.commit()
        await db.refresh(cart_item)
        return {"message": "Added to cart", "item_id": str(cart_item.id)}


@router.put("/{item_id}", response_model=dict)
async def update_cart_item(
    item_id: str,
    item_data: CartItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update cart item quantity"""
    cart_item = await db.get(CartItem, uuid.UUID(item_id))
    
    if not cart_item or cart_item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Cart item not found")
        
    # Validate quantity limits
    product = await db.get(Product, cart_item.product_id)
    if product:
        if product.min_quantity and item_data.quantity < product.min_quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Меньше {product.min_quantity} шт. заказать нельзя",
            )
        # Сток проверяется наравне с лимитом на одни руки: раньше сюда
        # смотрели только при добавлении в корзину, и последнюю штуку можно
        # было положить, а потом плюсом набрать больше, чем есть
        ceiling = _quantity_ceiling(product)
        if ceiling is not None and item_data.quantity > ceiling:
            raise HTTPException(
                status_code=400,
                detail=_limit_message(product, cart_item.quantity, ceiling),
            )
    
    cart_item.quantity = item_data.quantity
    await db.commit()
    
    return {"message": "Cart item updated"}


@router.delete("/{item_id}")
async def remove_from_cart(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove item from cart"""
    cart_item = await db.get(CartItem, uuid.UUID(item_id))
    
    if not cart_item or cart_item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Cart item not found")
    
    await db.delete(cart_item)
    await db.commit()
    
    return {"message": "Item removed from cart"}


@router.delete("")
async def clear_cart(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Clear all items from cart"""
    stmt = select(CartItem).where(CartItem.user_id == user.id)
    result = await db.execute(stmt)
    cart_items = result.scalars().all()
    
    for item in cart_items:
        await db.delete(item)
    
    await db.commit()
    
    return {"message": "Cart cleared"}
