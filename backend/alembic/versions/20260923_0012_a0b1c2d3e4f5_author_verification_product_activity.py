"""Проверенные авторы и активность товара

Три колонки под три разные дыры.

products.is_active — товар может существовать, но не продаваться. До этого
такого состояния не было, и подписки попадали в каталог в момент создания
тарифа: канал ещё висел в черновике, а купить его доступ уже было можно.
Объявления эту дыру обходили тем, что Product создаётся только после
одобрения (см. комментарий к ProductListing), подписки — нет.

Данные чиним здесь же: всё, что продаётся от имени неопубликованного канала,
гасим. На проде такие строки уже лежат в каталоге.

seller_profiles.is_verified / channels.is_verified — галочка проверенного
автора. Ставится только администратором, самому себе её не выдать.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'products',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
    )
    op.add_column(
        'seller_profiles',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column(
        'channels',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    # Каталог фильтрует по is_active на каждом открытии главной — частичный
    # индекс дешевле полного и покрывает ровно тот запрос, который есть.
    op.create_index(
        'ix_products_active', 'products', ['is_active'],
        postgresql_where=sa.text('is_active'),
    )

    # Разбор завала: товары тарифов у каналов, не прошедших модерацию.
    # Связь идёт через subscription_plans.product_id, а не через поле в
    # products — отдельной колонки с каналом у товара нет.
    op.execute(
        """
        UPDATE products
           SET is_active = false
         WHERE id IN (
               SELECT p.product_id
                 FROM subscription_plans p
                 JOIN channels c ON c.id = p.channel_id
                WHERE p.product_id IS NOT NULL
                  AND c.status <> 'ACTIVE'
         )
        """
    )


def downgrade() -> None:
    op.drop_index('ix_products_active', table_name='products')
    op.drop_column('channels', 'is_verified')
    op.drop_column('seller_profiles', 'is_verified')
    op.drop_column('products', 'is_active')
