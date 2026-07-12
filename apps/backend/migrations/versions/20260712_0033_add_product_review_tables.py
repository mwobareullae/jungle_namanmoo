"""add product review storage and metric tables

Revision ID: 20260712_0033
Revises: 20260711_0032
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260712_0033"
down_revision: str | None = "20260711_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _count_column(name: str, *, big: bool = False) -> sa.Column:
    column_type = sa.BigInteger() if big else sa.Integer()
    return sa.Column(name, column_type, server_default="0", nullable=False)


def _decimal_column(
    name: str,
    precision: int,
    scale: int,
    *,
    default: str = "0",
    nullable: bool = False,
) -> sa.Column:
    return sa.Column(
        name,
        sa.Numeric(precision=precision, scale=scale),
        server_default=default if not nullable else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "product_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_code", sa.String(length=80), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("order_item_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_review_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_review_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("review_type", sa.String(length=20), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("option_text", sa.Text(), nullable=True),
        sa.Column("is_repurchase_review", sa.Boolean(), nullable=True),
        sa.Column("verified_purchase", sa.Boolean(), nullable=True),
        sa.Column("helpful_count", sa.Integer(), nullable=True),
        sa.Column("source_has_photo", sa.Boolean(), nullable=True),
        sa.Column("source_badge_labels_json", JSONB, nullable=True),
        sa.Column("source_metadata_json", JSONB, nullable=True),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("profile_mapping_version", sa.String(length=40), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status in ('PENDING', 'PUBLISHED', 'HIDDEN', 'DELETED')",
            name="ck_product_reviews_status",
        ),
        sa.CheckConstraint(
            "review_type is null or review_type in ('GENERAL', 'MONTH_USE')",
            name="ck_product_reviews_type",
        ),
        sa.CheckConstraint(
            "rating is null or (rating >= 1 and rating <= 5)",
            name="ck_product_reviews_rating",
        ),
        sa.CheckConstraint(
            "helpful_count is null or helpful_count >= 0",
            name="ck_product_reviews_helpful",
        ),
        sa.CheckConstraint(
            "rating is not null or (review_text is not null and length(trim(review_text)) > 0)",
            name="ck_product_reviews_content",
        ),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"]),
        sa.ForeignKeyConstraint(["parent_review_id"], ["product_reviews.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_code"),
        sa.UniqueConstraint("source", "source_review_id", name="uq_product_reviews_source_review"),
        sa.UniqueConstraint("order_item_id", "review_type", name="uq_product_reviews_order_item_type"),
    )
    op.create_index("ix_product_reviews_order_item_id", "product_reviews", ["order_item_id"])
    op.create_index("ix_product_reviews_parent_review_id", "product_reviews", ["parent_review_id"])
    op.create_index("ix_product_reviews_product_id", "product_reviews", ["product_id"])
    op.create_index("ix_product_reviews_user_id", "product_reviews", ["user_id"])
    op.create_index(
        "ix_product_reviews_product_status_reviewed",
        "product_reviews",
        ["product_id", "status", "reviewed_at", "id"],
    )

    op.create_table(
        "product_review_profile_labels",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("value_code", sa.String(length=64), nullable=False),
        sa.Column("source_label", sa.String(length=120), nullable=False),
        sa.Column("mapping_source", sa.String(length=40), nullable=False),
        sa.Column("mapping_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "dimension in ('SKIN_TYPE', 'SENSITIVITY', 'SKIN_CONCERN', 'SKIN_TONE')",
            name="ck_review_profile_labels_dimension",
        ),
        sa.CheckConstraint(
            "mapping_confidence >= 0 and mapping_confidence <= 1",
            name="ck_review_profile_labels_confidence",
        ),
        sa.ForeignKeyConstraint(["review_id"], ["product_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_id",
            "dimension",
            "value_code",
            name="uq_review_profile_labels_review_value",
        ),
    )
    op.create_index(
        "ix_product_review_profile_labels_review_id",
        "product_review_profile_labels",
        ["review_id"],
    )
    op.create_index(
        "ix_review_profile_labels_dimension_value_review",
        "product_review_profile_labels",
        ["dimension", "value_code", "review_id"],
    )

    op.create_table(
        "product_review_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        _count_column("review_count"),
        _count_column("rating_count"),
        _count_column("rating_1_count"),
        _count_column("rating_2_count"),
        _count_column("rating_3_count"),
        _count_column("rating_4_count"),
        _count_column("rating_5_count"),
        _decimal_column("average_rating", 6, 4, nullable=True),
        _decimal_column("weighted_average_rating", 6, 4, nullable=True),
        _decimal_column("bayesian_rating", 6, 4, nullable=True),
        _decimal_column("category_prior_rating", 6, 4, nullable=True),
        _count_column("general_review_count"),
        _count_column("month_use_review_count"),
        _decimal_column("general_average_rating", 6, 4, nullable=True),
        _decimal_column("month_use_average_rating", 6, 4, nullable=True),
        _count_column("repurchase_known_count"),
        _count_column("repurchase_review_count"),
        _decimal_column("repurchase_rate", 7, 6, nullable=True),
        _decimal_column("bayesian_repurchase_rate", 7, 6, nullable=True),
        _decimal_column("category_prior_repurchase_rate", 7, 6, nullable=True),
        _count_column("profile_labeled_review_count"),
        _count_column("source_photo_marker_count"),
        _count_column("helpful_count_sum", big=True),
        _decimal_column("weight_sum", 18, 6),
        _decimal_column("weight_square_sum", 20, 8),
        _decimal_column("rating_effective_sample_size", 18, 6),
        _decimal_column("repurchase_effective_sample_size", 18, 6),
        _decimal_column("month_use_effective_sample_size", 18, 6),
        _decimal_column("effective_sample_size", 18, 6),
        _decimal_column("prior_strength", 8, 4, default="20"),
        _decimal_column("rating_score", 7, 6, default="0.5"),
        _decimal_column("repurchase_score", 7, 6, default="0.5"),
        _decimal_column("month_consistency_score", 7, 6, nullable=True),
        _decimal_column("confidence", 7, 6),
        _decimal_column("review_quality_score", 7, 6, default="0.5"),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "score_version",
            sa.String(length=40),
            server_default="review_quality_v1",
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "review_count >= 0 and rating_count >= 0 and general_review_count >= 0 "
            "and month_use_review_count >= 0 and repurchase_known_count >= 0 "
            "and repurchase_review_count >= 0 and profile_labeled_review_count >= 0 "
            "and source_photo_marker_count >= 0 and helpful_count_sum >= 0",
            name="ck_review_metrics_counts",
        ),
        sa.CheckConstraint(
            "rating_1_count >= 0 and rating_2_count >= 0 and rating_3_count >= 0 "
            "and rating_4_count >= 0 and rating_5_count >= 0",
            name="ck_review_metrics_rating_counts",
        ),
        sa.CheckConstraint(
            "(average_rating is null or (average_rating >= 1 and average_rating <= 5)) "
            "and (weighted_average_rating is null or (weighted_average_rating >= 1 and weighted_average_rating <= 5)) "
            "and (bayesian_rating is null or (bayesian_rating >= 1 and bayesian_rating <= 5)) "
            "and (category_prior_rating is null or (category_prior_rating >= 1 and category_prior_rating <= 5)) "
            "and (general_average_rating is null or (general_average_rating >= 1 and general_average_rating <= 5)) "
            "and (month_use_average_rating is null or (month_use_average_rating >= 1 and month_use_average_rating <= 5))",
            name="ck_review_metrics_ratings",
        ),
        sa.CheckConstraint(
            "(repurchase_rate is null or (repurchase_rate >= 0 and repurchase_rate <= 1)) "
            "and (bayesian_repurchase_rate is null or (bayesian_repurchase_rate >= 0 and bayesian_repurchase_rate <= 1)) "
            "and (category_prior_repurchase_rate is null or "
            "(category_prior_repurchase_rate >= 0 and category_prior_repurchase_rate <= 1))",
            name="ck_review_metrics_rates",
        ),
        sa.CheckConstraint(
            "rating_score >= 0 and rating_score <= 1 and repurchase_score >= 0 and repurchase_score <= 1 "
            "and (month_consistency_score is null or "
            "(month_consistency_score >= 0 and month_consistency_score <= 1)) "
            "and confidence >= 0 and confidence <= 1 "
            "and review_quality_score >= 0 and review_quality_score <= 1",
            name="ck_review_metrics_scores",
        ),
        sa.CheckConstraint(
            "weight_sum >= 0 and weight_square_sum >= 0 and rating_effective_sample_size >= 0 "
            "and repurchase_effective_sample_size >= 0 and month_use_effective_sample_size >= 0 "
            "and effective_sample_size >= 0 and prior_strength > 0",
            name="ck_review_metrics_samples",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_product_review_metrics_product"),
    )
    op.create_index("ix_product_review_metrics_product_id", "product_review_metrics", ["product_id"])

    op.create_table(
        "product_review_segment_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("value_code", sa.String(length=64), nullable=False),
        _count_column("review_count"),
        _count_column("rating_count"),
        _count_column("month_use_review_count"),
        _count_column("repurchase_known_count"),
        _count_column("repurchase_review_count"),
        _decimal_column("average_rating", 6, 4, nullable=True),
        _decimal_column("weighted_average_rating", 6, 4, nullable=True),
        _decimal_column("bayesian_rating", 6, 4, nullable=True),
        _decimal_column("product_prior_rating", 6, 4, nullable=True),
        _decimal_column("repurchase_rate", 7, 6, nullable=True),
        _decimal_column("bayesian_repurchase_rate", 7, 6, nullable=True),
        _decimal_column("product_prior_repurchase_rate", 7, 6, nullable=True),
        _decimal_column("weight_sum", 18, 6),
        _decimal_column("weight_square_sum", 20, 8),
        _decimal_column("effective_sample_size", 18, 6),
        _decimal_column("rating_effective_sample_size", 18, 6),
        _decimal_column("repurchase_effective_sample_size", 18, 6),
        _decimal_column("rating_affinity_score", 7, 6, default="0.5"),
        _decimal_column("repurchase_affinity_score", 7, 6, default="0.5"),
        _decimal_column("total_affinity_score", 7, 6, default="0.5"),
        _decimal_column("confidence", 7, 6),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "score_version",
            sa.String(length=40),
            server_default="review_quality_v1",
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "dimension in ('SKIN_TYPE', 'SENSITIVITY', 'SKIN_CONCERN', 'SKIN_TONE')",
            name="ck_review_segment_metrics_dimension",
        ),
        sa.CheckConstraint(
            "review_count >= 0 and rating_count >= 0 and month_use_review_count >= 0 "
            "and repurchase_known_count >= 0 and repurchase_review_count >= 0",
            name="ck_review_segment_metrics_counts",
        ),
        sa.CheckConstraint(
            "(average_rating is null or (average_rating >= 1 and average_rating <= 5)) "
            "and (weighted_average_rating is null or (weighted_average_rating >= 1 and weighted_average_rating <= 5)) "
            "and (bayesian_rating is null or (bayesian_rating >= 1 and bayesian_rating <= 5)) "
            "and (product_prior_rating is null or (product_prior_rating >= 1 and product_prior_rating <= 5))",
            name="ck_review_segment_metrics_ratings",
        ),
        sa.CheckConstraint(
            "(repurchase_rate is null or (repurchase_rate >= 0 and repurchase_rate <= 1)) "
            "and (bayesian_repurchase_rate is null or (bayesian_repurchase_rate >= 0 and bayesian_repurchase_rate <= 1)) "
            "and (product_prior_repurchase_rate is null or "
            "(product_prior_repurchase_rate >= 0 and product_prior_repurchase_rate <= 1))",
            name="ck_review_segment_metrics_rates",
        ),
        sa.CheckConstraint(
            "rating_affinity_score >= 0 and rating_affinity_score <= 1 "
            "and repurchase_affinity_score >= 0 and repurchase_affinity_score <= 1 "
            "and total_affinity_score >= 0 and total_affinity_score <= 1 "
            "and confidence >= 0 and confidence <= 1",
            name="ck_review_segment_metrics_scores",
        ),
        sa.CheckConstraint(
            "weight_sum >= 0 and weight_square_sum >= 0 and effective_sample_size >= 0 "
            "and rating_effective_sample_size >= 0 and repurchase_effective_sample_size >= 0",
            name="ck_review_segment_metrics_samples",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "dimension",
            "value_code",
            name="uq_review_segment_metrics_product_value",
        ),
    )
    op.create_index(
        "ix_product_review_segment_metrics_product_id",
        "product_review_segment_metrics",
        ["product_id"],
    )
    op.create_index(
        "ix_review_segment_metrics_dimension_value_product",
        "product_review_segment_metrics",
        ["dimension", "value_code", "product_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_review_segment_metrics_dimension_value_product",
        table_name="product_review_segment_metrics",
    )
    op.drop_index(
        "ix_product_review_segment_metrics_product_id",
        table_name="product_review_segment_metrics",
    )
    op.drop_table("product_review_segment_metrics")
    op.drop_index("ix_product_review_metrics_product_id", table_name="product_review_metrics")
    op.drop_table("product_review_metrics")
    op.drop_index(
        "ix_review_profile_labels_dimension_value_review",
        table_name="product_review_profile_labels",
    )
    op.drop_index(
        "ix_product_review_profile_labels_review_id",
        table_name="product_review_profile_labels",
    )
    op.drop_table("product_review_profile_labels")
    op.drop_index("ix_product_reviews_product_status_reviewed", table_name="product_reviews")
    op.drop_index("ix_product_reviews_user_id", table_name="product_reviews")
    op.drop_index("ix_product_reviews_product_id", table_name="product_reviews")
    op.drop_index("ix_product_reviews_parent_review_id", table_name="product_reviews")
    op.drop_index("ix_product_reviews_order_item_id", table_name="product_reviews")
    op.drop_table("product_reviews")
