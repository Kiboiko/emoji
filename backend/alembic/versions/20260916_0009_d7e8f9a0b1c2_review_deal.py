"""отзывы: привязка к P2P-сделке

Отзыв о товаре пользователя — это по сути отзыв о продавце: по нему
пересчитывается рейтинг SellerProfile. Привязка к сделке нужна, чтобы:
  * отзыв оставлял только реальный покупатель по завершённой сделке;
  * по одной сделке был ровно один отзыв (UNIQUE) — иначе рейтинг
    накручивается повторными отзывами.

SET NULL: удаление сделки не должно уносить сам отзыв с витрины.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reviews', sa.Column('deal_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'reviews_deal_id_fkey', 'reviews', 'deals',
        ['deal_id'], ['id'], ondelete='SET NULL',
    )
    op.create_unique_constraint('uq_reviews_deal', 'reviews', ['deal_id'])


def downgrade() -> None:
    op.drop_constraint('uq_reviews_deal', 'reviews', type_='unique')
    op.drop_constraint('reviews_deal_id_fkey', 'reviews', type_='foreignkey')
    op.drop_column('reviews', 'deal_id')
