from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class RecommendationRun(Base):
    __tablename__ = "recommendation_runs"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    concern_text: Mapped[str] = mapped_column(Text, nullable=False)
    skin_type: Mapped[str] = mapped_column(String(40), nullable=False, default="중성", server_default="중성")
    sensitivity: Mapped[str] = mapped_column(String(40), nullable=False, default="보통", server_default="보통")
    avoid_ingredients: Mapped[dict | list | None] = mapped_column(jsonb_type(), nullable=True)
    request_context: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    parser_result: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v0", server_default="v0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecommendationRunConcern(Base):
    __tablename__ = "recommendation_run_concerns"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_run_id",
            "concern_id",
            name="uq_recommendation_run_concerns_run_concern",
        ),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id"),
        nullable=False,
        index=True,
    )
    concern_id: Mapped[int] = mapped_column(ForeignKey("concerns.id"), nullable=False, index=True)
    matched_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class RecommendationRunConstraint(Base):
    __tablename__ = "recommendation_run_constraints"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id"),
        nullable=False,
        index=True,
    )
    constraint_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operator: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("product_categories.id"), nullable=True, index=True)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_hard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class SearchCandidate(Base):
    __tablename__ = "search_candidates"
    __table_args__ = (
        UniqueConstraint("recommendation_run_id", "product_id", name="uq_search_candidates_run_product"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    keyword_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=0, server_default="0.0")
    vector_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=0, server_default="0.0")
    search_match_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        nullable=False,
        default=0,
        server_default="0.0",
    )
    rank_order: Mapped[int | None] = mapped_column(nullable=True)


class RecommendationResult(Base):
    __tablename__ = "recommendation_results"
    __table_args__ = (
        UniqueConstraint("recommendation_run_id", "product_id", name="uq_recommendation_results_run_product"),
        UniqueConstraint("recommendation_run_id", "rank_order", name="uq_recommendation_results_run_rank"),
    )

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_run_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_runs.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    rank_order: Mapped[int] = mapped_column(nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown: Mapped[dict | None] = mapped_column(jsonb_type(), nullable=True)


class RecommendationScoreEvidence(Base):
    __tablename__ = "recommendation_score_evidence"

    id: Mapped[int] = mapped_column(big_integer_pk_type(), primary_key=True, autoincrement=True)
    recommendation_result_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_results.id"),
        nullable=False,
        index=True,
    )
    ingredient_id: Mapped[int | None] = mapped_column(ForeignKey("ingredients.id"), nullable=True, index=True)
    effect_id: Mapped[int | None] = mapped_column(ForeignKey("effects.id"), nullable=True, index=True)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredient_evidence.id"),
        nullable=True,
        index=True,
    )
    contribution_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProductRecommendationFeature(Base):
    __tablename__ = "product_recommendation_features"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        primary_key=True,
    )
    top_ingredient_codes: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    top_effect_codes: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ProductEffectRecommendationFeature(Base):
    __tablename__ = "product_effect_recommendation_features"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        primary_key=True,
    )
    effect_id: Mapped[int] = mapped_column(
        ForeignKey("effects.id"),
        primary_key=True,
    )
    ingredient_effect_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    ingredient_evidence_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    concentration_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    concentration_context: Mapped[dict] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=dict,
        server_default="{}",
    )
    top_ingredient_ids: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    best_evidence_ids: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ProductRecommendationScoringSnapshot(Base):
    __tablename__ = "product_recommendation_scoring_snapshots"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        primary_key=True,
    )
    scoring_payload: Mapped[dict] = mapped_column(jsonb_type(), nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_versions: Mapped[dict] = mapped_column(jsonb_type(), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ProductRecommendationScoringReadModel(Base):
    __tablename__ = "product_recommendation_scoring_read_models"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        primary_key=True,
    )
    top_ingredient_codes: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    top_effect_codes: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    product_feature_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_feature_source_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    functional_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    functional_claims: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    functional_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    functional_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    skin_tags: Mapped[list] = mapped_column(
        jsonb_type(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    dry_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    oily_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    combination_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    normal_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    dehydrated_oily_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sensitive_fit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sensitivity_tag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    skin_profile_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skin_profile_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    popularity_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    popularity_score_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    popularity_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    review_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    review_effective_sample_size: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_score_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    read_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserPreferenceProfile(Base):
    __tablename__ = "user_preference_profiles"
    __table_args__ = (
        CheckConstraint(
            "source in ('wishlist', 'cart', 'purchase', 'recent_view', 'click', 'negative_feedback')",
            name="ck_user_preference_profiles_source",
        ),
        CheckConstraint(
            "event_count >= 0",
            name="ck_user_preference_profiles_event_count_nonnegative",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    category_scores: Mapped[dict] = mapped_column(
        jsonb_type(), nullable=False, default=dict, server_default="{}"
    )
    brand_scores: Mapped[dict] = mapped_column(
        jsonb_type(), nullable=False, default=dict, server_default="{}"
    )
    ingredient_scores: Mapped[dict] = mapped_column(
        jsonb_type(), nullable=False, default=dict, server_default="{}"
    )
    effect_scores: Mapped[dict] = mapped_column(
        jsonb_type(), nullable=False, default=dict, server_default="{}"
    )
    price_band_scores: Mapped[dict] = mapped_column(
        jsonb_type(), nullable=False, default=dict, server_default="{}"
    )
    product_ids: Mapped[list] = mapped_column(
        jsonb_type(), nullable=False, default=list, server_default="[]"
    )
    total_weight: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    effect_top3_sum: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    ingredient_top5_sum: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    category_max: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    brand_max: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    price_band_max: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
