from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import ProductRecommendationCoarseFeature
from app.db.session import make_engine
from app.services import recommendation_coarse_feature_rollup, scoring
from app.services.db_seed import seed_database
from app.services.product_candidates import ProductCandidate, list_product_candidates
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_coarse_feature_rollup import (
    rollup_product_recommendation_coarse_features,
)
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_feature_versions import (
    PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
)
from app.services.recommendation_intent import (
    RecommendationIntent,
    build_recommendation_intent,
)
from app.services.repository import load_repository
from app.services.scoring import ScoredProduct, score_candidates
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_coarse_path_sends_only_top50_to_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(75)
    _add_coarse_rows(session, range(1, 76))
    exact_calls: list[tuple[list[int], int | None, bool]] = []

    def capture_exact(_session, _intent, exact_candidates, _matches, **kwargs):
        exact_calls.append(
            (
                [candidate.db_product_id for candidate in exact_candidates],
                kwargs.get("result_limit"),
                bool(kwargs.get("single_pass_details")),
            )
        )
        _set_exact_diagnostics(kwargs.get("diagnostics"))
        return [_scored(candidate) for candidate in exact_candidates]

    def fail_detail_loader(*_args, **_kwargs):
        raise AssertionError("coarse stage must not call an exact detail loader")

    monkeypatch.setattr(scoring, "_score_candidates_exact", capture_exact)
    monkeypatch.setattr(scoring, "_load_candidate_scoring_bundles", fail_detail_loader)
    monkeypatch.setattr(scoring, "_load_risk_flags", fail_detail_loader)
    monkeypatch.setattr(scoring, "_load_review_segments", fail_detail_loader)
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
        result_limit=10,
        diagnostics=diagnostics,
    )

    assert len(results) == 50
    assert exact_calls == [(list(range(1, 51)), None, True)]
    assert diagnostics["coarse_shortlist_size"] == 50
    assert diagnostics["coarse_feature_hit_count"] == 75
    assert diagnostics["scoring_fallback"] is False


def test_coarse_path_limits_all_exact_detail_loaders_to_top50(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(75)
    _add_coarse_rows(session, range(1, 76))
    loader_sizes: dict[str, list[int]] = {
        "candidate_bundles": [],
        "effect_features": [],
        "ingredient_effects": [],
        "risk_flags": [],
        "review_segments": [],
    }

    original_candidate_bundles = scoring._load_candidate_scoring_bundles
    original_effect_features = scoring._load_product_effect_recommendation_features
    original_ingredient_effects = scoring._load_ingredient_effects
    original_risk_flags = scoring._load_risk_flags
    original_review_segments = scoring._load_review_segments

    def capture_candidate_bundles(loader_session, loader_candidates):
        loader_sizes["candidate_bundles"].append(len(loader_candidates))
        return original_candidate_bundles(loader_session, loader_candidates)

    def capture_effect_features(loader_session, product_ids, desired_effects):
        loader_sizes["effect_features"].append(len(product_ids))
        return original_effect_features(loader_session, product_ids, desired_effects)

    def capture_ingredient_effects(
        loader_session,
        product_ids,
        desired_effects,
        **kwargs,
    ):
        loader_sizes["ingredient_effects"].append(len(product_ids))
        return original_ingredient_effects(
            loader_session,
            product_ids,
            desired_effects,
            **kwargs,
        )

    def capture_risk_flags(loader_session, product_ids):
        loader_sizes["risk_flags"].append(len(product_ids))
        return original_risk_flags(loader_session, product_ids)

    def capture_review_segments(loader_session, product_ids):
        loader_sizes["review_segments"].append(len(product_ids))
        return original_review_segments(loader_session, product_ids)

    monkeypatch.setattr(
        scoring,
        "_load_candidate_scoring_bundles",
        capture_candidate_bundles,
    )
    monkeypatch.setattr(
        scoring,
        "_load_product_effect_recommendation_features",
        capture_effect_features,
    )
    monkeypatch.setattr(
        scoring,
        "_load_ingredient_effects",
        capture_ingredient_effects,
    )
    monkeypatch.setattr(scoring, "_load_risk_flags", capture_risk_flags)
    monkeypatch.setattr(scoring, "_load_review_segments", capture_review_segments)

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
    )

    assert len(results) == 50
    assert loader_sizes["candidate_bundles"] == [50]
    assert loader_sizes["effect_features"]
    assert max(loader_sizes["effect_features"]) <= 50
    assert loader_sizes["risk_flags"] == [50]
    assert loader_sizes["review_segments"] == [50]
    assert loader_sizes["ingredient_effects"]
    assert max(loader_sizes["ingredient_effects"]) <= 50


def test_coarse_partial_miss_loads_only_missing_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(21)
    _add_coarse_rows(session, range(1, 21))
    fallback_calls: list[list[int]] = []

    def source_fallback(_session, product_ids, *, computed_at):
        assert computed_at.tzinfo is not None
        fallback_calls.append(list(product_ids))
        return [_source_row(product_id) for product_id in product_ids]

    def capture_exact(_session, _intent, exact_candidates, _matches, **kwargs):
        _set_exact_diagnostics(kwargs.get("diagnostics"))
        return [_scored(candidate) for candidate in exact_candidates]

    monkeypatch.setattr(
        recommendation_coarse_feature_rollup,
        "load_product_recommendation_coarse_feature_source_rows",
        source_fallback,
    )
    monkeypatch.setattr(scoring, "_score_candidates_exact", capture_exact)
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
        diagnostics=diagnostics,
    )

    assert len(results) == 21
    assert fallback_calls == [[21]]
    assert diagnostics["coarse_feature_hit_count"] == 20
    assert diagnostics["coarse_feature_miss_count"] == 1
    assert diagnostics["scoring_fallback"] is False


def test_coarse_partial_stale_loads_only_stale_source_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(21)
    _add_coarse_rows(session, range(1, 22))
    stale_row = session.get(ProductRecommendationCoarseFeature, 21)
    assert stale_row is not None
    stale_row.source_current = False
    session.commit()
    fallback_calls: list[list[int]] = []

    def source_fallback(_session, product_ids, *, computed_at):
        fallback_calls.append(list(product_ids))
        return [_source_row(product_id) for product_id in product_ids]

    def capture_exact(_session, _intent, exact_candidates, _matches, **kwargs):
        _set_exact_diagnostics(kwargs.get("diagnostics"))
        return [_scored(candidate) for candidate in exact_candidates]

    monkeypatch.setattr(
        recommendation_coarse_feature_rollup,
        "load_product_recommendation_coarse_feature_source_rows",
        source_fallback,
    )
    monkeypatch.setattr(scoring, "_score_candidates_exact", capture_exact)
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
        diagnostics=diagnostics,
    )

    assert len(results) == 21
    assert fallback_calls == [[21]]
    assert diagnostics["coarse_feature_hit_count"] == 20
    assert diagnostics["coarse_feature_miss_count"] == 0
    assert diagnostics["coarse_feature_stale_count"] == 1
    assert diagnostics["scoring_fallback"] is False


def test_coarse_incomplete_partial_source_uses_full_exact_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(21)
    _add_coarse_rows(session, range(1, 21))
    exact_calls: list[list[int]] = []

    monkeypatch.setattr(
        recommendation_coarse_feature_rollup,
        "load_product_recommendation_coarse_feature_source_rows",
        lambda *_args, **_kwargs: [],
    )

    def capture_exact(_session, _intent, exact_candidates, _matches, **kwargs):
        exact_calls.append(
            [candidate.db_product_id for candidate in exact_candidates]
        )
        _set_exact_diagnostics(kwargs.get("diagnostics"))
        return [_scored(candidate) for candidate in exact_candidates]

    monkeypatch.setattr(scoring, "_score_candidates_exact", capture_exact)
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
        diagnostics=diagnostics,
    )

    assert len(results) == 21
    assert exact_calls == [list(range(1, 22))]
    assert diagnostics["scoring_fallback"] is True
    assert diagnostics["scoring_fallback_reason"] == (
        "coarse_feature_source_fallback_incomplete"
    )


def test_coarse_miss_ratio_over_threshold_uses_full_exact_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _empty_session()
    candidates = _synthetic_candidates(10)
    _add_coarse_rows(session, range(1, 10))
    exact_calls: list[tuple[list[int], bool]] = []

    def capture_exact(_session, _intent, exact_candidates, _matches, **kwargs):
        exact_calls.append(
            (
                [candidate.db_product_id for candidate in exact_candidates],
                bool(kwargs.get("single_pass_details")),
            )
        )
        _set_exact_diagnostics(kwargs.get("diagnostics"))
        return [_scored(candidate) for candidate in exact_candidates]

    monkeypatch.setattr(scoring, "_score_candidates_exact", capture_exact)
    diagnostics: dict[str, object] = {}

    results = score_candidates(
        session,
        _empty_intent(),
        candidates,
        [],
        scoring_read_path="coarse_top50_v1",
        diagnostics=diagnostics,
    )

    assert len(results) == 10
    assert exact_calls == [(list(range(1, 11)), False)]
    assert diagnostics["scoring_fallback"] is True
    assert diagnostics["scoring_fallback_reason"] == (
        "coarse_feature_miss_ratio_exceeded"
    )
    assert diagnostics["coarse_shortlist_size"] == 0


def test_coarse_shortlist_exact_scores_match_legacy_and_preserve_quality() -> None:
    session = _seed_example_session()
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
    rollup_product_recommendation_coarse_features(session)
    session.commit()
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
        scoring_read_path="coarse_top50_v1",
        diagnostics=diagnostics,
    )

    assert actual == baseline
    baseline_top10 = {product.db_product_id for product in baseline[:10]}
    actual_ids = {product.db_product_id for product in actual}
    recall_at_50 = len(baseline_top10 & actual_ids) / len(baseline_top10)
    assert baseline[0].db_product_id in actual_ids
    assert recall_at_50 == 1.0
    assert diagnostics["exact_prefetch_ms"] >= 0.0
    assert diagnostics["exact_score_loop_ms"] >= 0.0
    assert diagnostics["exact_functional_axis_ms"] >= 0.0


def test_coarse_path_preserves_all_result_details_with_result_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _seed_example_session()
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
    rollup_product_recommendation_coarse_features(session)
    session.commit()

    original_loader = scoring._load_ingredient_effects
    ingredient_loads: list[
        tuple[list[int], tuple[tuple[int, str, int], ...] | None]
    ] = []

    def capture_ingredient_loads(
        loader_session,
        product_ids,
        desired_effects,
        **kwargs,
    ):
        ingredient_loads.append((list(product_ids), kwargs.get("selection_keys")))
        return original_loader(
            loader_session,
            product_ids,
            desired_effects,
            **kwargs,
        )

    monkeypatch.setattr(
        scoring,
        "_load_ingredient_effects",
        capture_ingredient_loads,
    )
    diagnostics: dict[str, object] = {}

    actual = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="dry",
        sensitivity="high",
        scoring_read_path="coarse_top50_v1",
        result_limit=1,
        diagnostics=diagnostics,
    )

    assert actual == baseline
    selected_loads = [
        (product_ids, selection_keys)
        for product_ids, selection_keys in ingredient_loads
        if product_ids and selection_keys is not None
    ]
    assert len(selected_loads) == 1
    selected_product_ids, selection_keys = selected_loads[0]
    assert selected_product_ids == [product.db_product_id for product in actual]
    assert selection_keys
    assert {
        product_id for product_id, _effect_code, _ingredient_id in selection_keys
    }.issubset(set(selected_product_ids))
    assert diagnostics["score_detail_count"] == len(actual)
    prefetch_detail = diagnostics["scoring_prefetch_detail"]
    assert prefetch_detail["detail_ingredients_selection_applied"] == 1
    assert prefetch_detail["detail_ingredients_selection_key_count"] == len(
        selection_keys
    )


def _empty_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_example_session() -> Session:
    session = _empty_session()
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    rollup_product_recommendation_features(session)
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
    assert candidates
    return intent, candidates, matches


def _empty_intent() -> RecommendationIntent:
    return RecommendationIntent(
        concern_text="",
        normalized_text="",
        purchase_conditions=ParsedPurchaseConditions(
            categories=(),
            brands=(),
            price_min=None,
            price_max=None,
            price_text=None,
            price_max_text=None,
        ),
        concerns=(),
        effects=(),
        excluded_concerns=(),
        priority_effects=(),
        unmatched_terms=(),
        needs_llm=False,
    )


def _synthetic_candidates(count: int) -> list[ProductCandidate]:
    return [
        ProductCandidate(
            db_product_id=product_id,
            product_id=f"product-{product_id}",
            brand_code="brand",
            brand="Brand",
            category_code="serum",
            name=f"Product {product_id}",
            thumbnail_url=None,
            lowest_price=10_000,
        )
        for product_id in range(1, count + 1)
    ]


def _add_coarse_rows(session: Session, product_ids) -> None:
    now = datetime.now(UTC)
    session.add_all(
        ProductRecommendationCoarseFeature(
            product_id=product_id,
            normal_fit=5_000,
            sensitive_fit=5_000,
            skin_profile_confidence_code=2,
            source_current=True,
            feature_version=PRODUCT_RECOMMENDATION_COARSE_FEATURE_VERSION,
            source_updated_at=now,
            computed_at=now,
        )
        for product_id in product_ids
    )
    session.commit()


def _source_row(product_id: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "normal_fit": 5_000,
        "sensitive_fit": 5_000,
        "skin_profile_confidence_code": 2,
    }


def _scored(candidate: ProductCandidate) -> ScoredProduct:
    return ScoredProduct(
        product_id=candidate.product_id,
        db_product_id=candidate.db_product_id,
        rank=0,
        total_score=50.0,
        reason_summary="",
        evidence_tags=(),
        key_ingredients=(),
        score_breakdown={},
        score_evidence=(),
    )


def _set_exact_diagnostics(diagnostics: dict[str, object] | None) -> None:
    if diagnostics is None:
        return
    diagnostics.update(
        {
            "scoring_data_prefetch_ms": 1.0,
            "score_loop_ms": 2.0,
            "score_detail_materialization_ms": 0.0,
            "score_loop_breakdown": {"functional_axis_ms": 0.5},
            "score_detail_breakdown": {},
        }
    )
