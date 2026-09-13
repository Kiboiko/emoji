"""baseline: таблицы digital_items, payments, withdrawals

Эти три таблицы существовали только за счёт Base.metadata.create_all() при
старте приложения и не имели ни одной миграции. Последствия:

  * `alembic upgrade head` на чистой базе давал НЕПОЛНУЮ схему — приложение
    поднималось только потому, что create_all() дописывал недостающее;
  * первый же `alembic revision --autogenerate` увидел бы их как новые и
    попытался создать заново — на проде это падало бы с "relation already
    exists".

Миграция приводит историю Alembic в соответствие с фактическим состоянием.
Она идемпотентна: таблица создаётся только если её нет. На проде, где они уже
созданы через create_all(), это no-op; на чистой базе — создаёт схему.

DDL списан с фактического состояния боевой БД, воспроизведённого локально
(см. docs/db/schema-baseline-prod-equivalent.sql), а не с моделей — чтобы
миграция не «чинила» попутно то, чего мы не собирались менять.

Revision ID: b7c1d2e3f4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if not _has_table('digital_items'):
        op.create_table(
            'digital_items',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('is_sold', sa.Boolean(), nullable=False),
            sa.Column('order_id', sa.UUID(), nullable=True),
            sa.Column('reserved_until', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _has_table('payments'):
        op.create_table(
            'payments',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('order_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('external_id', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

    if not _has_table('withdrawals'):
        op.create_table(
            'withdrawals',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('wallet', sa.String(length=255), nullable=False),
            sa.Column(
                'status',
                sa.Enum('PENDING', 'COMPLETED', name='withdrawalstatus',
                        native_enum=False, length=20),
                nullable=False,
            ),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    # Откат удаляет таблицы вместе с данными. Оставлен для полноты цепочки,
    # на боевой базе применять осознанно.
    for name in ('withdrawals', 'payments', 'digital_items'):
        if _has_table(name):
            op.drop_table(name)
