"""подписки на закрытые каналы

Новые таблицы: channels, subscription_plans, subscriptions,
subscription_access_log. Существующие таблицы не затрагиваются — подписка
продаётся через уже существующие products/cart/orders как товар с
type='subscription'.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CHANNEL_STATUSES = ('DRAFT', 'PENDING', 'ACTIVE', 'SUSPENDED', 'REJECTED')
SUBSCRIPTION_STATUSES = ('PENDING', 'ACTIVE', 'EXPIRED', 'REVOKED')
ACCESS_ACTIONS = (
    'INVITE_CREATED', 'JOINED', 'LEFT', 'KICKED', 'KICK_FAILED',
    'INVITE_FAILED', 'REVOKED', 'EXTENDED',
)


def upgrade() -> None:
    op.create_table(
        'channels',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_user_id', sa.UUID(), nullable=False),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('payout_wallet', sa.String(length=80), nullable=True),
        sa.Column('bot_is_admin', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('bot_checked_at', sa.DateTime(), nullable=True),
        sa.Column('bot_check_error', sa.Text(), nullable=True),
        sa.Column('status',
                  sa.Enum(*CHANNEL_STATUSES, name='channelstatus',
                          native_enum=False, length=20),
                  nullable=False),
        sa.Column('moderation_comment', sa.Text(), nullable=True),
        sa.Column('moderated_at', sa.DateTime(), nullable=True),
        sa.Column('terms_version', sa.String(length=20), nullable=True),
        sa.Column('terms_accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Один канал нельзя подключить дважды — иначе два автора продавали бы
        # доступ в один и тот же чат
        sa.UniqueConstraint('telegram_chat_id', name='uq_channels_chat_id'),
    )
    op.create_index('ix_channels_status', 'channels', ['status'])

    op.create_table(
        'subscription_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('channel_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('title_ru', sa.String(length=255), nullable=False),
        sa.Column('title_en', sa.String(length=255), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=False),
        sa.Column('price_usd', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        # SET NULL: удаление товара из каталога не должно уносить тариф
        # вместе с историей подписок по нему
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('channel_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=True),
        sa.Column('order_id', sa.UUID(), nullable=True),
        sa.Column('status',
                  sa.Enum(*SUBSCRIPTION_STATUSES, name='subscriptionstatus',
                          native_enum=False, length=20),
                  nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('invite_link', sa.String(length=255), nullable=True),
        sa.Column('invite_link_expires_at', sa.DateTime(), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('reminder_sent_for_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Главный запрос джобы истечения: активные с вышедшим сроком
    op.create_index('ix_subscriptions_status_expires', 'subscriptions',
                    ['status', 'expires_at'])
    op.create_index('ix_subscriptions_user_channel', 'subscriptions',
                    ['user_id', 'channel_id'])

    op.create_table(
        'subscription_access_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('subscription_id', sa.UUID(), nullable=False),
        sa.Column('action',
                  sa.Enum(*ACCESS_ACTIONS, name='accessaction',
                          native_enum=False, length=20),
                  nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_access_log_subscription', 'subscription_access_log',
                    ['subscription_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_access_log_subscription', table_name='subscription_access_log')
    op.drop_table('subscription_access_log')
    op.drop_index('ix_subscriptions_user_channel', table_name='subscriptions')
    op.drop_index('ix_subscriptions_status_expires', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_table('subscription_plans')
    op.drop_index('ix_channels_status', table_name='channels')
    op.drop_table('channels')
