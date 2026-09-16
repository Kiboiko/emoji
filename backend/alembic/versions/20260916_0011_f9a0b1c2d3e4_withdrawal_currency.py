"""Выводы: валюта и целочисленная сумма

До этого выводы были только в USD (реферальный баланс), а заработок
продавца копится в TON — вывести его было нечем.

currency='USD' у существующих строк верно: других валют в выводах не было.
amount_minor допускает NULL — у старых заявок точной целочисленной суммы нет,
и подставлять её пересчётом из float значило бы записать вычисленное как
исходное.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-09-16 16:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'withdrawals',
        sa.Column('currency', sa.String(length=10), server_default=sa.text("'USD'"), nullable=False),
    )
    op.add_column('withdrawals', sa.Column('amount_minor', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('withdrawals', 'amount_minor')
    op.drop_column('withdrawals', 'currency')
