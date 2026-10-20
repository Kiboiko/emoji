"""Модераторы, версия токена, журналы входов и действий

Только добавление: существующие строки и таблицы не меняются.

  * users.is_moderator — роль модератора (server_default false);
  * users.token_version — версия токенов персонала, для «выйти везде» и
    выхода после смены пароля (server_default 0);
  * admin_login_log — журнал входов в админку;
  * admin_audit_log — журнал действий администраторов и модераторов.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column(
        'is_moderator', sa.Boolean(), nullable=False, server_default=sa.text('false'),
    ))
    op.add_column('users', sa.Column(
        'token_version', sa.Integer(), nullable=False, server_default=sa.text('0'),
    ))

    op.create_table(
        'admin_login_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=40), nullable=False),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_admin_login_log_created', 'admin_login_log', ['created_at'])

    op.create_table(
        'admin_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('actor_name', sa.String(length=100), nullable=False),
        sa.Column('actor_role', sa.String(length=20), nullable=False),
        sa.Column('action', sa.String(length=60), nullable=False),
        sa.Column('target_type', sa.String(length=40), nullable=True),
        sa.Column('target_id', sa.String(length=64), nullable=True),
        sa.Column('details', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_admin_audit_created', 'admin_audit_log', ['created_at'])
    op.create_index('ix_admin_audit_actor', 'admin_audit_log', ['actor_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_admin_audit_actor', table_name='admin_audit_log')
    op.drop_index('ix_admin_audit_created', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
    op.drop_index('ix_admin_login_log_created', table_name='admin_login_log')
    op.drop_table('admin_login_log')
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'is_moderator')
