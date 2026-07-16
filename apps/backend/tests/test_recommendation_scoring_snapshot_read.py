from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product, ProductSkinProfile
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationScoringSnapshot,
)
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.models.taxonomy import RiskFlag
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_scoring_snapshot_rollup import (
    rollup_product_recommendation_scoring_snapshots,
)
from app.services.repository import load_repository
from app.services.review_rollup import REVIEW_SCORE_VERSION
from app.services import scoring
from app.services.scoring import score_candidates
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_snapshot_all_hits_preserve_complete_scoring_output() -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
    )
    rollup_product_recommendation_scoring_snapshots(session)
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert diagnostics["scoring_snapshot_hit_count"] == 2
    assert diagnostics["scoring_snapshot_miss_count"] == 0
    assert diagnostics["scoring_snapshot_parse_error_count"] == 0
    assert diagnostics["scoring_snapshot_fallback_ms"] == 0.0


def test_snapshot_partial_miss_falls_back_for_only_missing_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(session, intent, candidates, matches)
    rollup_product_recommendation_scoring_snapshots(session)
    missing_product_id = candidates[0].db_product_id
    session.execute(
        delete(ProductRecommendationScoringSnapshot).where(
            ProductRecommendationScoringSnapshot.product_id == missing_product_id
        )
    )
    session.commit()
    fallback_product_ids: list[int] = []
    original_loader = scoring._load_candidate_scoring_bundles

    def capture_fallback(session_arg, fallback_candidates):
        fallback_product_ids.extend(
            candidate.db_product_id for candidate in fallback_candidates
        )
        return original_loader(session_arg, fallback_candidates)

    monkeypatch.setattr(
        scoring,
        "_load_candidate_scoring_bundles",
        capture_fallback,
    )
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert fallback_product_ids == [missing_product_id]
    assert diagnostics["scoring_snapshot_hit_count"] == 1
    assert diagnostics["scoring_snapshot_miss_count"] == 1
    assert diagnostics["scoring_snapshot_parse_error_count"] == 0
    assert diagnostics["scoring_snapshot_fallback_ms"] >= 0.0


def test_snapshot_full_miss_uses_existing_loaders() -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        diagnostics=diagnostics,
    )

    assert len(actual) == 2
    assert diagnostics["scoring_snapshot_hit_count"] == 0
    assert diagnostics["scoring_snapshot_miss_count"] == 2
    assert diagnostics["scoring_snapshot_parse_error_count"] == 0


@pytest.mark.parametrize(
    ("failure_mode", "expected_parse_errors"),
    [
        ("snapshot_version", 0),
        ("malformed_payload", 1),
        ("stale_effect_version", 0),
    ],
)
def test_invalid_snapshot_rows_fall_back_without_changing_output(
    failure_mode: str,
    expected_parse_errors: int,
) -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(session, intent, candidates, matches)
    rollup_product_recommendation_scoring_snapshots(session)
    target = session.get(
        ProductRecommendationScoringSnapshot,
        candidates[0].db_product_id,
    )
    assert target is not None
    if failure_mode == "snapshot_version":
        target.snapshot_version = "stale"
    elif failure_mode == "malformed_payload":
        target.scoring_payload = {"broken": True}
    else:
        source_versions = dict(target.source_versions)
        effect_versions = {
            effect_code: "stale"
            for effect_code in source_versions["effect_features"]
        }
        assert effect_versions
        source_versions["effect_features"] = effect_versions
        target.source_versions = source_versions
        scoring_payload = dict(target.scoring_payload)
        scoring_payload["effect_features"] = {}
        target.scoring_payload = scoring_payload
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert diagnostics["scoring_snapshot_hit_count"] == 1
    assert diagnostics["scoring_snapshot_miss_count"] == 1
    assert diagnostics["scoring_snapshot_parse_error_count"] == expected_parse_errors


@pytest.mark.parametrize(
    "missing_source",
    [
        "skin_profile",
        "review_metric",
        "review_segments",
        "popularity_metric",
        "risk_flags",
        "effect_features",
    ],
)
def test_snapshot_preserves_scoring_when_optional_source_is_missing(
    missing_source: str,
) -> None:
    session = _seed_example_session(include_optional_sources=True)
    if missing_source == "skin_profile":
        session.execute(delete(ProductSkinProfile))
    elif missing_source == "review_metric":
        session.execute(delete(ProductReviewMetric))
    elif missing_source == "review_segments":
        session.execute(delete(ProductReviewSegmentMetric))
    elif missing_source == "popularity_metric":
        session.execute(delete(ProductPopularityMetric))
    elif missing_source == "risk_flags":
        session.execute(delete(RiskFlag))
    else:
        session.execute(delete(ProductEffectRecommendationFeature))
    session.commit()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(session, intent, candidates, matches)
    rollup_product_recommendation_scoring_snapshots(session)
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert diagnostics["scoring_snapshot_hit_count"] == 2
    assert diagnostics["scoring_snapshot_miss_count"] == 0


def _seed_example_session(*, include_optional_sources: bool = False) -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    rollup_product_recommendation_features(session)
    if include_optional_sources:
        _add_optional_sources(session)
    session.commit()
    return session


def _recommendation_inputs(session: Session):
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(
        "건조하고 민감한 피부에 보습 제품 추천",
        repository=repository,
    )
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    assert len(candidates) == 2
    return intent, candidates, matches


def _add_optional_sources(session: Session) -> None:
    session.execute(delete(ProductPopularityMetric))
    session.execute(delete(ProductReviewSegmentMetric))
    session.execute(delete(ProductReviewMetric))
    products = session.execute(select(Product).order_by(Product.id)).scalars().all()
    for index, product in enumerate(products, start=1):
        session.add_all(
            [
                ProductPopularityMetric(
                    product_id=product.id,
                    window_days=7,
                    popularity_score=Decimal(str(0.6 + index * 0.1)),
                ),
                ProductReviewMetric(
                    product_id=product.id,
                    review_count=10 * index,
                    rating_count=10 * index,
                    confidence=Decimal("0.7"),
                    effective_sample_size=Decimal(str(8 * index)),
                    review_quality_score=Decimal(str(0.65 + index * 0.05)),
                    score_version=REVIEW_SCORE_VERSION,
                ),
                ProductReviewSegmentMetric(
                    product_id=product.id,
                    dimension="SKIN_TYPE",
                    value_code="dry",
                    review_count=10 * index,
                    rating_count=10 * index,
                    effective_sample_size=Decimal(str(8 * index)),
                    total_affinity_score=Decimal(str(0.6 + index * 0.05)),
                    score_version=REVIEW_SCORE_VERSION,
                ),
            ]
        )
    session.flush()
