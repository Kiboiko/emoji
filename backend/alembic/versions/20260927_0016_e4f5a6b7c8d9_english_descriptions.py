"""Английские описания у заявок и каналов

Название на двух языках уже есть, описание — ещё нет: при публикации одно
и то же описание уходило в товар сразу в обе колонки, и покупатель с
английским интерфейсом читал русский текст.

Колонки необязательные на уровне базы, хотя формы теперь требуют их
заполнить: у заявок и каналов, заведённых раньше, английского текста нет,
и объявлять колонку NOT NULL значило бы либо ронять миграцию, либо
проставлять туда русский — после чего не отличить «так и хотели» от
«поле не существовало».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('product_listings', sa.Column('description_en', sa.Text(), nullable=True))
    op.add_column('channels', sa.Column('description_en', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('channels', 'description_en')
    op.drop_column('product_listings', 'description_en')
