"""Pre-purchase conversations and commission-funded partner links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "a0034inquiries"
down_revision = "a0033giftlife"
branch_labels = depends_on = None


def ident(name="id", target=None, nullable=False, primary=False):
    return sa.Column(name, pg.UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT")] if target else []), primary_key=primary, nullable=nullable)


def upgrade():
    op.create_table("seller_inquiries", ident(primary=True), ident("buyer_id", "users.id"), ident("seller_id", "users.id"),
        ident("seller_profile_id", "seller_profiles.id"), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime()), ident("paid_order_id", "orders.id", nullable=True),
        sa.Column("linked_deal_id", pg.UUID(as_uuid=True), sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("buyer_read_at", sa.DateTime()), sa.Column("seller_read_at", sa.DateTime()))
    op.create_index("ix_seller_inquiries_expires_at", "seller_inquiries", ["expires_at"])
    op.create_index("uq_inquiry_unpaid_pair", "seller_inquiries", ["buyer_id", "seller_id"], unique=True, postgresql_where=sa.text("paid_order_id IS NULL"))
    op.create_index("ix_inquiry_buyer_created", "seller_inquiries", ["buyer_id", "created_at"])
    op.create_index("ix_inquiry_seller_created", "seller_inquiries", ["seller_id", "created_at"])
    op.create_table("seller_inquiry_messages", ident(primary=True),
        sa.Column("inquiry_id", pg.UUID(as_uuid=True), sa.ForeignKey("seller_inquiries.id", ondelete="CASCADE"), nullable=False),
        ident("sender_id", "users.id"), sa.Column("text", sa.Text()), sa.Column("photo_path", sa.String(255)),
        ident("client_id", nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("inquiry_id", "sender_id", "client_id", name="uq_inquiry_message_client"))
    op.create_index("ix_inquiry_messages_chat", "seller_inquiry_messages", ["inquiry_id", "created_at"])
    op.create_index("ix_inquiry_messages_sender", "seller_inquiry_messages", ["sender_id", "created_at"])
    op.create_table("seller_inquiry_media_cleanup", ident("inquiry_id", primary=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("partner_links", ident(primary=True), sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False), ident("beneficiary_id", "users.id"), ident("created_by", "users.id"),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("partner_attributions", ident("buyer_id", "users.id", primary=True), ident("link_id", "partner_links.id"),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_partner_attributions_link_id", "partner_attributions", ["link_id"])
    op.create_table("partner_commissions", ident(primary=True), ident("link_id", "partner_links.id"),
        ident("buyer_id", "users.id"), ident("beneficiary_id", "users.id"), ident("order_id", "orders.id"),
        sa.Column("source_kind", sa.String(20), nullable=False), ident("source_id"), sa.Column("amount_nano", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_kind", "source_id", name="uq_partner_commission_source"),
        sa.CheckConstraint("amount_nano > 0", name="ck_partner_commission_positive"))
    op.create_index("ix_partner_commission_link_created", "partner_commissions", ["link_id", "created_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM partner_attributions) OR EXISTS(SELECT 1 FROM partner_commissions) OR EXISTS(SELECT 1 FROM seller_inquiries) OR EXISTS(SELECT 1 FROM seller_inquiry_media_cleanup)")).scalar():
        raise RuntimeError("Preserve partner attribution, payouts and conversations before downgrade")
    for table in ["partner_commissions", "partner_attributions", "partner_links", "seller_inquiry_media_cleanup", "seller_inquiry_messages", "seller_inquiries"]:
        op.drop_table(table)
