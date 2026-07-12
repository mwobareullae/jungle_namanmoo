"""Allow content-free deleted review tombstones.

Revision ID: 20260712_0035
Revises: 20260712_0034
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260712_0035"
down_revision: str | None = "20260712_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_product_reviews_content",
        "product_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_reviews_content",
        "product_reviews",
        "status = 'DELETED' or rating is not null or "
        "(review_text is not null and length(trim(review_text)) > 0)",
    )
    op.create_index(
        "ix_product_reviews_user_status_reviewed",
        "product_reviews",
        ["user_id", "status", "reviewed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_reviews_user_status_reviewed",
        table_name="product_reviews",
    )
    op.drop_constraint(
        "ck_product_reviews_content",
        "product_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_product_reviews_content",
        "product_reviews",
        "rating is not null or "
        "(review_text is not null and length(trim(review_text)) > 0)",
    )
