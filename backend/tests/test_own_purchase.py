"""An owner cannot obtain an invoice through a new or legacy cart/order."""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from models.cart import CartItem
from models.category import Category
from models.order import Order, OrderItem
from models.payment import Payment
from models.product import Product
from routes import payments
from test_http_wiring import client, _bearer

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def owned(db, user_factory):
    owner = await user_factory()
    category = Category(name_ru="Тест", name_en="Test")
    db.add(category)
    await db.flush()
    product = Product(name_ru="Мой товар", name_en="My product", description_ru="", description_en="",
        price_usdt=Decimal("2.00"), image_url="/uploads/a.jpg", category_id=category.id,
        owner_user_id=owner.id, type="p2p", is_p2p=True, stock=4, content_data={})
    db.add(product)
    await db.flush()
    return owner, product


@pytest.mark.parametrize("kind", ["p2p", "subscription", "service", "digital"])
async def test_cannot_add_own_product_but_other_buyer_can(client, db, owned, user_factory, kind):
    owner, product = owned
    product.type = kind
    await db.flush()
    response = await client.post('/api/cart', headers=_bearer(owner), json={"product_id":str(product.id), "quantity":1})
    assert response.status_code == 400 and "собственный" in response.json()['detail']
    assert await db.scalar(select(func.count()).select_from(CartItem)) == 0
    buyer = await user_factory()
    assert (await client.post('/api/cart', headers=_bearer(buyer), json={"product_id":str(product.id), "quantity":1})).status_code == 200


async def test_legacy_own_cart_cannot_update_or_checkout(client, db, owned):
    owner, product = owned
    item = CartItem(user_id=owner.id, product_id=product.id, quantity=1)
    db.add(item)
    await db.flush()
    headers = _bearer(owner)
    assert (await client.put(f'/api/cart/{item.id}', headers=headers, json={"quantity":2})).status_code == 400
    response = await client.post('/api/orders', headers=headers, json={"currency":"TON", "accept_terms":True})
    assert response.status_code == 400 and "собственный" in response.json()['detail']
    await db.refresh(product)
    assert product.stock == 4
    assert await db.scalar(select(func.count()).select_from(Order)) == 0
    assert await db.scalar(select(func.count()).select_from(Payment)) == 0
    assert (await client.delete(f'/api/cart/{item.id}', headers=headers)).status_code == 200


async def test_legacy_own_order_cannot_get_payment(client, db, owned, order_factory, monkeypatch):
    owner, product = owned
    order = await order_factory(user=owner)
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1,
                     price_usdt=product.price_usdt, product_snapshot={}))
    await db.flush()
    create_payment = AsyncMock()
    monkeypatch.setattr(payments.payment_service, 'create_or_refresh_payment', create_payment)
    response = await client.post(f'/api/payments/ton/init/{order.id}', headers=_bearer(owner))
    assert response.status_code == 400
    create_payment.assert_not_awaited()


async def test_public_product_exposes_owner_uuid_for_buy_controls(client, owned):
    owner, product = owned
    response = await client.get(f'/api/products/{product.id}')
    assert response.status_code == 200
    assert response.json()['owner_user_id'] == str(owner.id)
