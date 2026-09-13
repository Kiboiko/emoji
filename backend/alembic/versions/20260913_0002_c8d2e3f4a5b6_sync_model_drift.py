"""sync: устранение расхождений модель <-> БД

Два расхождения, из-за которых `alembic revision --autogenerate` предлагал
деструктивные изменения:

1. users.is_blocked
   Колонка создана первой миграцией как NOT NULL БЕЗ default, но в модели User
   отсутствовала. Практический эффект был хуже, чем просто дрейф схемы:
   SQLAlchemy не включала колонку в INSERT, и создание любого пользователя
   падало с NotNullViolationError — то есть регистрация новых покупателей не
   работала вовсе. Колонка добавлена в модель (см. этап 0), здесь ей
   проставляется server_default, чтобы вставки в обход ORM тоже проходили.

   Миграция идемпотентна по обеим возможным историям боевой базы:
     * база поднята миграциями -> колонка есть, ей добавляется default;
     * база поднята только через create_all() -> колонки нет, она создаётся.

2. order_items.product_id
   В БД: NOT NULL + ON DELETE CASCADE. В модели: nullable + ON DELETE SET NULL.
   Правильна модель: при удалении товара заказ обязан сохраниться — состав
   заказа и так лежит в снапшоте order_items.product_snapshot. С текущим
   CASCADE удаление товара из каталога унесло бы за собой позиции заказов,
   то есть историю покупок и выручку.

Revision ID: c8d2e3f4a5b6
Revises: b7c1d2e3f4a5
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d2e3f4a5b6'
down_revision: Union[str, None] = 'b7c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def _fk_names(table: str, column: str) -> list[str]:
    bind = op.get_bind()
    return [
        fk['name']
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if fk.get('constrained_columns') == [column] and fk.get('name')
    ]


def upgrade() -> None:
    # --- 1. users.is_blocked ---------------------------------------------
    if 'is_blocked' not in _columns('users'):
        op.add_column(
            'users',
            sa.Column('is_blocked', sa.Boolean(), nullable=False,
                      server_default=sa.text('false')),
        )
    else:
        # Колонка есть, но без default — дописываем и подстраховываемся по NULL.
        op.execute("UPDATE users SET is_blocked = false WHERE is_blocked IS NULL")
        op.alter_column('users', 'is_blocked',
                        existing_type=sa.Boolean(),
                        nullable=False,
                        server_default=sa.text('false'))

    # --- 2. order_items.product_id ---------------------------------------
    op.alter_column('order_items', 'product_id',
                    existing_type=sa.UUID(),
                    nullable=True)

    for name in _fk_names('order_items', 'product_id'):
        op.drop_constraint(name, 'order_items', type_='foreignkey')

    op.create_foreign_key(
        'order_items_product_id_fkey', 'order_items', 'products',
        ['product_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    # Возврат product_id к NOT NULL возможен только если нет строк с NULL
    # (они появляются после удаления товара). Чистим ссылки не молча, а падаем:
    # молчаливое удаление позиций заказа при откате недопустимо.
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text("SELECT count(*) FROM order_items WHERE product_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"Откат невозможен: в order_items {orphans} строк с product_id IS NULL. "
            "Это позиции заказов по удалённым товарам — восстановление NOT NULL "
            "потребовало бы их удаления."
        )

    for name in _fk_names('order_items', 'product_id'):
        op.drop_constraint(name, 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'order_items_product_id_fkey', 'order_items', 'products',
        ['product_id'], ['id'], ondelete='CASCADE',
    )
    op.alter_column('order_items', 'product_id',
                    existing_type=sa.UUID(),
                    nullable=False)

    op.alter_column('users', 'is_blocked',
                    existing_type=sa.Boolean(),
                    server_default=None)
