"""add wishlist and recent views

Revision ID: 20260705_0020
Revises: 20260705_0019
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260705_0020"
down_revision: str | None = "20260705_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wishlists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_wishlists_user_product"),
    )
    op.create_index("ix_wishlists_product_id", "wishlists", ["product_id"])
    op.create_index("ix_wishlists_user_added_at", "wishlists", ["user_id", "added_at"])
    op.create_index("ix_wishlists_user_id", "wishlists", ["user_id"])

    op.create_table(
        "recent_views",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_recent_views_user_product"),
    )
    op.create_index("ix_recent_views_product_id", "recent_views", ["product_id"])
    op.create_index("ix_recent_views_user_id", "recent_views", ["user_id"])
    op.create_index("ix_recent_views_user_viewed_at", "recent_views", ["user_id", "viewed_at"])


def downgrade() -> None:
    op.drop_index("ix_recent_views_user_viewed_at", table_name="recent_views")
    op.drop_index("ix_recent_views_user_id", table_name="recent_views")
    op.drop_index("ix_recent_views_product_id", table_name="recent_views")
    op.drop_table("recent_views")

    op.drop_index("ix_wishlists_user_id", table_name="wishlists")
    op.drop_index("ix_wishlists_user_added_at", table_name="wishlists")
    op.drop_index("ix_wishlists_product_id", table_name="wishlists")
    op.drop_table("wishlists")
