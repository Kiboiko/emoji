"""add_fake_review_fields

Revision ID: a1b2c3d4e5f6
Revises: 0e5993b84a1c
Create Date: 2026-03-25 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0e5993b84a1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add fake review fields
    op.add_column('reviews', sa.Column('is_fake', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('reviews', sa.Column('fake_username', sa.String(100), nullable=True))
    op.add_column('reviews', sa.Column('fake_quantity', sa.Integer(), nullable=True))

    # Make user_id and order_id nullable for fake reviews
    op.alter_column('reviews', 'user_id', existing_type=sa.UUID(), nullable=True)
    op.alter_column('reviews', 'order_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column('reviews', 'order_id', existing_type=sa.UUID(), nullable=False)
    op.alter_column('reviews', 'user_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('reviews', 'fake_quantity')
    op.drop_column('reviews', 'fake_username')
    op.drop_column('reviews', 'is_fake')
