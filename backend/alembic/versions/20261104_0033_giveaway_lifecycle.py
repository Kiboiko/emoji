"""Giveaway membership versions, winner username and post lifecycle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "a0033giftlife"
down_revision = "a0032giveaways"
branch_labels = depends_on = None


def upgrade():
    for column in [sa.Column("public_winner_username", sa.String(64)),
                   sa.Column("post_chat_id", sa.BigInteger()), sa.Column("post_message_id", sa.BigInteger()),
                   sa.Column("post_status", sa.String(20), nullable=False, server_default="disabled"),
                   sa.Column("post_started_at", sa.DateTime())]:
        op.add_column("giveaways", column)
    op.add_column("giveaway_entries", sa.Column("eligibility_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("giveaway_post_cleanup",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("has_photo", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chat_id", "message_id"))
    op.create_index("ix_giveaway_post_cleanup_next_attempt_at", "giveaway_post_cleanup", ["next_attempt_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS(SELECT 1 FROM giveaway_post_cleanup) OR EXISTS(SELECT 1 FROM giveaways WHERE post_status != 'disabled')")).scalar():
        raise RuntimeError("Resolve giveaway posts and cleanup jobs before downgrade")
    op.drop_table("giveaway_post_cleanup")
    op.drop_column("giveaway_entries", "eligibility_version")
    for name in ["post_started_at", "post_status", "post_message_id", "post_chat_id", "public_winner_username"]:
        op.drop_column("giveaways", name)
