"""Two-level categories and deletion protection. Existing categories remain roots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("categories", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])
    op.create_foreign_key("fk_categories_parent_id", "categories", "categories", ["parent_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_categories_not_self_parent", "categories", "parent_id <> id")
    op.drop_constraint("products_category_id_fkey", "products", type_="foreignkey")
    op.create_foreign_key("products_category_id_fkey", "products", "categories", ["category_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    op.drop_constraint("products_category_id_fkey", "products", type_="foreignkey")
    op.create_foreign_key("products_category_id_fkey", "products", "categories", ["category_id"], ["id"], ondelete="CASCADE")
    op.drop_constraint("ck_categories_not_self_parent", "categories", type_="check")
    op.drop_constraint("fk_categories_parent_id", "categories", type_="foreignkey")
    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_column("categories", "parent_id")
