from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import _normalize_recommendation_scoring_read_path
from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import ProductRecommendationScoringReadModel
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.session import make_engine
from app.services import scoring
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_scoring_read_model_rollup import (
    rollup_product_recommendation_scoring_read_models,
)
from app.services.repository import load_repository
from app.services.review_rollup import REVIEW_SCORE_VERSION
from app.services.scoring import score_candidates
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_compact_read_model_all_hits_preserve_complete_scoring_output() -> None:
    session = _seed_example_session(include_optional_sources=True)
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
        scoring_read_path="legacy_bulk",
    )
    rollup_product_recommendation_scoring_read_models(session)
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
        scoring_read_path="compact_v2",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert diagnostics["scoring_read_path"] == "compact_v2"
    assert diagnostics["scoring_compact_read_model_hit_count"] == 2
    assert diagnostics["scoring_compact_read_model_miss_count"] == 0
    assert diagnostics["scoring_compact_read_model_stale_count"] == 0
    assert diagnostics["scoring_compact_read_model_fallback_ms"] == 0.0
    assert diagnostics["scoring_compact_read_model_load_ms"] >= 0.0
    assert diagnostics["scoring_compact_read_model_query_ms"] >= 0.0
    assert diagnostics["scoring_compact_read_model_build_ms"] >= 0.0


def test_compact_partial_miss_uses_one_bulk_fallback_for_missing_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _seed_example_session(include_optional_sources=True)
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        scoring_read_path="legacy_bulk",
    )
    rollup_product_recommendation_scoring_read_models(session)
    missing_product_id = candidates[0].db_product_id
    session.execute(
        delete(ProductRecommendationScoringReadModel).where(
            ProductRecommendationScoringReadModel.product_id
            == missing_product_id
        )
    )
    session.commit()
    fallback_calls: list[list[int]] = []
    original_loader = scoring._load_candidate_scoring_bundles

    def capture_fallback(session_arg, fallback_candidates):
        fallback_calls.append(
            [candidate.db_product_id for candidate in fallback_candidates]
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
        scoring_read_path="compact_v2",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert fallback_calls == [[missing_product_id]]
    assert diagnostics["scoring_compact_read_model_hit_count"] == 1
    assert diagnostics["scoring_compact_read_model_miss_count"] == 1
    assert diagnostics["scoring_compact_read_model_stale_count"] == 0


def test_compact_full_miss_falls_back_once_for_all_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        scoring_read_path="legacy_bulk",
    )
    fallback_calls: list[list[int]] = []
    original_loader = scoring._load_candidate_scoring_bundles

    def capture_fallback(session_arg, fallback_candidates):
        fallback_calls.append(
            [candidate.db_product_id for candidate in fallback_candidates]
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
        scoring_read_path="compact_v2",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert fallback_calls == [
        [candidate.db_product_id for candidate in candidates]
    ]
    assert diagnostics["scoring_compact_read_model_hit_count"] == 0
    assert diagnostics["scoring_compact_read_model_miss_count"] == 2


@pytest.mark.parametrize(
    ("field_name", "stale_value"),
    [
        ("read_model_version", "stale"),
        ("product_feature_version", "stale"),
        ("product_feature_source_current", False),
        ("review_score_version", "stale"),
        ("popularity_window_days", 30),
    ],
)
def test_compact_stale_row_falls_back_without_changing_output(
    field_name: str,
    stale_value: object,
) -> None:
    session = _seed_example_session(include_optional_sources=True)
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        scoring_read_path="legacy_bulk",
    )
    rollup_product_recommendation_scoring_read_models(session)
    target = session.get(
        ProductRecommendationScoringReadModel,
        candidates[0].db_product_id,
    )
    assert target is not None
    setattr(target, field_name, stale_value)
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        scoring_read_path="compact_v2",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    assert diagnostics["scoring_compact_read_model_hit_count"] == 1
    assert diagnostics["scoring_compact_read_model_miss_count"] == 0
    assert diagnostics["scoring_compact_read_model_stale_count"] == 1


def test_legacy_path_does_not_query_compact_read_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("legacy_bulk must not query the compact read model")

    monkeypatch.setattr(
        scoring,
        "_load_recommendation_scoring_read_models",
        fail_if_called,
    )
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        intent,
        candidates,
        matches,
        scoring_read_path="legacy_bulk",
        diagnostics=diagnostics,
    )

    assert len(results) == 2
    assert diagnostics["scoring_read_path"] == "legacy_bulk"
    assert diagnostics["scoring_compact_read_model_load_ms"] == 0.0


def test_effect_feature_loader_fetches_only_requested_effects() -> None:
    session = _seed_example_session()
    intent, candidates, _matches = _recommendation_inputs(session)
    desired_effects = scoring._build_desired_effects(intent)
    assert desired_effects
    requested_effect = desired_effects[:1]

    features, _stale_ids, _hit_count = (
        scoring._load_product_effect_recommendation_features(
            session,
            [candidate.db_product_id for candidate in candidates],
            requested_effect,
        )
    )

    assert all(
        set(product_features) <= {requested_effect[0].effect_code}
        for product_features in features.values()
    )


def test_invalid_scoring_read_path_is_rejected() -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)

    with pytest.raises(ValueError, match="legacy_bulk or compact_v2"):
        score_candidates(
            session,
            intent,
            candidates,
            matches,
            scoring_read_path="snapshot_v1",
        )


@pytest.mark.parametrize("value", ["legacy_bulk", "compact_v2", " COMPACT_V2 "])
def test_scoring_read_path_setting_accepts_only_supported_values(value: str) -> None:
    assert _normalize_recommendation_scoring_read_path(value) in {
        "legacy_bulk",
        "compact_v2",
    }


def test_scoring_read_path_setting_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="legacy_bulk or compact_v2"):
        _normalize_recommendation_scoring_read_path("snapshot_v1")


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
        "건조하고 민감한 피부를 위한 보습 제품 추천",
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
