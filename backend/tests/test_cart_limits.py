"""
Что корзина отвечает, когда взять больше нельзя.

Отказ здесь — штатная ситуация, а не поломка: товар продавца существует в
одном экземпляре, и второе нажатие «В корзину» по нему упирается в предел.
Раньше в этот момент покупателю показывали «Maximum quantity is 1» —
английскую строку поверх русского интерфейса, которая вдобавок умалчивала
о главном: товар уже лежит в его корзине.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models.category import Category
from models.product import Product
from routes import cart as cart_routes
from schemas.cart import CartItemCreate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def product(db):
    category = Category(id=uuid.uuid4(), name_ru="Вещи", name_en="Things")
    db.add(category)
    await db.flush()

    row = Product(
        id=uuid.uuid4(),
        name_ru="Клавиатура", name_en="Keyboard",
        description_ru="описание", description_en="description",
        price_usdt=Decimal("50.00"),
        image_url="/uploads/listings/a.jpg",
        category_id=category.id,
        type="p2p", min_quantity=1, max_quantity=1, stock=1,
        content_data={}, is_p2p=True,
    )
    db.add(row)
    await db.flush()
    return row


async def test_second_add_says_the_item_is_already_in_the_cart(db, user_factory, product):
    buyer = await user_factory(username="cart_buyer")

    await cart_routes.add_to_cart(
        CartItemCreate(product_id=product.id, quantity=1), user=buyer, db=db,
    )

    with pytest.raises(HTTPException) as exc:
        await cart_routes.add_to_cart(
            CartItemCreate(product_id=product.id, quantity=1), user=buyer, db=db,
        )

    assert exc.value.status_code == 400
    assert "уже в корзине" in exc.value.detail


async def test_stock_limit_is_reported_in_units(db, user_factory, product):
    """
    Товара несколько, но меньше запрошенного: покупатель должен узнать
    остаток, а не то, что ему «не положено».
    """
    product.stock = 3
    product.max_quantity = 10
    await db.flush()

    buyer = await user_factory(username="cart_buyer_stock")

    with pytest.raises(HTTPException) as exc:
        await cart_routes.add_to_cart(
            CartItemCreate(product_id=product.id, quantity=5), user=buyer, db=db,
        )

    assert "3" in exc.value.detail
