"""Cache profile photos supplied by signed Telegram Mini App data."""
from alembic import op
import sqlalchemy as sa

revision = "a0035avatars"
down_revision = "a0034inquiries"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("photo_url", sa.String(2048), nullable=True))


def downgrade():
    op.drop_column("users", "photo_url")
