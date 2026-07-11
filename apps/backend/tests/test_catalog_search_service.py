from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.review import ProductReviewMetric
from app.db.session import make_engine
from app.services.catalog_search_service import get_catalog_search_response
from app.services.db_seed import seed_database
from app.services.elasticsearch_catalog_search import ElasticsearchCatalogSearchResult
from tests.test_data_loader import EXAMPLES_DIR


def test_catalog_search_hydrates_elasticsearch_order_from_database() -> None:
    session = _seed_example_session()

    execution = get_catalog_search_response(
        session,
        query="세럼",
        page=1,
        page_size=2,
        elasticsearch_search=_fake_es_search([2, 1], total=2),
    )

    assert execution.backend == "elasticsearch"
    assert execution.fallback_used is False
    assert [item.product_id for item in execution.response.items] == ["prod_002"]
    assert execution.response.pagination.total_items == 1
    assert execution.response.items[0].lowest_price == 22900
    assert execution.response.items[0].sales_status == "UNKNOWN"


def test_catalog_search_uses_only_bounded_database_fallback_when_es_fails() -> None:
    session = _seed_example_session()

    execution = get_catalog_search_response(
        session,
        query="수분 크림",
        page=1,
        page_size=20,
        elasticsearch_search=_fake_es_search([], failure_reason="index missing"),
    )

    assert execution.backend == "database"
    assert execution.fallback_used is True
    assert [item.product_id for item in execution.response.items] == ["prod_001"]
    assert execution.response.applied_filters.categories == ["cream"]


def test_catalog_search_does_not_fill_successful_empty_es_result() -> None:
    session = _seed_example_session()

    execution = get_catalog_search_response(
        session,
        query="존재하지 않는 상품",
        elasticsearch_search=_fake_es_search([], total=0),
    )

    assert execution.backend == "elasticsearch"
    assert execution.fallback_used is False
    assert execution.response.items == []
    assert execution.response.pagination.total_items == 0


def test_catalog_search_skips_recovery_when_normal_results_are_at_least_three() -> None:
    session = _seed_example_session()
    calls: list[dict] = []

    def search(*args, **kwargs) -> ElasticsearchCatalogSearchResult:
        calls.append(kwargs)
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(1,),
            total_hit_count=3,
            aggregations={},
            attempted=True,
            duration_ms=2,
            index_alias="test_catalog_products_current",
        )

    execution = get_catalog_search_response(
        session,
        query="라운드렙",
        elasticsearch_search=search,
    )

    assert len(calls) == 1
    assert execution.recovery_used is False
    assert execution.response.corrected_query is None


def test_catalog_search_uses_recovery_only_below_three_results() -> None:
    session = _seed_example_session()
    calls: list[dict] = []

    def search(*args, **kwargs) -> ElasticsearchCatalogSearchResult:
        calls.append(kwargs)
        is_recovery = kwargs.get("recovery_only", False)
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(1,) if is_recovery else (),
            total_hit_count=1 if is_recovery else 0,
            aggregations={},
            attempted=True,
            duration_ms=2,
            index_alias="test_catalog_products_current",
            suggested_queries=("토리든",) if is_recovery else (),
        )

    execution = get_catalog_search_response(
        session,
        query="토리덴",
        elasticsearch_search=search,
    )

    assert len(calls) == 2
    assert calls[1]["recovery_only"] is True
    assert calls[1]["fuzzy_enabled"] is True
    assert execution.recovery_used is True
    assert execution.response.corrected_query == "토리든"
    assert execution.response.query == "토리덴"


def test_catalog_search_exposes_confident_correction_without_extra_recovery() -> None:
    session = _seed_example_session()
    calls: list[dict] = []

    def search(*args, **kwargs) -> ElasticsearchCatalogSearchResult:
        calls.append(kwargs)
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(1,),
            total_hit_count=3,
            aggregations={},
            attempted=True,
            duration_ms=2,
            index_alias="test_catalog_products_current",
        )

    execution = get_catalog_search_response(
        session,
        query="히알루론사",
        elasticsearch_search=search,
    )

    assert len(calls) == 1
    assert execution.recovery_used is False
    assert execution.response.corrected_query == "히알루론산"


def test_catalog_search_hydrates_rating_from_review_metrics() -> None:
    session = _seed_example_session()
    product = session.scalar(select(Product).where(Product.product_code == "prod_001"))
    assert product is not None
    session.add_all(
        [
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                review_count=999,
                average_rating=1.0,
                popularity_score=70,
            ),
            ProductReviewMetric(
                product_id=product.id,
                review_count=12,
                rating_count=12,
                average_rating=4.8,
            ),
        ]
    )
    session.flush()

    execution = get_catalog_search_response(
        session,
        query="수분 크림",
        elasticsearch_search=_fake_es_search([product.id], total=1),
    )

    assert execution.response.items[0].rating == 4.8
    assert execution.response.items[0].review_count == 12


def _fake_es_search(
    product_db_ids: list[int],
    *,
    total: int | None = None,
    failure_reason: str | None = None,
):
    def search(*args, **kwargs) -> ElasticsearchCatalogSearchResult:
        return ElasticsearchCatalogSearchResult(
            product_db_ids=tuple(product_db_ids),
            total_hit_count=len(product_db_ids) if total is None else total,
            aggregations={},
            attempted=True,
            duration_ms=3,
            index_alias="test_catalog_products_current",
            failure_reason=failure_reason,
        )

    return search


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
