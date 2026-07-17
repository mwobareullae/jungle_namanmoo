from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductSkinProfile
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import (
    ProductRecommendationFeature,
    ProductRecommendationScoringReadModel,
)
from app.db.models.review import ProductReviewMetric
from app.services.recommendation_feature_rollup import upsert_rows
from app.services.recommendation_feature_versions import (
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_SCORING_READ_MODEL_VERSION,
)
from app.services.review_rollup import REVIEW_SCORE_VERSION
from app.services.scoring import MARKET_SIGNAL_WINDOW_DAYS


@dataclass(frozen=True)
class ProductRecommendationScoringReadModelRollupResult:
    requested_product_count: int
    product_count: int
    read_model_count: int
    batch_count: int
    computed_at: datetime
    read_model_version: str = PRODUCT_RECOMMENDATION_SCORING_READ_MODEL_VERSION


def rollup_product_recommendation_scoring_read_models(
    session: Session,
    *,
    product_ids: tuple[int, ...] | None = None,
    batch_size: int = 500,
    computed_at: datetime | None = None,
) -> ProductRecommendationScoringReadModelRollupResult:
    normalized_batch_size = max(1, int(batch_size))
    normalized_product_ids = _load_target_product_ids(session, product_ids)
    now = computed_at or datetime.now(UTC)
    read_model_count = 0
    batch_count = 0

    for start in range(0, len(normalized_product_ids), normalized_batch_size):
        batch_count += 1
        batch_product_ids = normalized_product_ids[start : start + normalized_batch_size]
        rows = _load_read_model_rows(session, batch_product_ids, computed_at=now)
        upsert_rows(
            session,
            ProductRecommendationScoringReadModel,
            rows,
            conflict_columns=("product_id",),
            update_columns=tuple(
                column.name
                for column in ProductRecommendationScoringReadModel.__table__.columns
                if column.name != "product_id"
            ),
        )
        read_model_count += len(rows)
        session.flush()

    return ProductRecommendationScoringReadModelRollupResult(
        requested_product_count=(
            len(product_ids) if product_ids is not None else len(normalized_product_ids)
        ),
        product_count=len(normalized_product_ids),
        read_model_count=read_model_count,
        batch_count=batch_count,
        computed_at=now,
    )


def _load_target_product_ids(
    session: Session,
    product_ids: tuple[int, ...] | None,
) -> list[int]:
    statement = select(Product.id).order_by(Product.id.asc())
    if product_ids is not None:
        normalized_ids = sorted({int(product_id) for product_id in product_ids})
        if not normalized_ids:
            return []
        statement = statement.where(Product.id.in_(normalized_ids))
    return [int(product_id) for product_id in session.execute(statement).scalars()]


def _load_read_model_rows(
    session: Session,
    product_ids: list[int],
    *,
    computed_at: datetime,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            Product.id.label("product_id"),
            Product.updated_at.label("product_updated_at"),
            Product.functional_cosmetic_status,
            Product.functional_cosmetic_claims,
            Product.functional_claim_confidence,
            Product.functional_claim_basis,
            Product.skin_type_tags,
            ProductRecommendationFeature.product_id.label("feature_product_id"),
            ProductRecommendationFeature.top_ingredient_codes,
            ProductRecommendationFeature.top_effect_codes,
            ProductRecommendationFeature.feature_version.label(
                "product_feature_version"
            ),
            ProductRecommendationFeature.source_updated_at.label(
                "product_feature_source_updated_at"
            ),
            ProductRecommendationFeature.computed_at.label(
                "product_feature_computed_at"
            ),
            ProductSkinProfile.product_id.label("skin_profile_product_id"),
            ProductSkinProfile.dry_fit,
            ProductSkinProfile.oily_fit,
            ProductSkinProfile.combination_fit,
            ProductSkinProfile.normal_fit,
            ProductSkinProfile.dehydrated_oily_fit,
            ProductSkinProfile.sensitive_fit,
            ProductSkinProfile.sensitivity_tag,
            ProductSkinProfile.confidence.label("skin_profile_confidence"),
            ProductSkinProfile.reason.label("skin_profile_reason"),
            ProductPopularityMetric.product_id.label("popularity_product_id"),
            ProductPopularityMetric.popularity_score,
            ProductPopularityMetric.score_version.label("popularity_score_version"),
            ProductPopularityMetric.updated_at.label("popularity_updated_at"),
            ProductReviewMetric.product_id.label("review_metric_product_id"),
            ProductReviewMetric.review_quality_score,
            ProductReviewMetric.confidence.label("review_confidence"),
            ProductReviewMetric.effective_sample_size.label(
                "review_effective_sample_size"
            ),
            ProductReviewMetric.review_count,
            ProductReviewMetric.score_version.label("review_score_version"),
            ProductReviewMetric.updated_at.label("review_updated_at"),
        )
        .outerjoin(
            ProductRecommendationFeature,
            ProductRecommendationFeature.product_id == Product.id,
        )
        .outerjoin(
            ProductSkinProfile,
            ProductSkinProfile.product_id == Product.id,
        )
        .outerjoin(
            ProductPopularityMetric,
            and_(
                ProductPopularityMetric.product_id == Product.id,
                ProductPopularityMetric.window_days == MARKET_SIGNAL_WINDOW_DAYS,
            ),
        )
        .outerjoin(
            ProductReviewMetric,
            ProductReviewMetric.product_id == Product.id,
        )
        .where(Product.id.in_(product_ids))
        .order_by(Product.id.asc())
    ).all()

    read_model_rows: list[dict[str, object]] = []
    for row in rows:
        product_feature_source_current = bool(
            row.feature_product_id is not None
            and row.product_feature_version == PRODUCT_RECOMMENDATION_FEATURE_VERSION
            and _source_is_current(
                row.product_feature_source_updated_at,
                row.product_updated_at,
            )
        )
        skin_profile_exists = row.skin_profile_product_id is not None
        popularity_exists = row.popularity_product_id is not None
        review_metric_exists = row.review_metric_product_id is not None
        source_updated_at = _latest_datetime(
            row.product_updated_at,
            row.product_feature_source_updated_at,
            row.product_feature_computed_at,
            row.popularity_updated_at,
            row.review_updated_at,
        )
        read_model_rows.append(
            {
                "product_id": int(row.product_id),
                "top_ingredient_codes": list(row.top_ingredient_codes or ()),
                "top_effect_codes": list(row.top_effect_codes or ()),
                "product_feature_version": row.product_feature_version,
                "product_feature_source_current": product_feature_source_current,
                "functional_status": row.functional_cosmetic_status,
                "functional_claims": list(_split_tags(row.functional_cosmetic_claims)),
                "functional_confidence": row.functional_claim_confidence,
                "functional_basis": row.functional_claim_basis,
                "skin_tags": list(_split_tags(row.skin_type_tags)),
                "dry_fit": row.dry_fit if skin_profile_exists else None,
                "oily_fit": row.oily_fit if skin_profile_exists else None,
                "combination_fit": row.combination_fit if skin_profile_exists else None,
                "normal_fit": row.normal_fit if skin_profile_exists else None,
                "dehydrated_oily_fit": (
                    row.dehydrated_oily_fit if skin_profile_exists else None
                ),
                "sensitive_fit": row.sensitive_fit if skin_profile_exists else None,
                "sensitivity_tag": row.sensitivity_tag if skin_profile_exists else None,
                "skin_profile_confidence": (
                    row.skin_profile_confidence if skin_profile_exists else None
                ),
                "skin_profile_reason": (
                    row.skin_profile_reason if skin_profile_exists else None
                ),
                "popularity_score": (
                    row.popularity_score if popularity_exists else None
                ),
                "popularity_score_version": (
                    row.popularity_score_version if popularity_exists else None
                ),
                "popularity_window_days": (
                    MARKET_SIGNAL_WINDOW_DAYS if popularity_exists else None
                ),
                "review_quality_score": (
                    row.review_quality_score if review_metric_exists else None
                ),
                "review_confidence": (
                    row.review_confidence if review_metric_exists else None
                ),
                "review_effective_sample_size": (
                    row.review_effective_sample_size if review_metric_exists else None
                ),
                "review_count": row.review_count if review_metric_exists else None,
                "review_score_version": (
                    row.review_score_version if review_metric_exists else None
                ),
                "read_model_version": (
                    PRODUCT_RECOMMENDATION_SCORING_READ_MODEL_VERSION
                ),
                "source_updated_at": source_updated_at,
                "computed_at": computed_at,
            }
        )
    return read_model_rows


def _source_is_current(
    source_updated_at: datetime | None,
    product_updated_at: datetime | None,
) -> bool:
    if source_updated_at is None or product_updated_at is None:
        return False
    return _normalized_datetime(source_updated_at) >= _normalized_datetime(
        product_updated_at
    )


def _latest_datetime(*values: datetime | None) -> datetime:
    normalized = [
        _normalized_datetime(value)
        for value in values
        if value is not None
    ]
    if not normalized:
        return datetime.now(UTC)
    return max(normalized)


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _split_tags(raw_tags: str | None) -> tuple[str, ...]:
    if not raw_tags:
        return ()
    normalized = raw_tags.replace(",", ";").replace("/", ";")
    return tuple(tag.strip() for tag in normalized.split(";") if tag.strip())
