"""update product images to storage key contract

Revision ID: 20260703_0010
Revises: 20260701_0009
Create Date: 2026-07-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260703_0010"
down_revision: str | None = "20260701_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_images",
        sa.Column("image_type", sa.String(length=20), server_default="detail", nullable=True),
    )
    op.add_column("product_images", sa.Column("storage_key", sa.Text(), nullable=True))

    op.execute(
        """
        UPDATE product_images
        SET storage_key = image_url
        WHERE storage_key IS NULL
          AND image_url IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE product_images
        SET image_type = 'detail'
        WHERE image_type IS NULL
        """
    )

    op.alter_column("product_images", "image_type", nullable=False, server_default="detail")
    op.alter_column("product_images", "storage_key", nullable=False)

    op.create_check_constraint(
        "ck_product_images_image_type",
        "product_images",
        "image_type in ('thumbnail', 'detail')",
    )
    op.create_unique_constraint(
        "uq_product_images_product_type_order",
        "product_images",
        ["product_id", "image_type", "display_order"],
    )
    op.create_unique_constraint(
        "uq_product_images_product_storage_key",
        "product_images",
        ["product_id", "storage_key"],
    )

    op.drop_column("product_images", "image_url")


def downgrade() -> None:
    op.add_column("product_images", sa.Column("image_url", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE product_images
        SET image_url = storage_key
        WHERE image_url IS NULL
        """
    )
    op.alter_column("product_images", "image_url", nullable=False)

    op.drop_constraint("uq_product_images_product_storage_key", "product_images", type_="unique")
    op.drop_constraint("uq_product_images_product_type_order", "product_images", type_="unique")
    op.drop_constraint("ck_product_images_image_type", "product_images", type_="check")
    op.drop_column("product_images", "storage_key")
    op.drop_column("product_images", "image_type")
