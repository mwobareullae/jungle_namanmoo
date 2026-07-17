"""add product import SKU

Revision ID: 20260717_0049
Revises: 20260717_0048
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0049"
down_revision: str | None = "20260717_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


IMPORT_SKU_FORMAT_CHECK = "import_sku is null or import_sku ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'"
IMPORT_SKU_NOT_NULL_PREDICATE = "import_sku IS NOT NULL"


def upgrade() -> None:
    op.add_column("products", sa.Column("import_sku", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_products_import_sku_format",
        "products",
        IMPORT_SKU_FORMAT_CHECK,
    )
    op.create_index(
        "uq_products_import_sku_not_null",
        "products",
        ["import_sku"],
        unique=True,
        postgresql_where=sa.text(IMPORT_SKU_NOT_NULL_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_products_import_sku_not_null", table_name="products")
    op.drop_constraint("ck_products_import_sku_format", "products", type_="check")
    op.drop_column("products", "import_sku")
