from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationFeature,
    ProductRecommendationScoringSnapshot,
)
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.models.taxonomy import Effect, RiskFlag
from app.services.recommendation_feature_rollup import upsert_rows
from app.services.recommendation_feature_versions import (
    PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
    RECOMMENDATION_SCORING_SNAPSHOT_VERSION,
)
from app.services.recommendation_scoring_snapshot import (
    RecommendationScoringSnapshotPayload,
    SnapshotEffectFeature,
    SnapshotFunctionalInfo,
    SnapshotMarketSignal,
    SnapshotProductFeature,
    SnapshotReviewMetric,
    SnapshotReviewSegment,
    SnapshotRiskFlag,
    SnapshotSkinProfile,
)
from app.services.review_rollup import REVIEW_SCORE_VERSION
from app.services.scoring import (
    MARKET_SIGNAL_WINDOW_DAYS,
    REVIEW_AFFINITY_DIMENSION_WEIGHTS,
)


@dataclass(frozen=True)
class ProductRecommendationScoringSnapshotRollupResult:
    requested_product_count: int
    product_count: int
    snapshot_count: int
    batch_count: int
    computed_at: datetime
    snapshot_version: str = RECOMMENDATION_SCORING_SNAPSHOT_VERSION


@dataclass(frozen=True)
class _BaseSnapshotInput:
    product_feature: SnapshotProductFeature | None
    functional_info: SnapshotFunctionalInfo
    skin_tags: tuple[str, ...]
    skin_profile: SnapshotSkinProfile | None
    market_signal: SnapshotMarketSignal | None
    review_metric: SnapshotReviewMetric | None
    source_versions: dict[str, object]


def rollup_product_recommendation_scoring_snapshots(
    session: Session,
    *,
    product_ids: tuple[int, ...] | None = None,
    batch_size: int = 500,
    computed_at: datetime | None = None,
) -> ProductRecommendationScoringSnapshotRollupResult:
    normalized_batch_size = max(1, int(batch_size))
    normalized_product_ids = _load_target_product_ids(session, product_ids)
    now = computed_at or datetime.now(UTC)
    snapshot_count = 0
    batch_count = 0

    for start in range(0, len(normalized_product_ids), normalized_batch_size):
        batch_count += 1
        batch_product_ids = normalized_product_ids[start : start + normalized_batch_size]
        base_inputs = _load_base_snapshot_inputs(session, batch_product_ids)
        effect_features, effect_versions = _load_effect_features(
            session,
            batch_product_ids,
        )
        risk_flags = _load_risk_flags(session, batch_product_ids)
        review_segments, review_segment_versions = _load_review_segments(
            session,
            batch_product_ids,
        )

        snapshot_rows: list[dict[str, object]] = []
        for product_id in batch_product_ids:
            base = base_inputs[product_id]
            payload = RecommendationScoringSnapshotPayload(
                product_feature=base.product_feature,
                effect_features=effect_features.get(product_id, {}),
                functional_info=base.functional_info,
                skin_tags=base.skin_tags,
                skin_profile=base.skin_profile,
                risk_flags=risk_flags.get(product_id, ()),
                market_signal=base.market_signal,
                review_metric=base.review_metric,
                review_segments=review_segments.get(product_id, ()),
            )
            source_versions = {
                **base.source_versions,
                "effect_features": effect_versions.get(product_id, {}),
                "review_segments": sorted(
                    review_segment_versions.get(product_id, set())
                ),
            }
            snapshot_rows.append(
                {
                    "product_id": product_id,
                    "scoring_payload": payload.to_dict(),
                    "snapshot_version": RECOMMENDATION_SCORING_SNAPSHOT_VERSION,
                    "source_versions": source_versions,
                    "computed_at": now,
                }
            )

        upsert_rows(
            session,
            ProductRecommendationScoringSnapshot,
            snapshot_rows,
            conflict_columns=("product_id",),
            update_columns=(
                "scoring_payload",
                "snapshot_version",
                "source_versions",
                "computed_at",
            ),
        )
        snapshot_count += len(snapshot_rows)
        session.flush()

    return ProductRecommendationScoringSnapshotRollupResult(
        requested_product_count=(
            len(product_ids) if product_ids is not None else len(normalized_product_ids)
        ),
        product_count=len(normalized_product_ids),
        snapshot_count=snapshot_count,
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


def _load_base_snapshot_inputs(
    session: Session,
    product_ids: list[int],
) -> dict[int, _BaseSnapshotInput]:
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
            ProductRecommendationFeature.source_updated_at,
            ProductSkinProfile.product_id.label("skin_profile_product_id"),
            ProductSkinProfile.dry_fit,
            ProductSkinProfile.oily_fit,
            ProductSkinProfile.combination_fit,
            ProductSkinProfile.normal_fit,
            ProductSkinProfile.dehydrated_oily_fit,
            ProductSkinProfile.sensitive_fit,
            ProductSkinProfile.sensitivity_tag,
            ProductSkinProfile.confidence.label("skin_profile_confidence"),
            ProductSkinProfile.reason,
            ProductPopularityMetric.product_id.label("popularity_product_id"),
            ProductPopularityMetric.popularity_score,
            ProductPopularityMetric.score_version.label("popularity_score_version"),
            ProductReviewMetric.product_id.label("review_metric_product_id"),
            ProductReviewMetric.review_quality_score,
            ProductReviewMetric.confidence.label("review_metric_confidence"),
            ProductReviewMetric.effective_sample_size,
            ProductReviewMetric.review_count,
            ProductReviewMetric.score_version.label("review_score_version"),
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
    ).all()

    inputs: dict[int, _BaseSnapshotInput] = {}
    for row in rows:
        product_id = int(row.product_id)
        product_feature_current = bool(
            row.feature_product_id is not None
            and row.product_feature_version
            == PRODUCT_RECOMMENDATION_FEATURE_VERSION
            and _source_is_current(row.source_updated_at, row.product_updated_at)
        )
        product_feature = None
        if product_feature_current:
            product_feature = SnapshotProductFeature(
                top_ingredient_codes=tuple(
                    str(code) for code in row.top_ingredient_codes or ()
                ),
                top_effect_codes=tuple(
                    str(code) for code in row.top_effect_codes or ()
                ),
            )

        skin_profile = None
        if row.skin_profile_product_id is not None:
            skin_profile = SnapshotSkinProfile(
                dry_fit=_to_float(row.dry_fit),
                oily_fit=_to_float(row.oily_fit),
                combination_fit=_to_float(row.combination_fit),
                normal_fit=_to_float(row.normal_fit),
                dehydrated_oily_fit=_to_float(row.dehydrated_oily_fit),
                sensitive_fit=_to_float(row.sensitive_fit),
                sensitivity_tag=row.sensitivity_tag,
                confidence=row.skin_profile_confidence,
                reason=row.reason,
            )

        market_signal = None
        if row.popularity_product_id is not None:
            market_signal = SnapshotMarketSignal(
                popularity_score=_to_float(row.popularity_score),
            )

        review_metric = None
        if (
            row.review_metric_product_id is not None
            and row.review_score_version == REVIEW_SCORE_VERSION
        ):
            review_metric = SnapshotReviewMetric(
                review_quality_score=_to_float(row.review_quality_score),
                confidence=_to_float(row.review_metric_confidence),
                effective_sample_size=_to_float(row.effective_sample_size),
                review_count=int(row.review_count),
            )

        inputs[product_id] = _BaseSnapshotInput(
            product_feature=product_feature,
            functional_info=SnapshotFunctionalInfo(
                status=row.functional_cosmetic_status,
                claims=_split_tags(row.functional_cosmetic_claims),
                claim_confidence=row.functional_claim_confidence,
                basis=row.functional_claim_basis,
            ),
            skin_tags=_split_tags(row.skin_type_tags),
            skin_profile=skin_profile,
            market_signal=market_signal,
            review_metric=review_metric,
            source_versions={
                "product_feature": {
                    "feature_version": row.product_feature_version,
                    "source_current": product_feature_current,
                },
                "review_metric": row.review_score_version,
                "market_signal": {
                    "window_days": MARKET_SIGNAL_WINDOW_DAYS,
                    "score_version": row.popularity_score_version,
                },
            },
        )
    return inputs


def _load_effect_features(
    session: Session,
    product_ids: list[int],
) -> tuple[
    dict[int, dict[str, SnapshotEffectFeature]],
    dict[int, dict[str, str]],
]:
    rows = session.execute(
        select(
            ProductEffectRecommendationFeature,
            Effect.effect_code,
        )
        .join(Effect, ProductEffectRecommendationFeature.effect_id == Effect.id)
        .where(ProductEffectRecommendationFeature.product_id.in_(product_ids))
    ).all()
    features: dict[int, dict[str, SnapshotEffectFeature]] = {}
    versions: dict[int, dict[str, str]] = {}
    for row, effect_code_value in rows:
        product_id = int(row.product_id)
        effect_code = str(effect_code_value)
        versions.setdefault(product_id, {})[effect_code] = str(row.feature_version)
        if row.feature_version != PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION:
            continue
        features.setdefault(product_id, {})[effect_code] = SnapshotEffectFeature(
            ingredient_effect_score=_to_float(row.ingredient_effect_score),
            ingredient_evidence_score=_to_float(row.ingredient_evidence_score),
            concentration_score=_to_float(row.concentration_score),
            concentration_context=dict(row.concentration_context or {}),
            top_ingredient_ids=tuple(
                int(ingredient_id) for ingredient_id in row.top_ingredient_ids or ()
            ),
            best_evidence_ids=tuple(
                int(evidence_id) for evidence_id in row.best_evidence_ids or ()
            ),
        )
    return features, versions


def _load_risk_flags(
    session: Session,
    product_ids: list[int],
) -> dict[int, tuple[SnapshotRiskFlag, ...]]:
    rows = session.execute(
        select(
            ProductIngredient.product_id,
            RiskFlag.risk_type,
            RiskFlag.display_text,
            RiskFlag.severity,
            RiskFlag.severity_score,
            RiskFlag.applies_to,
        )
        .join(RiskFlag, RiskFlag.ingredient_id == ProductIngredient.ingredient_id)
        .where(ProductIngredient.product_id.in_(product_ids))
    ).all()
    by_product: dict[int, list[SnapshotRiskFlag]] = {}
    for product_id, risk_type, display_text, severity, severity_score, applies_to in rows:
        by_product.setdefault(int(product_id), []).append(
            SnapshotRiskFlag(
                risk_type=str(risk_type),
                display_text=str(display_text),
                severity=str(severity),
                severity_score=_to_optional_float(severity_score),
                applies_to=applies_to,
            )
        )
    return {
        product_id: tuple(flags)
        for product_id, flags in by_product.items()
    }


def _load_review_segments(
    session: Session,
    product_ids: list[int],
) -> tuple[
    dict[int, tuple[SnapshotReviewSegment, ...]],
    dict[int, set[str]],
]:
    rows = session.execute(
        select(ProductReviewSegmentMetric).where(
            ProductReviewSegmentMetric.product_id.in_(product_ids),
            ProductReviewSegmentMetric.dimension.in_(
                REVIEW_AFFINITY_DIMENSION_WEIGHTS
            ),
        )
    ).scalars()
    by_product: dict[int, list[SnapshotReviewSegment]] = {}
    versions: dict[int, set[str]] = {}
    for row in rows:
        product_id = int(row.product_id)
        versions.setdefault(product_id, set()).add(str(row.score_version))
        if row.score_version != REVIEW_SCORE_VERSION:
            continue
        by_product.setdefault(product_id, []).append(
            SnapshotReviewSegment(
                dimension=str(row.dimension),
                value_code=str(row.value_code),
                total_affinity_score=_to_float(row.total_affinity_score),
                effective_sample_size=_to_float(row.effective_sample_size),
                review_count=int(row.review_count),
            )
        )
    return (
        {
            product_id: tuple(segments)
            for product_id, segments in by_product.items()
        },
        versions,
    )


def _source_is_current(
    source_updated_at: datetime | None,
    product_updated_at: datetime | None,
) -> bool:
    if source_updated_at is None or product_updated_at is None:
        return False
    return _normalized_datetime(source_updated_at) >= _normalized_datetime(
        product_updated_at
    )


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _split_tags(raw_tags: str | None) -> tuple[str, ...]:
    if not raw_tags:
        return ()
    normalized = raw_tags.replace(",", ";").replace("/", ";")
    return tuple(tag.strip() for tag in normalized.split(";") if tag.strip())


def _to_float(value: Decimal | int | float | None) -> float:
    return float(value) if value is not None else 0.0


def _to_optional_float(value: Decimal | int | float | None) -> float | None:
    return float(value) if value is not None else None
