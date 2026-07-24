from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product
from app.db.models.recommendation import (
    HomeEvidencePickFeature,
    ProductRecommendationCoarseFeature,
)
from app.services.recommendation_feature_rollup import upsert_rows
from app.services.recommendation_feature_versions import (
    HOME_EVIDENCE_PICK_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
)


@dataclass(frozen=True)
class HomeEvidencePickFeatureRollupResult:
    requested_product_count: int
    product_count: int
    evidence_pick_feature_count: int
    source_current_count: int
    batch_count: int
    computed_at: datetime
    feature_version: str = HOME_EVIDENCE_PICK_FEATURE_VERSION


def rollup_home_evidence_pick_features(
    session: Session,
    *,
    product_ids: tuple[int, ...] | None = None,
    batch_size: int = 500,
    computed_at: datetime | None = None,
) -> HomeEvidencePickFeatureRollupResult:
    normalized_ids = _load_target_product_ids(session, product_ids)
    normalized_batch_size = max(1, int(batch_size))
    now = computed_at or datetime.now(UTC)
    feature_count = 0
    source_current_count = 0
    batch_count = 0

    for start in range(0, len(normalized_ids), normalized_batch_size):
        batch_count += 1
        batch_ids = normalized_ids[start : start + normalized_batch_size]
        rows = load_home_evidence_pick_feature_source_rows(
            session,
            batch_ids,
            computed_at=now,
        )
        upsert_rows(
            session,
            HomeEvidencePickFeature,
            rows,
            conflict_columns=("product_id",),
            update_columns=tuple(
                column.name
                for column in HomeEvidencePickFeature.__table__.columns
                if column.name != "product_id"
            ),
        )
        feature_count += len(rows)
        source_current_count += sum(bool(row["source_current"]) for row in rows)
        session.flush()

    return HomeEvidencePickFeatureRollupResult(
        requested_product_count=len(product_ids) if product_ids is not None else len(normalized_ids),
        product_count=len(normalized_ids),
        evidence_pick_feature_count=feature_count,
        source_current_count=source_current_count,
        batch_count=batch_count,
        computed_at=now,
    )


def load_home_evidence_pick_feature_source_rows(
    session: Session,
    product_ids: list[int],
    *,
    computed_at: datetime,
) -> list[dict[str, object]]:
    if not product_ids:
        return []

    rows = session.execute(
        select(
            ProductRecommendationCoarseFeature.product_id,
            ProductRecommendationCoarseFeature.home_max_evidence_score,
            ProductRecommendationCoarseFeature.home_max_effect_score,
            ProductRecommendationCoarseFeature.home_lowest_price,
            ProductRecommendationCoarseFeature.source_current,
            ProductRecommendationCoarseFeature.home_source_current,
            ProductRecommendationCoarseFeature.feature_version,
            ProductRecommendationCoarseFeature.source_updated_at,
        ).where(ProductRecommendationCoarseFeature.product_id.in_(product_ids))
    ).all()
    return [
        {
            "product_id": int(row.product_id),
            "max_evidence_score": int(row.home_max_evidence_score or 0),
            "max_effect_score": int(row.home_max_effect_score or 0),
            "lowest_price": int(row.home_lowest_price or 0),
            "source_current": bool(
                row.source_current
                and row.home_source_current
                and row.feature_version == PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION
            ),
            "feature_version": HOME_EVIDENCE_PICK_FEATURE_VERSION,
            "source_updated_at": row.source_updated_at,
            "computed_at": computed_at,
        }
        for row in rows
    ]


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
