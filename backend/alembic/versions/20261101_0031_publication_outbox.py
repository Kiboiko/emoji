"""Durable, disabled-by-default large-deal publications."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = "a0031outbox"
down_revision = "a0030ranking"
branch_labels = depends_on = None


def upgrade():
    op.create_table("large_deal_config", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("min_nano", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger()), sa.Column("thread_id", sa.Integer()), sa.Column("enabled_at", sa.DateTime()))
    op.create_table("telegram_publications", sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False), sa.Column("source_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=False), sa.Column("thread_id", sa.Integer()),
        sa.Column("payload", pg.JSONB(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime()), sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(50)), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime()), sa.UniqueConstraint("kind", "source_id", "destination_chat_id"))
    op.create_index("ix_telegram_publications_status", "telegram_publications", ["status"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM telegram_publications)")).scalar():
        raise RuntimeError("Preserve publication history before downgrade")
    op.drop_table("telegram_publications")
    op.drop_table("large_deal_config")
