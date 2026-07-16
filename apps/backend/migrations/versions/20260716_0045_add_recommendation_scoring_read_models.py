"""add recommendation scoring read models

Revision ID: 20260716_0045
Revises: 20260716_0044
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260716_0045"
down_revision: str | None = "20260716_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "product_recommendation_scoring_read_models",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("top_ingredient_codes", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("top_effect_codes", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("product_feature_version", sa.String(length=64), nullable=True),
        sa.Column(
            "product_feature_source_current",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("functional_status", sa.String(length=40), nullable=True),
        sa.Column("functional_claims", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("functional_confidence", sa.String(length=20), nullable=True),
        sa.Column("functional_basis", sa.Text(), nullable=True),
        sa.Column("skin_tags", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("dry_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("oily_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("combination_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("normal_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("dehydrated_oily_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("sensitive_fit", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("sensitivity_tag", sa.String(length=40), nullable=True),
        sa.Column("skin_profile_confidence", sa.String(length=20), nullable=True),
        sa.Column("skin_profile_reason", sa.Text(), nullable=True),
        sa.Column("popularity_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("popularity_score_version", sa.String(length=40), nullable=True),
        sa.Column("popularity_window_days", sa.Integer(), nullable=True),
        sa.Column("review_quality_score", sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column("review_confidence", sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column(
            "review_effective_sample_size",
            sa.Numeric(precision=18, scale=6),
            nullable=True,
        ),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("review_score_version", sa.String(length=40), nullable=True),
        sa.Column("read_model_version", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "popularity_window_days is null or popularity_window_days >= 0",
            name="ck_recommendation_scoring_read_models_popularity_window",
        ),
        sa.CheckConstraint(
            "review_count is null or review_count >= 0",
            name="ck_recommendation_scoring_read_models_review_count",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )


def downgrade() -> None:
    op.drop_table("product_recommendation_scoring_read_models")
