"""Когда пользователь последний раз был в приложении

В шапке чата сделки видно, в сети ли собеседник, а если нет — когда был.
«В сети» знает менеджер сокетов; время последнего визита должно переживать
перезапуск сервера, поэтому оно в базе.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_seen_at')
