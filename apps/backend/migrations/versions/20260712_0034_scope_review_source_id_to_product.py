"""Scope review source identifiers to a product.

Revision ID: 20260712_0034
Revises: 20260712_0033
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260712_0034"
down_revision: str | None = "20260712_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_product_reviews_source_review",
        "product_reviews",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_product_reviews_source_product_review",
        "product_reviews",
        ["source", "product_id", "source_review_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_product_reviews_source_product_review",
        "product_reviews",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_product_reviews_source_review",
        "product_reviews",
        ["source", "source_review_id"],
    )
