"""add product popularity metrics

Revision ID: 20260705_0019
Revises: 20260704_0018
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260705_0019"
down_revision: str | None = "20260704_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_popularity_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("window_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("click_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cart_add_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("order_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("units_sold", sa.Integer(), server_default="0", nullable=False),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("average_rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("popularity_score", sa.Numeric(8, 4), server_default="0", nullable=False),
        sa.Column("score_version", sa.String(length=40), server_default="popular_v1", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("window_days >= 0", name="ck_product_popularity_metrics_window_days_non_negative"),
        sa.CheckConstraint("view_count >= 0", name="ck_product_popularity_metrics_view_count_non_negative"),
        sa.CheckConstraint("click_count >= 0", name="ck_product_popularity_metrics_click_count_non_negative"),
        sa.CheckConstraint("cart_add_count >= 0", name="ck_product_popularity_metrics_cart_add_count_non_negative"),
        sa.CheckConstraint("order_count >= 0", name="ck_product_popularity_metrics_order_count_non_negative"),
        sa.CheckConstraint("units_sold >= 0", name="ck_product_popularity_metrics_units_sold_non_negative"),
        sa.CheckConstraint("review_count >= 0", name="ck_product_popularity_metrics_review_count_non_negative"),
        sa.CheckConstraint(
            "average_rating is null or (average_rating >= 0 and average_rating <= 5)",
            name="ck_product_popularity_metrics_average_rating_range",
        ),
        sa.CheckConstraint("popularity_score >= 0", name="ck_product_popularity_metrics_popularity_score_non_negative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "window_days", name="uq_product_popularity_metrics_product_window"),
    )
    op.create_index("ix_product_popularity_metrics_product_id", "product_popularity_metrics", ["product_id"])
    op.create_index(
        "ix_product_popularity_metrics_window_score",
        "product_popularity_metrics",
        ["window_days", "popularity_score", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_popularity_metrics_window_score", table_name="product_popularity_metrics")
    op.drop_index("ix_product_popularity_metrics_product_id", table_name="product_popularity_metrics")
    op.drop_table("product_popularity_metrics")
