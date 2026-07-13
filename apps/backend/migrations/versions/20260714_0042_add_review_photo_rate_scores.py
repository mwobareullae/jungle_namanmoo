"""add review photo rate scores and v2 defaults

Revision ID: 20260714_0042
Revises: 20260713_0041
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260714_0042"
down_revision: str | None = "20260713_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_review_metrics",
        sa.Column("bayesian_photo_rate", sa.Numeric(7, 6), nullable=True),
    )
    op.add_column(
        "product_review_metrics",
        sa.Column("photo_rate_score", sa.Numeric(7, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_review_metrics_photo_rates",
        "product_review_metrics",
        "(bayesian_photo_rate is null or "
        "(bayesian_photo_rate >= 0 and bayesian_photo_rate <= 1)) "
        "and (photo_rate_score is null or "
        "(photo_rate_score >= 0 and photo_rate_score <= 1))",
    )
    op.alter_column(
        "product_review_metrics",
        "score_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default="review_quality_v2",
    )
    op.alter_column(
        "product_review_segment_metrics",
        "score_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default="review_quality_v2",
    )


def downgrade() -> None:
    op.alter_column(
        "product_review_segment_metrics",
        "score_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default="review_quality_v1",
    )
    op.alter_column(
        "product_review_metrics",
        "score_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default="review_quality_v1",
    )
    op.drop_constraint(
        "ck_review_metrics_photo_rates",
        "product_review_metrics",
        type_="check",
    )
    op.drop_column("product_review_metrics", "photo_rate_score")
    op.drop_column("product_review_metrics", "bayesian_photo_rate")
