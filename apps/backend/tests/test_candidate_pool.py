import app.services.candidate_pool as candidate_pool_service
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.commerce import ProductPopularityMetric
from app.db.session import make_engine
from app.services.candidate_pool import generate_candidate_pool
from app.services.db_seed import seed_database
from app.services.elasticsearch_recommendation_candidates import (
    ElasticsearchRecommendationCandidateResult,
)
from app.services.product_candidates import ProductCandidate
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from tests.test_data_loader import EXAMPLES_DIR


def test_generate_candidate_pool_uses_only_catalog_es_on_success(monkeypatch) -> None:
    session = _seed_example_session()
    intent = _build_intent()
    es_candidates = (_candidate(2), _candidate(1))

    monkeypatch.setattr(
        candidate_pool_service,
        "list_recommendation_fallback_candidates",
        _unexpected_fallback,
    )
    monkeypatch.setattr(
        "app.services.pgvector_product_search.search_pgvector_product_candidates",
        _unexpected_pgvector,
    )

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="combination",
        sensitivity="normal",
        avoid_ingredients=[],
        target_pool_size=20,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search(
            es_candidates,
            direct_match_count=2,
        ),
    )

    assert [candidate.product_id for candidate in pool.candidates] == [
        "prod_002",
        "prod_001",
    ]
    assert all(candidate.thumbnail_url is None for candidate in pool.candidates)
    assert pool.source_counts == {"catalog_es_recommendation": 2}
    assert pool.fallback_used is False

    diagnostics = pool.to_diagnostics()
    assert diagnostics["candidate_generation_version"] == "candidate_pool_catalog_es_v2"
    assert diagnostics["strategy"] == "catalog_es_candidate_pool"
    assert diagnostics["es_direct_match_count"] == 2
    assert diagnostics["es_popularity_fill_count"] == 0
    assert diagnostics["final_candidate_count"] == 2


def test_generate_candidate_pool_does_not_fallback_when_es_returns_fewer_candidates(
    monkeypatch,
) -> None:
    session = _seed_example_session()
    intent = _build_intent()
    monkeypatch.setattr(
        candidate_pool_service,
        "list_recommendation_fallback_candidates",
        _unexpected_fallback,
    )

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="normal",
        sensitivity="low",
        avoid_ingredients=[],
        target_pool_size=500,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search(
            (_candidate(1),),
            direct_match_count=1,
            total_hit_count=1,
        ),
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_001"]
    assert pool.fallback_used is False
    assert pool.hard_filter_total_count == 1


def test_generate_candidate_pool_caps_and_deduplicates_es_results() -> None:
    session = _seed_example_session()
    intent = _build_intent()
    candidates = tuple(_candidate(product_id) for product_id in range(1, 502))

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="normal",
        sensitivity="low",
        avoid_ingredients=[],
        target_pool_size=500,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search(
            (*candidates, candidates[0]),
            direct_match_count=502,
        ),
    )

    assert len(pool.candidates) == 500
    assert len({candidate.db_product_id for candidate in pool.candidates}) == 500
    assert pool.cap_applied_count == 1


def test_generate_candidate_pool_uses_popularity_fallback_only_on_es_failure() -> None:
    session = _seed_example_session()
    session.add(
        ProductPopularityMetric(
            product_id=2,
            window_days=7,
            popularity_score=100,
        )
    )
    session.flush()

    pool = generate_candidate_pool(
        session,
        _build_intent(),
        skin_type="normal",
        sensitivity="low",
        avoid_ingredients=[],
        target_pool_size=20,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search(
            (),
            failure_reason="index missing",
        ),
    )

    assert [candidate.product_id for candidate in pool.candidates] == [
        "prod_002",
        "prod_001",
    ]
    assert all(candidate.thumbnail_url is None for candidate in pool.candidates)
    assert pool.source_counts == {
        "catalog_es_recommendation": 0,
        "db_popularity_fallback": 2,
    }
    assert pool.fallback_used is True
    assert pool.fallback_reason == "index missing"
    assert pool.fallback_count == 2


def _fake_es_search(
    candidates: tuple[ProductCandidate, ...],
    *,
    direct_match_count: int = 0,
    popularity_fill_count: int = 0,
    failure_reason: str | None = None,
    total_hit_count: int | None = None,
):
    def search(*args, **kwargs) -> ElasticsearchRecommendationCandidateResult:
        return ElasticsearchRecommendationCandidateResult(
            candidates=candidates,
            raw_hit_count=len(candidates),
            direct_match_count=direct_match_count,
            popularity_fill_count=popularity_fill_count,
            pre_dedupe_count=len(candidates),
            deduped_count=len({candidate.db_product_id for candidate in candidates}),
            attempted=True,
            index_alias="test_catalog_current",
            query_text="test query",
            duration_ms=3,
            failure_reason=failure_reason,
            total_hit_count=(
                total_hit_count if total_hit_count is not None else len(candidates)
            ),
        )

    return search


def _candidate(product_db_id: int) -> ProductCandidate:
    return ProductCandidate(
        db_product_id=product_db_id,
        product_id=f"prod_{product_db_id:03d}",
        brand_code="test_brand",
        brand="Test Brand",
        category_code="serum",
        name=f"Test Product {product_db_id}",
        thumbnail_url=None,
        lowest_price=10_000 + product_db_id,
    )


def _unexpected_fallback(*args, **kwargs):
    raise AssertionError("DB fallback must not run after a successful ES request")


def _unexpected_pgvector(*args, **kwargs):
    raise AssertionError("pgvector must not run in candidate_pool_catalog_es_v2")


def _build_intent():
    repository = load_repository(EXAMPLES_DIR)
    return build_recommendation_intent(
        "hydration recommendation",
        repository=repository,
    )


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
