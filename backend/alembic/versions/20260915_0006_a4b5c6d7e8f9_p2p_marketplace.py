"""P2P: товары пользователей, сделки с escrow, релей-чат

Новые таблицы: seller_profiles, product_listings, listing_images, deals,
deal_messages, terms_acceptances.

В products добавляются owner_user_id и is_p2p. Существующие товары площадки
остаются с owner_user_id = NULL и is_p2p = false — поведение для них не
меняется.

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SELLER_STATUSES = ('ACTIVE', 'RESTRICTED', 'BANNED')
LISTING_STATUSES = ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'ARCHIVED')
DEAL_STATUSES = (
    'CREATED', 'PAID_ESCROW', 'CHAT_OPENED', 'DELIVERED_CLAIMED', 'CONFIRMED',
    'RELEASED', 'DISPUTED', 'REFUNDED', 'CANCELLED',
)
MESSAGE_DIRECTIONS = ('BUYER_TO_SELLER', 'SELLER_TO_BUYER', 'SYSTEM')


def upgrade() -> None:
    # --- Товары пользователей -------------------------------------------
    op.add_column('products', sa.Column('owner_user_id', sa.UUID(), nullable=True))
    op.add_column('products', sa.Column(
        'is_p2p', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_foreign_key(
        'products_owner_user_id_fkey', 'products', 'users',
        ['owner_user_id'], ['id'], ondelete='SET NULL',
    )

    op.create_table(
        'seller_profiles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('payout_wallet', sa.String(length=80), nullable=False),
        sa.Column('status', sa.Enum(*SELLER_STATUSES, name='sellerstatus',
                                    native_enum=False, length=20), nullable=False),
        sa.Column('restricted_until', sa.DateTime(), nullable=True),
        sa.Column('restriction_reason', sa.Text(), nullable=True),
        sa.Column('rating_sum', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('rating_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('deals_completed', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('rejected_streak', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('terms_version', sa.String(length=20), nullable=True),
        sa.Column('terms_accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_seller_user'),
    )

    op.create_table(
        'product_listings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('seller_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('category_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('price_usd', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.Enum(*LISTING_STATUSES, name='listingstatus',
                                    native_enum=False, length=20), nullable=False),
        sa.Column('moderator_id', sa.UUID(), nullable=True),
        sa.Column('moderation_comment', sa.Text(), nullable=True),
        sa.Column('moderated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['seller_id'], ['seller_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['moderator_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_listings_status', 'product_listings', ['status', 'created_at'])

    op.create_table(
        'listing_images',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('listing_id', sa.UUID(), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['listing_id'], ['product_listings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'deals',
        sa.Column('id', sa.UUID(), nullable=False),
        # BigSerial: человекочитаемый номер для чата и поддержки
        sa.Column('number', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('order_item_id', sa.UUID(), nullable=True),
        sa.Column('buyer_id', sa.UUID(), nullable=False),
        sa.Column('seller_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('product_name', sa.String(length=500), nullable=False),
        sa.Column('amount_nano', sa.BigInteger(), nullable=False),
        sa.Column('commission_nano', sa.BigInteger(), nullable=False),
        sa.Column('seller_amount_nano', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.Enum(*DEAL_STATUSES, name='dealstatus',
                                    native_enum=False, length=20), nullable=False),
        sa.Column('confirm_deadline_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_claimed_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
        sa.Column('dispute_opened_at', sa.DateTime(), nullable=True),
        sa.Column('dispute_opened_by', sa.UUID(), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.Column('resolved_by_admin_id', sa.UUID(), nullable=True),
        sa.Column('resolution_comment', sa.Text(), nullable=True),
        sa.Column('chat_closed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_item_id'], ['order_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['dispute_opened_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resolved_by_admin_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number', name='uq_deals_number'),
    )
    op.create_index('ix_deals_status_deadline', 'deals', ['status', 'confirm_deadline_at'])
    op.create_index('ix_deals_buyer', 'deals', ['buyer_id'])
    op.create_index('ix_deals_seller', 'deals', ['seller_id'])

    op.create_table(
        'deal_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('deal_id', sa.UUID(), nullable=False),
        sa.Column('direction', sa.Enum(*MESSAGE_DIRECTIONS, name='messagedirection',
                                       native_enum=False, length=20), nullable=False),
        sa.Column('sender_id', sa.UUID(), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('media_type', sa.String(length=30), nullable=True),
        sa.Column('media_file_id', sa.String(length=255), nullable=True),
        sa.Column('source_message_id', sa.BigInteger(), nullable=True),
        sa.Column('delivered_message_id', sa.BigInteger(), nullable=True),
        sa.Column('delivery_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_deal_messages_deal', 'deal_messages', ['deal_id', 'created_at'])
    # По нему ищем сделку, когда пользователь отвечает reply на копию
    op.create_index('ix_deal_messages_delivered', 'deal_messages', ['delivered_message_id'])

    op.create_table(
        'terms_acceptances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        # Дублируется намеренно: запись должна пережить удаление аккаунта,
        # иначе доказательство согласия исчезнет вместе с пользователем
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('terms_version', sa.String(length=20), nullable=False),
        sa.Column('context', sa.String(length=30), nullable=False),
        sa.Column('ref_type', sa.String(length=30), nullable=True),
        sa.Column('ref_id', sa.UUID(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_terms_user_version', 'terms_acceptances', ['user_id', 'terms_version'])


def downgrade() -> None:
    op.drop_index('ix_terms_user_version', table_name='terms_acceptances')
    op.drop_table('terms_acceptances')
    op.drop_index('ix_deal_messages_delivered', table_name='deal_messages')
    op.drop_index('ix_deal_messages_deal', table_name='deal_messages')
    op.drop_table('deal_messages')
    op.drop_index('ix_deals_seller', table_name='deals')
    op.drop_index('ix_deals_buyer', table_name='deals')
    op.drop_index('ix_deals_status_deadline', table_name='deals')
    op.drop_table('deals')
    op.drop_table('listing_images')
    op.drop_index('ix_listings_status', table_name='product_listings')
    op.drop_table('product_listings')
    op.drop_table('seller_profiles')
    op.drop_constraint('products_owner_user_id_fkey', 'products', type_='foreignkey')
    op.drop_column('products', 'is_p2p')
    op.drop_column('products', 'owner_user_id')
