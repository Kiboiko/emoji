"""релей-чат: активная сделка пользователя

Маршрутизация сообщений в релее. У человека может быть несколько открытых
сделок одновременно, и когда он пишет боту обычным сообщением, надо понять,
какому контрагенту его адресовать.

Основной механизм — «активная сделка»: после покупки она становится текущей,
переключение инлайн-кнопкой. Дополнительно работает reply на сообщение
контрагента, который определяет сделку по нему и перекрывает активную.

SET NULL: удаление сделки не должно ломать пользователя.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('active_deal_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'users_active_deal_id_fkey', 'users', 'deals',
        ['active_deal_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('users_active_deal_id_fkey', 'users', type_='foreignkey')
    op.drop_column('users', 'active_deal_id')
