"""External TON promotion invoices and expiration state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    op.create_table("product_promotions",
        sa.Column("product_id", uid, sa.ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("promoted_until", sa.DateTime(), nullable=False))
    op.create_index("ix_product_promotions_promoted_until", "product_promotions", ["promoted_until"])
    op.create_table("promotion_invoices",
        sa.Column("id", uid, primary_key=True),
        sa.Column("product_id", uid, sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("user_id", uid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_nano", sa.BigInteger(), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(10), nullable=False),
        sa.Column("destination_address", sa.String(80), nullable=False),
        sa.Column("payment_comment", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("tx_hash", sa.String(128), unique=True),
        sa.Column("received_nano", sa.BigInteger()),
        sa.Column("credited_nano", sa.BigInteger(), nullable=False),
        sa.Column("credit_reason", sa.String(24)),
        sa.Column("seen_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("promoted_until", sa.DateTime()),
        sa.CheckConstraint("amount_nano > 0 AND duration_hours > 0", name="ck_promotion_invoice_positive"))
    op.create_index("ix_promotion_invoices_status_expires", "promotion_invoices", ["status", "expires_at"])
    op.create_index("ix_promotion_invoices_product", "promotion_invoices", ["product_id"])


def downgrade():
    # Paid invoices and their ledger attribution must survive a code rollback.
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM promotion_invoices WHERE tx_hash IS NOT NULL)")).scalar():
        raise RuntimeError("Cannot drop paid promotion history; resolve rollback without deleting invoices")
    op.drop_table("promotion_invoices")
    op.drop_table("product_promotions")
