from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.elasticsearch_product_search import ElasticsearchProductSearchResult
from app.services.pgvector_product_search import PgvectorProductSearchResult
from app.services.candidate_pool import generate_candidate_pool
from app.services.db_seed import seed_database
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from tests.test_data_loader import EXAMPLES_DIR


def test_generate_candidate_pool_wraps_legacy_candidates_with_diagnostics() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="수부지",
        sensitivity="보통",
        avoid_ingredients=[],
        target_pool_size=20,
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_001", "prod_002"]
    assert pool.source_counts == {"legacy_id_order": 2}

    diagnostics = pool.to_diagnostics()
    assert diagnostics["candidate_generation_version"] == "candidate_pool_pgvector_v1"
    assert diagnostics["strategy"] == "candidate_pool"
    assert diagnostics["requested_candidate_pool_limit"] == 20
    assert diagnostics["loaded_candidate_count"] == 2
    assert diagnostics["merged_count"] == 2
    assert diagnostics["deduped_count"] == 2
    assert diagnostics["avoid_filtered_count"] == 0
    assert diagnostics["after_avoid_filter_count"] == 2
    assert diagnostics["source_diagnostics"] == [
        {
            "source": "legacy_id_order",
            "requested_limit": 20,
            "returned_count": 2,
            "after_dedupe_count": 2,
            "skipped_count": 0,
        }
    ]
    assert diagnostics["fallback_used"] is False


def test_generate_candidate_pool_filters_avoided_ingredients() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="수부지",
        sensitivity="높음",
        avoid_ingredients=["판테놀"],
        target_pool_size=20,
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_002"]
    diagnostics = pool.to_diagnostics()
    assert diagnostics["loaded_candidate_count"] == 2
    assert diagnostics["avoid_filtered_count"] == 1
    assert diagnostics["after_avoid_filter_count"] == 1


def test_generate_candidate_pool_prefers_elasticsearch_order_then_legacy_fill() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="수부지",
        sensitivity="보통",
        avoid_ingredients=[],
        target_pool_size=20,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search([2, 1], raw_hit_count=2),
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_002", "prod_001"]
    diagnostics = pool.to_diagnostics()
    assert diagnostics["source_counts"] == {
        "es_keyword_search": 2,
        "legacy_id_order": 2,
    }
    assert diagnostics["source_diagnostics"][0] == {
        "source": "es_keyword_search",
        "requested_limit": 20,
        "returned_count": 2,
        "after_dedupe_count": 2,
        "skipped_count": 0,
        "duration_ms": 3,
    }
    assert diagnostics["merged_count"] == 4
    assert diagnostics["deduped_count"] == 2
    assert diagnostics["fallback_used"] is False


def test_generate_candidate_pool_merges_pgvector_between_elasticsearch_and_legacy() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="수부지",
        sensitivity="보통",
        avoid_ingredients=[],
        target_pool_size=20,
        enable_elasticsearch=True,
        enable_pgvector=True,
        elasticsearch_search=_fake_es_search([2], raw_hit_count=1),
        pgvector_search=_fake_pgvector_search([1], raw_hit_count=1),
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_002", "prod_001"]
    diagnostics = pool.to_diagnostics()
    assert diagnostics["source_counts"] == {
        "es_keyword_search": 1,
        "pgvector_search": 1,
        "legacy_id_order": 2,
    }
    assert diagnostics["source_diagnostics"][1] == {
        "source": "pgvector_search",
        "requested_limit": 20,
        "returned_count": 1,
        "after_dedupe_count": 1,
        "skipped_count": 0,
        "duration_ms": 2,
        "provider_model": "local-hash-v1",
        "embedding_dimensions": 1536,
        "embedding_coverage": 1.0,
        "total_hit_count": 1,
    }
    assert diagnostics["merged_count"] == 4
    assert diagnostics["deduped_count"] == 2


def test_generate_candidate_pool_falls_back_to_legacy_when_elasticsearch_fails() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    pool = generate_candidate_pool(
        session,
        intent,
        skin_type="수부지",
        sensitivity="보통",
        avoid_ingredients=[],
        target_pool_size=20,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search([], raw_hit_count=0, failure_reason="index missing"),
    )

    assert [candidate.product_id for candidate in pool.candidates] == ["prod_001", "prod_002"]
    diagnostics = pool.to_diagnostics()
    assert diagnostics["source_diagnostics"][0]["source"] == "es_keyword_search"
    assert diagnostics["source_diagnostics"][0]["failure_reason"] == "index missing"
    assert diagnostics["fallback_used"] is True


def _fake_es_search(
    product_db_ids: list[int],
    *,
    raw_hit_count: int,
    failure_reason: str | None = None,
):
    def search(*args, **kwargs) -> ElasticsearchProductSearchResult:
        return ElasticsearchProductSearchResult(
            product_db_ids=tuple(product_db_ids),
            raw_hit_count=raw_hit_count,
            attempted=True,
            index_alias="test_products_current",
            query_text="test query",
            duration_ms=3,
            failure_reason=failure_reason,
        )

    return search


def _fake_pgvector_search(
    product_db_ids: list[int],
    *,
    raw_hit_count: int,
    failure_reason: str | None = None,
):
    def search(*args, **kwargs) -> PgvectorProductSearchResult:
        return PgvectorProductSearchResult(
            product_db_ids=tuple(product_db_ids),
            scores_by_product_db_id={
                product_db_id: 0.8
                for product_db_id in product_db_ids
            },
            raw_hit_count=raw_hit_count,
            attempted=True,
            query_text="test query",
            provider_model="local-hash-v1",
            dimensions=1536,
            duration_ms=2,
            embedding_coverage=1.0,
            failure_reason=failure_reason,
            total_hit_count=raw_hit_count,
        )

    return search


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
