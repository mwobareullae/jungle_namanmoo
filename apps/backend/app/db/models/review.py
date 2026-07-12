from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import big_integer_pk_type, jsonb_type


REVIEW_STATUS_VALUES = "'PENDING', 'PUBLISHED', 'HIDDEN', 'DELETED'"
REVIEW_TYPE_VALUES = "'GENERAL', 'MONTH_USE'"
REVIEW_PROFILE_DIMENSION_VALUES = "'SKIN_TYPE', 'SENSITIVITY', 'SKIN_CONCERN', 'SKIN_TONE'"


class ProductReview(Base):
    __tablename__ = "product_reviews"
    __table_args__ = (
        CheckConstraint(f"status in ({REVIEW_STATUS_VALUES})", name="ck_product_reviews_status"),
        CheckConstraint(
            f"review_type is null or review_type in ({REVIEW_TYPE_VALUES})",
            name="ck_product_reviews_type",
        ),
        CheckConstraint(
            "rating is null or (rating >= 1 and rating <= 5)",
            name="ck_product_reviews_rating",
        ),
        CheckConstraint(
            "helpful_count is null or helpful_count >= 0",
            name="ck_product_reviews_helpful",
        ),
        CheckConstraint(
            "status = 'DELETED' or rating is not null or "
            "(review_text is not null and length(trim(review_text)) > 0)",
            name="ck_product_reviews_content",
        ),
        UniqueConstraint(
            "source",
            "product_id",
            "source_review_id",
            name="uq_product_reviews_source_product_review",
        ),
        UniqueConstraint("order_item_id", "review_type", name="uq_product_reviews_order_item_type"),
        Index(
            "ix_product_reviews_product_status_reviewed",
            "product_id",
            "status",
            "reviewed_at",
            "id",
        ),
        Index(
            "ix_product_reviews_user_status_reviewed",
            "user_id",
            "status",
            "reviewed_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    review_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), nullable=True, index=True)
    parent_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_reviews.id"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_review_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    review_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    option_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_repurchase_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verified_purchase: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    helpful_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_has_photo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_badge_labels_json: Mapped[list | None] = mapped_column(jsonb_type(), nullable=True)
    source_metadata_json: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    source_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_mapping_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductReviewProfileLabel(Base):
    __tablename__ = "product_review_profile_labels"
    __table_args__ = (
        CheckConstraint(
            f"dimension in ({REVIEW_PROFILE_DIMENSION_VALUES})",
            name="ck_review_profile_labels_dimension",
        ),
        CheckConstraint(
            "mapping_confidence >= 0 and mapping_confidence <= 1",
            name="ck_review_profile_labels_confidence",
        ),
        UniqueConstraint(
            "review_id",
            "dimension",
            "value_code",
            name="uq_review_profile_labels_review_value",
        ),
        Index(
            "ix_review_profile_labels_dimension_value_review",
            "dimension",
            "value_code",
            "review_id",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("product_reviews.id"), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    value_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_label: Mapped[str] = mapped_column(String(120), nullable=False)
    mapping_source: Mapped[str] = mapped_column(String(40), nullable=False)
    mapping_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductReviewMetric(Base):
    __tablename__ = "product_review_metrics"
    __table_args__ = (
        CheckConstraint(
            "review_count >= 0 and rating_count >= 0 and general_review_count >= 0 "
            "and month_use_review_count >= 0 and repurchase_known_count >= 0 "
            "and repurchase_review_count >= 0 and profile_labeled_review_count >= 0 "
            "and source_photo_marker_count >= 0 and helpful_count_sum >= 0",
            name="ck_review_metrics_counts",
        ),
        CheckConstraint(
            "rating_1_count >= 0 and rating_2_count >= 0 and rating_3_count >= 0 "
            "and rating_4_count >= 0 and rating_5_count >= 0",
            name="ck_review_metrics_rating_counts",
        ),
        CheckConstraint(
            "(average_rating is null or (average_rating >= 1 and average_rating <= 5)) "
            "and (weighted_average_rating is null or (weighted_average_rating >= 1 and weighted_average_rating <= 5)) "
            "and (bayesian_rating is null or (bayesian_rating >= 1 and bayesian_rating <= 5)) "
            "and (category_prior_rating is null or (category_prior_rating >= 1 and category_prior_rating <= 5)) "
            "and (general_average_rating is null or (general_average_rating >= 1 and general_average_rating <= 5)) "
            "and (month_use_average_rating is null or (month_use_average_rating >= 1 and month_use_average_rating <= 5))",
            name="ck_review_metrics_ratings",
        ),
        CheckConstraint(
            "(repurchase_rate is null or (repurchase_rate >= 0 and repurchase_rate <= 1)) "
            "and (bayesian_repurchase_rate is null or (bayesian_repurchase_rate >= 0 and bayesian_repurchase_rate <= 1)) "
            "and (category_prior_repurchase_rate is null or "
            "(category_prior_repurchase_rate >= 0 and category_prior_repurchase_rate <= 1))",
            name="ck_review_metrics_rates",
        ),
        CheckConstraint(
            "rating_score >= 0 and rating_score <= 1 and repurchase_score >= 0 and repurchase_score <= 1 "
            "and (month_consistency_score is null or "
            "(month_consistency_score >= 0 and month_consistency_score <= 1)) "
            "and confidence >= 0 and confidence <= 1 "
            "and review_quality_score >= 0 and review_quality_score <= 1",
            name="ck_review_metrics_scores",
        ),
        CheckConstraint(
            "weight_sum >= 0 and weight_square_sum >= 0 and rating_effective_sample_size >= 0 "
            "and repurchase_effective_sample_size >= 0 and month_use_effective_sample_size >= 0 "
            "and effective_sample_size >= 0 and prior_strength > 0",
            name="ck_review_metrics_samples",
        ),
        UniqueConstraint("product_id", name="uq_product_review_metrics_product"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_1_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_2_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_3_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_4_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_5_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    weighted_average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    bayesian_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    category_prior_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    general_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    month_use_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    general_average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    month_use_average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    repurchase_known_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    repurchase_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    bayesian_repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    category_prior_repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    profile_labeled_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    source_photo_marker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    helpful_count_sum: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    weight_sum: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0, server_default="0")
    weight_square_sum: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=0,
        server_default="0",
    )
    rating_effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    repurchase_effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    month_use_effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    prior_strength: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("20"),
        server_default="20",
    )
    rating_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    repurchase_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    month_consistency_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    review_quality_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="review_quality_v1",
        server_default="review_quality_v1",
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductReviewSegmentMetric(Base):
    __tablename__ = "product_review_segment_metrics"
    __table_args__ = (
        CheckConstraint(
            f"dimension in ({REVIEW_PROFILE_DIMENSION_VALUES})",
            name="ck_review_segment_metrics_dimension",
        ),
        CheckConstraint(
            "review_count >= 0 and rating_count >= 0 and month_use_review_count >= 0 "
            "and repurchase_known_count >= 0 and repurchase_review_count >= 0",
            name="ck_review_segment_metrics_counts",
        ),
        CheckConstraint(
            "(average_rating is null or (average_rating >= 1 and average_rating <= 5)) "
            "and (weighted_average_rating is null or (weighted_average_rating >= 1 and weighted_average_rating <= 5)) "
            "and (bayesian_rating is null or (bayesian_rating >= 1 and bayesian_rating <= 5)) "
            "and (product_prior_rating is null or (product_prior_rating >= 1 and product_prior_rating <= 5))",
            name="ck_review_segment_metrics_ratings",
        ),
        CheckConstraint(
            "(repurchase_rate is null or (repurchase_rate >= 0 and repurchase_rate <= 1)) "
            "and (bayesian_repurchase_rate is null or (bayesian_repurchase_rate >= 0 and bayesian_repurchase_rate <= 1)) "
            "and (product_prior_repurchase_rate is null or "
            "(product_prior_repurchase_rate >= 0 and product_prior_repurchase_rate <= 1))",
            name="ck_review_segment_metrics_rates",
        ),
        CheckConstraint(
            "rating_affinity_score >= 0 and rating_affinity_score <= 1 "
            "and repurchase_affinity_score >= 0 and repurchase_affinity_score <= 1 "
            "and total_affinity_score >= 0 and total_affinity_score <= 1 "
            "and confidence >= 0 and confidence <= 1",
            name="ck_review_segment_metrics_scores",
        ),
        CheckConstraint(
            "weight_sum >= 0 and weight_square_sum >= 0 and effective_sample_size >= 0 "
            "and rating_effective_sample_size >= 0 and repurchase_effective_sample_size >= 0",
            name="ck_review_segment_metrics_samples",
        ),
        UniqueConstraint(
            "product_id",
            "dimension",
            "value_code",
            name="uq_review_segment_metrics_product_value",
        ),
        Index(
            "ix_review_segment_metrics_dimension_value_product",
            "dimension",
            "value_code",
            "product_id",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    value_code: Mapped[str] = mapped_column(String(64), nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    month_use_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    repurchase_known_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    repurchase_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    weighted_average_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    bayesian_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    product_prior_rating: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    bayesian_repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    product_prior_repurchase_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    weight_sum: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0, server_default="0")
    weight_square_sum: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=0,
        server_default="0",
    )
    effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    rating_effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    repurchase_effective_sample_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    rating_affinity_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    repurchase_affinity_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    total_affinity_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=Decimal("0.5"),
        server_default="0.5",
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(7, 6),
        nullable=False,
        default=0,
        server_default="0",
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="review_quality_v1",
        server_default="review_quality_v1",
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
