from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.elasticsearch_product_search import ElasticsearchProductSearchResult
from app.services.pgvector_product_search import PgvectorProductSearchResult
from app.services.product_search_service import get_product_search_response
from app.services.search_index_builder import build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_product_search_response_uses_database_fallback_by_default_on_sqlite() -> None:
    session = _seed_example_session()

    response = get_product_search_response(
        session,
        query="수분 크림",
        page=1,
        page_size=10,
    )

    assert response.diagnostics.backend == "database"
    assert response.diagnostics.fallback_used is False
    assert response.diagnostics.es_attempted is False
    assert response.items
    assert all(item.match_source == "database" for item in response.items)
    assert response.pagination.total_items >= len(response.items)


def test_product_search_response_uses_elasticsearch_when_available() -> None:
    session = _seed_example_session()

    response = get_product_search_response(
        session,
        query="수분 추천",
        page=1,
        page_size=10,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search([2, 1], total_hit_count=2),
    )

    assert response.diagnostics.backend == "elasticsearch"
    assert response.diagnostics.fallback_used is False
    assert response.diagnostics.es_attempted is True
    assert [item.product_id for item in response.items] == ["prod_002", "prod_001"]
    assert all(item.match_source == "elasticsearch" for item in response.items)
    assert response.pagination.total_items == 2


def test_product_search_response_falls_back_to_database_when_elasticsearch_fails() -> None:
    session = _seed_example_session()

    response = get_product_search_response(
        session,
        query="수분 크림",
        page=1,
        page_size=10,
        enable_elasticsearch=True,
        elasticsearch_search=_fake_es_search([], failure_reason="index missing"),
    )

    assert response.diagnostics.backend == "database"
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.es_attempted is True
    assert response.diagnostics.es_failure_reason == "index missing"
    assert response.items
    assert all(item.match_source == "database" for item in response.items)


def test_product_search_response_uses_pgvector_when_elasticsearch_fails() -> None:
    session = _seed_example_session()

    response = get_product_search_response(
        session,
        query="수분 추천",
        page=1,
        page_size=10,
        enable_elasticsearch=True,
        enable_pgvector=True,
        elasticsearch_search=_fake_es_search([], failure_reason="index missing"),
        pgvector_search=_fake_pgvector_search([2, 1], total_hit_count=2),
    )

    assert response.diagnostics.backend == "pgvector"
    assert response.diagnostics.fallback_used is True
    assert response.diagnostics.es_attempted is True
    assert response.diagnostics.es_failure_reason == "index missing"
    assert response.diagnostics.vector_attempted is True
    assert response.diagnostics.vector_result_count == 2
    assert [item.product_id for item in response.items] == ["prod_002", "prod_001"]
    assert all(item.match_source == "pgvector" for item in response.items)
    assert all(item.search_score == 0.8 for item in response.items)


def test_product_search_response_fills_elasticsearch_results_with_pgvector() -> None:
    session = _seed_example_session()

    response = get_product_search_response(
        session,
        query="수분 추천",
        page=1,
        page_size=2,
        enable_elasticsearch=True,
        enable_pgvector=True,
        elasticsearch_search=_fake_es_search([2], total_hit_count=1),
        pgvector_search=_fake_pgvector_search([2, 1], total_hit_count=2),
    )

    assert response.diagnostics.backend == "hybrid"
    assert response.diagnostics.fallback_used is False
    assert response.diagnostics.vector_attempted is True
    assert [item.product_id for item in response.items] == ["prod_002", "prod_001"]
    assert [item.match_source for item in response.items] == ["elasticsearch", "pgvector"]
    assert response.pagination.total_items == 2


def _fake_es_search(
    product_db_ids: list[int],
    *,
    total_hit_count: int | None = None,
    failure_reason: str | None = None,
):
    def search(*args, **kwargs) -> ElasticsearchProductSearchResult:
        return ElasticsearchProductSearchResult(
            product_db_ids=tuple(product_db_ids),
            raw_hit_count=len(product_db_ids),
            attempted=True,
            index_alias="test_products_current",
            query_text="test query",
            duration_ms=3,
            failure_reason=failure_reason,
            total_hit_count=total_hit_count if total_hit_count is not None else len(product_db_ids),
        )

    return search


def _fake_pgvector_search(
    product_db_ids: list[int],
    *,
    total_hit_count: int | None = None,
    failure_reason: str | None = None,
):
    def search(*args, **kwargs) -> PgvectorProductSearchResult:
        return PgvectorProductSearchResult(
            product_db_ids=tuple(product_db_ids),
            scores_by_product_db_id={
                product_db_id: 0.8
                for product_db_id in product_db_ids
            },
            raw_hit_count=len(product_db_ids),
            attempted=True,
            query_text="test query",
            provider_model="local-hash-v1",
            dimensions=1536,
            duration_ms=2,
            embedding_coverage=1.0,
            failure_reason=failure_reason,
            total_hit_count=total_hit_count if total_hit_count is not None else len(product_db_ids),
        )

    return search


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session
