from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Product,
    ProductImage,
    ProductIngredient,
    ProductPrice,
    ProductSkinProfile,
)
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationCoarseFeature,
    ProductRecommendationFeature,
)
from app.db.models.taxonomy import Effect, IngredientEffect, IngredientEvidence
from app.services.recommendation_feature_rollup import upsert_rows
from app.services.recommendation_feature_versions import (
    PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
)


SCORE_SCALE = 10_000
HOME_POPULARITY_WINDOW_DAYS = 7
HOME_SHORTLIST_EVIDENCE_WEIGHT = 0.50
HOME_SHORTLIST_EFFECT_WEIGHT = 0.25
HOME_SHORTLIST_POPULARITY_WEIGHT = 0.15
HOME_SHORTLIST_OLIVEYOUNG_WEIGHT = 0.10
EFFECT_COLUMN_PREFIXES = {
    "effect_acne_sebum": "acne_sebum",
    "effect_brightening": "brightening",
    "effect_calming": "calming",
    "effect_exfoliation": "exfoliation",
    "effect_moisture_barrier": "moisture_barrier",
    "effect_wrinkle": "wrinkle",
}
EFFECT_SCORE_COLUMNS = tuple(
    column
    for prefix in EFFECT_COLUMN_PREFIXES.values()
    for column in (f"{prefix}_effect_score", f"{prefix}_evidence_score")
)
CONFIDENCE_CODES = {
    "low": 1,
    "medium": 2,
    "med": 2,
    "high": 3,
}


@dataclass(frozen=True)
class ProductRecommendationCoarseFeatureRollupResult:
    requested_product_count: int
    product_count: int
    coarse_feature_count: int
    source_current_count: int
    batch_count: int
    computed_at: datetime
    feature_version: str = PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION


def rollup_product_recommendation_coarse_features(
    session: Session,
    *,
    product_ids: tuple[int, ...] | None = None,
    batch_size: int = 500,
    computed_at: datetime | None = None,
) -> ProductRecommendationCoarseFeatureRollupResult:
    normalized_batch_size = max(1, int(batch_size))
    normalized_product_ids = _load_target_product_ids(session, product_ids)
    now = computed_at or datetime.now(UTC)
    coarse_feature_count = 0
    source_current_count = 0
    batch_count = 0

    for start in range(0, len(normalized_product_ids), normalized_batch_size):
        batch_count += 1
        batch_product_ids = normalized_product_ids[start : start + normalized_batch_size]
        rows = load_product_recommendation_coarse_feature_source_rows(
            session,
            batch_product_ids,
            computed_at=now,
        )
        upsert_rows(
            session,
            ProductRecommendationCoarseFeature,
            rows,
            conflict_columns=("product_id",),
            update_columns=tuple(
                column.name
                for column in ProductRecommendationCoarseFeature.__table__.columns
                if column.name != "product_id"
            ),
        )
        coarse_feature_count += len(rows)
        source_current_count += sum(bool(row["source_current"]) for row in rows)
        session.flush()

    return ProductRecommendationCoarseFeatureRollupResult(
        requested_product_count=(
            len(product_ids) if product_ids is not None else len(normalized_product_ids)
        ),
        product_count=len(normalized_product_ids),
        coarse_feature_count=coarse_feature_count,
        source_current_count=source_current_count,
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


def load_product_recommendation_coarse_feature_source_rows(
    session: Session,
    product_ids: list[int],
    *,
    computed_at: datetime,
) -> list[dict[str, object]]:
    if not product_ids:
        return []

    home_signal_scores_by_product = _load_home_signal_scores(session, product_ids)
    home_summaries_by_product = _load_home_product_summaries(session, product_ids)
    source_rows = session.execute(
        select(
            Product.id.label("product_id"),
            Product.updated_at.label("product_updated_at"),
            ProductRecommendationFeature.product_id.label("feature_product_id"),
            ProductRecommendationFeature.feature_version.label("product_feature_version"),
            ProductRecommendationFeature.source_updated_at.label("product_feature_source_updated_at"),
            ProductRecommendationFeature.computed_at.label("product_feature_computed_at"),
            ProductSkinProfile.product_id.label("skin_profile_product_id"),
            ProductSkinProfile.dry_fit,
            ProductSkinProfile.oily_fit,
            ProductSkinProfile.combination_fit,
            ProductSkinProfile.normal_fit,
            ProductSkinProfile.dehydrated_oily_fit,
            ProductSkinProfile.sensitive_fit,
            ProductSkinProfile.confidence.label("skin_profile_confidence"),
            Effect.effect_code,
            ProductEffectRecommendationFeature.ingredient_effect_score,
            ProductEffectRecommendationFeature.ingredient_evidence_score,
            ProductEffectRecommendationFeature.feature_version.label("effect_feature_version"),
            ProductEffectRecommendationFeature.computed_at.label("effect_feature_computed_at"),
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
            ProductEffectRecommendationFeature,
            ProductEffectRecommendationFeature.product_id == Product.id,
        )
        .outerjoin(
            Effect,
            Effect.id == ProductEffectRecommendationFeature.effect_id,
        )
        .where(Product.id.in_(product_ids))
        .order_by(Product.id.asc())
    ).all()

    rows_by_product: dict[int, dict[str, object]] = {}
    current_by_product: dict[int, bool] = {}
    source_times_by_product: dict[int, list[datetime]] = {}
    for source in source_rows:
        product_id = int(source.product_id)
        if product_id not in rows_by_product:
            skin_profile_exists = source.skin_profile_product_id is not None
            home_effect_score, home_evidence_score = home_signal_scores_by_product.get(
                product_id,
                (0, 0),
            )
            (
                home_lowest_price,
                home_has_image,
                home_oliveyoung_available,
                home_popularity_score,
            ) = home_summaries_by_product.get(product_id, (0, False, False, 0))
            row: dict[str, object] = {
                "product_id": product_id,
                **{column: 0 for column in EFFECT_SCORE_COLUMNS},
                "dry_fit": _scaled_optional(source.dry_fit) if skin_profile_exists else None,
                "oily_fit": _scaled_optional(source.oily_fit) if skin_profile_exists else None,
                "combination_fit": (
                    _scaled_optional(source.combination_fit) if skin_profile_exists else None
                ),
                "normal_fit": _scaled_optional(source.normal_fit) if skin_profile_exists else None,
                "dehydrated_oily_fit": (
                    _scaled_optional(source.dehydrated_oily_fit)
                    if skin_profile_exists
                    else None
                ),
                "sensitive_fit": (
                    _scaled_optional(source.sensitive_fit) if skin_profile_exists else None
                ),
                "skin_profile_confidence_code": _confidence_code(
                    source.skin_profile_confidence if skin_profile_exists else None
                ),
                "home_max_effect_score": home_effect_score,
                "home_max_evidence_score": home_evidence_score,
                "home_lowest_price": home_lowest_price,
                "home_has_image": home_has_image,
                "home_oliveyoung_available": home_oliveyoung_available,
                "home_popularity_score": home_popularity_score,
                "home_shortlist_score": _home_shortlist_score(
                    evidence_score=home_evidence_score,
                    effect_score=home_effect_score,
                    popularity_score=home_popularity_score,
                    oliveyoung_available=home_oliveyoung_available,
                ),
                "home_source_current": False,
                "source_current": False,
                "feature_version": PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
                "source_updated_at": _latest_datetime(
                    source.product_updated_at,
                    source.product_feature_source_updated_at,
                    source.product_feature_computed_at,
                ),
                "computed_at": computed_at,
            }
            rows_by_product[product_id] = row
            current_by_product[product_id] = bool(
                source.feature_product_id is not None
                and source.product_feature_version == PRODUCT_RECOMMENDATION_FEATURE_VERSION
                and _source_is_current(
                    source.product_feature_source_updated_at,
                    source.product_updated_at,
                )
            )
            source_times_by_product[product_id] = [
                value
                for value in (
                    source.product_updated_at,
                    source.product_feature_source_updated_at,
                    source.product_feature_computed_at,
                )
                if value is not None
            ]

        if source.effect_feature_computed_at is not None:
            source_times_by_product[product_id].append(source.effect_feature_computed_at)
        if (
            source.effect_feature_version is not None
            and source.effect_feature_version
            != PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION
        ):
            current_by_product[product_id] = False

        prefix = EFFECT_COLUMN_PREFIXES.get(str(source.effect_code or ""))
        if prefix is None:
            continue
        rows_by_product[product_id][f"{prefix}_effect_score"] = _scaled_score(
            source.ingredient_effect_score
        )
        rows_by_product[product_id][f"{prefix}_evidence_score"] = _scaled_score(
            source.ingredient_evidence_score
        )

    for product_id, row in rows_by_product.items():
        row["source_current"] = current_by_product[product_id]
        row["home_source_current"] = current_by_product[product_id]
        row["source_updated_at"] = _latest_datetime(
            *source_times_by_product[product_id]
        )
    return [rows_by_product[product_id] for product_id in sorted(rows_by_product)]


def _load_home_signal_scores(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[int, int]]:
    rows = session.execute(
        select(
            ProductIngredient.product_id,
            func.max(IngredientEffect.effect_score).label("max_effect_score"),
            func.max(IngredientEvidence.evidence_score).label("max_evidence_score"),
        )
        .outerjoin(
            IngredientEffect,
            IngredientEffect.ingredient_id == ProductIngredient.ingredient_id,
        )
        .outerjoin(
            IngredientEvidence,
            and_(
                IngredientEvidence.ingredient_id == ProductIngredient.ingredient_id,
                IngredientEvidence.effect_id == IngredientEffect.effect_id,
            ),
        )
        .where(ProductIngredient.product_id.in_(product_ids))
        .group_by(ProductIngredient.product_id)
    ).all()
    return {
        int(row.product_id): (
            _scaled_home_score(row.max_effect_score),
            _scaled_home_score(row.max_evidence_score),
        )
        for row in rows
    }


def _load_home_product_summaries(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[int, bool, bool, int]]:
    lowest_price = (
        select(func.min(ProductPrice.price))
        .where(ProductPrice.product_id == Product.id)
        .scalar_subquery()
    )
    has_image = (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id)
        .exists()
    )
    has_oliveyoung_offer = (
        select(ProductPrice.id)
        .where(
            ProductPrice.product_id == Product.id,
            or_(
                ProductPrice.mall_name.like("%올리브영%"),
                func.lower(ProductPrice.mall_name).like("%oliveyoung%"),
            ),
        )
        .exists()
    )
    rows = session.execute(
        select(
            Product.id,
            lowest_price.label("lowest_price"),
            has_image.label("has_image"),
            has_oliveyoung_offer.label("has_oliveyoung_offer"),
            ProductPopularityMetric.popularity_score.label("popularity_score"),
        )
        .outerjoin(
            ProductPopularityMetric,
            and_(
                ProductPopularityMetric.product_id == Product.id,
                ProductPopularityMetric.window_days == HOME_POPULARITY_WINDOW_DAYS,
            ),
        )
        .where(Product.id.in_(product_ids))
    ).all()
    return {
        int(row.id): (
            int(row.lowest_price or 0),
            bool(row.has_image),
            bool(row.has_oliveyoung_offer),
            _scaled_home_score(row.popularity_score),
        )
        for row in rows
    }


def _home_shortlist_score(
    *,
    evidence_score: int,
    effect_score: int,
    popularity_score: int,
    oliveyoung_available: bool,
) -> int:
    oliveyoung_score = SCORE_SCALE if oliveyoung_available else 0
    return int(
        round(
            evidence_score * HOME_SHORTLIST_EVIDENCE_WEIGHT
            + effect_score * HOME_SHORTLIST_EFFECT_WEIGHT
            + popularity_score * HOME_SHORTLIST_POPULARITY_WEIGHT
            + oliveyoung_score * HOME_SHORTLIST_OLIVEYOUNG_WEIGHT
        )
    )


def _scaled_score(value: Decimal | float | int | None) -> int:
    normalized = max(0.0, min(1.0, float(value or 0.0)))
    return int(round(normalized * SCORE_SCALE))


def _scaled_home_score(value: Decimal | float | int | None) -> int:
    normalized = float(value or 0.0)
    if normalized > 1:
        normalized /= 100
    normalized = max(0.0, min(1.0, normalized))
    return int(round(normalized * SCORE_SCALE))


def _scaled_optional(value: Decimal | float | int | None) -> int | None:
    if value is None:
        return None
    return _scaled_score(value)


def _confidence_code(value: str | None) -> int:
    normalized = value.strip().casefold() if value else ""
    return CONFIDENCE_CODES.get(normalized, 0)


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
    return max(normalized) if normalized else datetime.now(UTC)


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
