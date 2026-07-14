"""add recommendation feature tables

Revision ID: 20260715_0042
Revises: 20260713_0041
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260715_0042"
down_revision: str | None = "20260713_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "product_recommendation_features",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "top_ingredient_codes",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "top_effect_codes",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )

    op.create_table(
        "product_effect_recommendation_features",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("effect_id", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_effect_score", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("ingredient_evidence_score", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("concentration_score", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column(
            "concentration_context",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "top_ingredient_ids",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "best_evidence_ids",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["effect_id"], ["effects.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("product_id", "effect_id"),
    )
    op.create_index(
        "ix_product_effect_recommendation_features_effect_id",
        "product_effect_recommendation_features",
        ["effect_id"],
    )

    op.create_table(
        "user_preference_profiles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("category_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("brand_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("ingredient_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("effect_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("price_band_scores", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("product_ids", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("total_weight", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("effect_top3_sum", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("ingredient_top5_sum", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("category_max", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("brand_max", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("price_band_max", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_count >= 0",
            name="ck_user_preference_profiles_event_count_nonnegative",
        ),
        sa.CheckConstraint(
            "source in ('wishlist', 'cart', 'purchase', 'recent_view', 'click', 'negative_feedback')",
            name="ck_user_preference_profiles_source",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "source"),
    )
    op.create_index(
        "ix_user_preference_profiles_source",
        "user_preference_profiles",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_preference_profiles_source", table_name="user_preference_profiles")
    op.drop_table("user_preference_profiles")
    op.drop_index(
        "ix_product_effect_recommendation_features_effect_id",
        table_name="product_effect_recommendation_features",
    )
    op.drop_table("product_effect_recommendation_features")
    op.drop_table("product_recommendation_features")
