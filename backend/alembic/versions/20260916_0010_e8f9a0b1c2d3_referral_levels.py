"""Реферальная программа: уровни, источники, целочисленные суммы

Новые колонки заполняются только у начислений, сделанных после этого
обновления. Старые записи не пересчитываются: процент тогда брался из .env,
и подставить его задним числом значило бы выдумать данные, которых нет.
Поэтому percent_bp_applied, source и amount_minor допускают NULL — «неизвестно»,
а не «ноль».

currency ставится 'USD' всем строкам, и для старых это верно: реферальные
всегда считались в долларах.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-09-16 08:42:01.021285

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'referral_transactions',
        sa.Column('level', sa.Integer(), server_default=sa.text('1'), nullable=False),
    )
    op.add_column(
        'referral_transactions',
        sa.Column('percent_bp_applied', sa.Integer(), nullable=True),
    )
    op.add_column(
        'referral_transactions',
        sa.Column('source', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'referral_transactions',
        sa.Column('amount_minor', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'referral_transactions',
        sa.Column('currency', sa.String(length=10), server_default=sa.text("'USD'"), nullable=False),
    )
    op.create_index(
        'ix_referral_tx_created', 'referral_transactions', ['created_at'], unique=False,
    )
    op.create_index(
        'ix_referral_tx_referrer', 'referral_transactions', ['referrer_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_referral_tx_referrer', table_name='referral_transactions')
    op.drop_index('ix_referral_tx_created', table_name='referral_transactions')
    op.drop_column('referral_transactions', 'currency')
    op.drop_column('referral_transactions', 'amount_minor')
    op.drop_column('referral_transactions', 'source')
    op.drop_column('referral_transactions', 'percent_bp_applied')
    op.drop_column('referral_transactions', 'level')
