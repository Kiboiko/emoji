"""Английское название заявки

У заявки было одно поле названия, и при одобрении оно уходило в товар сразу
в обе колонки — name_ru и name_en. Покупатель с английским интерфейсом видел
в каталоге русское название, а переключатель языка на такой товар не влиял
вовсе.

Колонка необязательная: у заявок, заведённых до этой правки, английского
названия нет, и подставлять туда русское на уровне базы нельзя — иначе
потом не отличить «автор так и хотел» от «поле не заполняли».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('product_listings', sa.Column('name_en', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('product_listings', 'name_en')
