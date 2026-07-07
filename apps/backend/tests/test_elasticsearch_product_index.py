from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.elasticsearch_product_index import (
    build_products_index_name,
    index_products_to_elasticsearch,
)
from app.services.search_index_builder import build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_build_products_index_name_uses_prefix_and_suffix() -> None:
    assert build_products_index_name("v1").endswith("_products_v1")


def test_index_products_to_elasticsearch_dry_run_counts_join_documents() -> None:
    session = _seed_example_session()

    result = index_products_to_elasticsearch(
        session,
        index_suffix="test",
        dry_run=True,
    )

    assert result.scanned == 2
    assert result.indexed == 0
    assert result.failed == 0
    assert result.index_name.endswith("_products_test")
    assert result.dry_run is True
    assert result.alias_swapped is False


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session
