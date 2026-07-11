from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.catalog_suggestion_service import (
    _document_matches_prefix,
    get_catalog_suggestions_response,
)
from app.services.db_seed import seed_database
from app.services.elasticsearch_catalog_search import (
    CatalogSuggestionDocument,
    ElasticsearchCatalogSuggestionResult,
)
from tests.test_data_loader import EXAMPLES_DIR


def test_catalog_suggestions_return_only_matching_brand_category_and_products() -> None:
    session = _seed_example_session()
    es_result = ElasticsearchCatalogSuggestionResult(
        documents=(
            CatalogSuggestionDocument(
                product_id="prod_001",
                product_name="자작나무 수분 크림",
                brand_name="라운드랩",
                category_code="cream",
                category_group="skincare",
                category_name="cream",
            ),
        ),
        suggested_queries=(),
        attempted=True,
        duration_ms=2,
        index_alias="test_catalog_products_current",
    )

    execution = get_catalog_suggestions_response(
        session,
        query="라운",
        limit=8,
        elasticsearch_suggestions=lambda *args, **kwargs: es_result,
    )

    assert execution.backend == "elasticsearch"
    assert [(item.type.value, item.text) for item in execution.response.items] == [
        ("BRAND", "라운드랩"),
        ("PRODUCT", "자작나무 수분 크림"),
    ]


def test_catalog_suggestions_use_bounded_database_fallback() -> None:
    session = _seed_example_session()

    execution = get_catalog_suggestions_response(
        session,
        query="수분",
        limit=8,
        elasticsearch_suggestions=_failed_es_suggestions,
    )

    assert execution.backend == "database"
    assert execution.fallback_used is True
    assert [(item.type.value, item.product_id) for item in execution.response.items] == [
        ("CATEGORY", None),
        ("PRODUCT", "prod_001"),
    ]


def test_catalog_suggestions_expose_correction_as_suggestion_only() -> None:
    session = _seed_example_session()

    execution = get_catalog_suggestions_response(
        session,
        query="선 크림",
        limit=8,
        elasticsearch_suggestions=_failed_es_suggestions,
    )

    assert execution.response.query == "선 크림"
    assert execution.response.items[0].type.value == "CORRECTION"
    assert execution.response.items[0].text == "선크림"


def test_database_suggestions_match_compact_spacing() -> None:
    session = _seed_example_session()

    execution = get_catalog_suggestions_response(
        session,
        query="수분 크림",
        limit=8,
        elasticsearch_suggestions=_failed_es_suggestions,
    )

    product_items = [item for item in execution.response.items if item.type.value == "PRODUCT"]
    assert [item.product_id for item in product_items] == ["prod_001"]


def test_database_suggestion_prefix_does_not_match_middle_of_word() -> None:
    document = CatalogSuggestionDocument(
        product_id="prod_brown",
        product_name="내추럴 브라운 헤어 컬러",
        brand_name="테스트",
        category_code="haircare",
        category_group="haircare",
        category_name="haircare",
    )

    assert _document_matches_prefix(document, "라운") is False
    assert _document_matches_prefix(document, "브라") is True


def _failed_es_suggestions(*args, **kwargs) -> ElasticsearchCatalogSuggestionResult:
    return ElasticsearchCatalogSuggestionResult(
        documents=(),
        suggested_queries=(),
        attempted=True,
        duration_ms=2,
        index_alias="test_catalog_products_current",
        failure_reason="index missing",
    )


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
