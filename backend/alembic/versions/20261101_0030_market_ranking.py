"""Weekly rankings and explicit homepage visibility."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = "a0030ranking"
down_revision = "f7a8b9c0d1e2"
branch_labels = depends_on = None


def upgrade():
    op.add_column("seller_profiles", sa.Column("home_visible", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("seller_profiles", sa.Column("ranking_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("market_ranking_periods", sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("start_at", sa.DateTime(), nullable=False, unique=True), sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("formula_version", sa.String(30), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False), sa.Column("closed_at", sa.DateTime()))
    op.create_table("market_ranking_entries", sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("period_id", pg.UUID(as_uuid=True), sa.ForeignKey("market_ranking_periods.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("seller_id", pg.UUID(as_uuid=True), sa.ForeignKey("seller_profiles.id", ondelete="RESTRICT"), nullable=False),
        *[sa.Column(n, sa.Integer(), nullable=False) for n in ["rank", "sales_count", "review_count", "review_sum"]],
        sa.Column("volume_cents", sa.BigInteger(), nullable=False),
        sa.Column("quality", sa.Numeric(18,9), nullable=False), sa.Column("score", sa.Numeric(18,9), nullable=False),
        sa.UniqueConstraint("period_id", "seller_id"))
    op.create_index("ix_market_ranking_entries_period_id", "market_ranking_entries", ["period_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM market_ranking_periods)")).scalar():
        raise RuntimeError("Preserve ranking history before downgrade")
    op.drop_table("market_ranking_entries")
    op.drop_table("market_ranking_periods")
    op.drop_column("seller_profiles", "ranking_enabled")
    op.drop_column("seller_profiles", "home_visible")
