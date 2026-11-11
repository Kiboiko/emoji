"""Cart query count stays bounded as rows grow, including paid legacy cleanup."""
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import event
from models.cart import CartItem
from models.category import Category
from models.order import OrderItem, OrderStatus
from models.product import Product
from routes.cart import get_cart

pytestmark = pytest.mark.asyncio


async def test_cart_batch_loading_and_paid_cleanup(db, user_factory, order_factory):
    user = await user_factory()
    category = Category(id=uuid.uuid4(), name_ru='Тест', name_en='Test')
    db.add(category)
    await db.flush()
    products = [Product(id=uuid.uuid4(), name_ru=str(i), name_en=str(i), description_ru='',
                        description_en='', price_usdt=Decimal('0.10'), image_url='/uploads/a.png',
                        category_id=category.id, type='digital', content_data={}, stock=10) for i in range(12)]
    db.add_all(products)
    await db.flush()
    now = datetime.utcnow()
    cart_rows = [CartItem(id=uuid.uuid4(),user_id=user.id,product_id=p.id,quantity=3,
                         created_at=now-timedelta(days=1)+timedelta(seconds=i)) for i,p in enumerate(products)]
    db.add_all(cart_rows)
    await db.flush()
    cart_rows[3].quantity = 2
    await db.flush()
    order = await order_factory(user=user, status=OrderStatus.COMPLETED)
    order.paid_at = now
    db.add(OrderItem(id=uuid.uuid4(),order_id=order.id,product_id=products[0].id,
                     product_snapshot={},quantity=1,price_usdt=Decimal('0.10')))
    await db.flush()
    user_id = user.id
    db.expunge_all()  # A real request has no products in its identity map.
    statements = []
    connection = (await db.connection()).sync_connection
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'): statements.append(statement)
    event.listen(connection, 'before_cursor_execute', capture)
    try:
        result = await get_cart(user=type('Buyer',(),{'id':user_id})(), db=db)
    finally:
        event.remove(connection, 'before_cursor_execute', capture)
    assert len(statements) == 2
    assert len(result.items) == 11
    assert result.total_usdt == 3.2
    assert [item['name'] for item in result.items] == [str(i) for i in range(1,12)]
