"""Resumable free giveaways and immutable winner history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = "a0032giveaways"
down_revision = "a0031outbox"
branch_labels = depends_on = None


def ident(name="id", target=None):
    return sa.Column(name, pg.UUID(as_uuid=True), *([sa.ForeignKey(target, ondelete="RESTRICT")] if target else []),
        primary_key=name == "id", nullable=False)


def upgrade():
    op.create_table("giveaways", ident(),
        sa.Column("title_ru", sa.String(200), nullable=False), sa.Column("title_en", sa.String(200), nullable=False),
        sa.Column("description_ru", sa.Text(), nullable=False), sa.Column("description_en", sa.Text(), nullable=False),
        sa.Column("prize", sa.String(500), nullable=False), sa.Column("photo_url", sa.String(500)),
        sa.Column("start_at", sa.DateTime(), nullable=False), sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("winner_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("public_winner_label", sa.String(60)), sa.Column("snapshot_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64)), sa.Column("fulfillment_status", sa.String(20), nullable=False),
        *[sa.Column(n, sa.DateTime()) for n in ["draw_started_at", "finished_at", "lease_until"]],
        sa.Column("lease_token", pg.UUID(as_uuid=True)), sa.Column("error_code", sa.String(50)),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.CheckConstraint("end_at > start_at", name="ck_giveaway_dates"))
    op.create_index("ix_giveaways_end_at", "giveaways", ["end_at"])
    op.create_index("ix_giveaways_status", "giveaways", ["status"])
    op.create_table("giveaway_required_chats", ident(), ident("giveaway_id", "giveaways.id"),
        sa.Column("chat_id", sa.BigInteger(), nullable=False), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("join_link", sa.String(500), nullable=False), sa.UniqueConstraint("giveaway_id", "chat_id"))
    op.create_table("giveaway_entries", ident(), ident("giveaway_id", "giveaways.id"), ident("user_id", "users.id"),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("entered_at", sa.DateTime()),
        sa.Column("checked_at", sa.DateTime()), sa.Column("error_code", sa.String(50)), sa.UniqueConstraint("giveaway_id", "user_id"))
    op.create_table("giveaway_draw_attempts", ident(), ident("giveaway_id", "giveaways.id"), ident("entry_id", "giveaway_entries.id"),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("selected_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("giveaway_id", "entry_id"),
        sa.UniqueConstraint("giveaway_id", "ordinal"))
    for name in ["giveaway_required_chats", "giveaway_entries", "giveaway_draw_attempts"]:
        op.create_index(f"ix_{name}_giveaway_id", name, ["giveaway_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM giveaways WHERE status != 'draft')")).scalar():
        raise RuntimeError("Preserve published giveaways and results before downgrade")
    for name in ["giveaway_draw_attempts", "giveaway_entries", "giveaway_required_chats", "giveaways"]:
        op.drop_table(name)
