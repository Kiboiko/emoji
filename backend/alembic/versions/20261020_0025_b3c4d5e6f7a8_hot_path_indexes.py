"""Индексы для горячих запросов

Только добавление индексов, данные не меняются. До этого на products,
orders, order_items, cart_items, reviews, digital_items и deals.product_id
индексов не было вовсе (внешний ключ в PostgreSQL индекс не создаёт), и
каждый запрос каталога, корзины, «моих заказов» и пересчёта остатка читал
таблицу целиком. На десятке товаров незаметно, на тысячах — заметно.

if_not_exists: миграция безопасна к повторному запуску и к индексам, которые
кто-то уже завёл руками.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = [
    ('ix_products_catalog', 'products', ['is_active', 'category_id']),
    ('ix_products_owner', 'products', ['owner_user_id']),
    ('ix_orders_user', 'orders', ['user_id', 'created_at']),
    ('ix_orders_status', 'orders', ['status', 'created_at']),
    ('ix_order_items_order', 'order_items', ['order_id']),
    ('ix_order_items_product', 'order_items', ['product_id']),
    ('ix_cart_items_user', 'cart_items', ['user_id']),
    ('ix_digital_items_product', 'digital_items', ['product_id', 'is_sold']),
    ('ix_withdrawals_user', 'withdrawals', ['user_id', 'created_at']),
    ('ix_withdrawals_status', 'withdrawals', ['status', 'created_at']),
    ('ix_reviews_product', 'reviews', ['product_id', 'created_at']),
    ('ix_deals_product', 'deals', ['product_id']),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
