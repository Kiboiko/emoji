"""Индекс порядка каталога

Только добавление индекса, данные не меняются.

Страница каталога сортирует товары по (is_top desc, sort_order desc,
created_at desc, id) и берёт сорок. Без индекса база читала все активные
товары и сортировала их ради сорока: 2,5 мс на 5000 товаров, и время растёт
вместе с каталогом. Частичный индекс по активным товарам даёт чтение сорока
строк по индексу (0,2 мс), в том числе для страницы категории.

if_not_exists: миграция безопасна к повторному запуску.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_products_catalog_order', 'products',
        [sa.text('is_top DESC'), sa.text('sort_order DESC'), sa.text('created_at DESC'), 'id'],
        # Предикат тот же, что в запросе каталога (is_active IS true): база
        # берёт частичный индекс, только если докажет, что условие запроса
        # из него следует
        postgresql_where=sa.text('is_active IS TRUE'),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index('ix_products_catalog_order', table_name='products', if_exists=True)
