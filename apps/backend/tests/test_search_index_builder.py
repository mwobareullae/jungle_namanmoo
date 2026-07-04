from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.search import SearchDocument
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.search_index_builder import DOCUMENT_CODE_PREFIX, build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_build_product_search_index_documents_dry_run_does_not_write_documents() -> None:
    session = _seed_example_session()

    result = build_product_search_index_documents(session, dry_run=True)

    assert result.scanned == 2
    assert result.upserted == 2
    assert result.unchanged == 0
    assert result.dry_run is True
    assert _search_document_count(session) == 4


def test_build_product_search_index_documents_creates_join_documents() -> None:
    session = _seed_example_session()

    result = build_product_search_index_documents(session)

    assert result.scanned == 2
    assert result.upserted == 2
    assert result.unchanged == 0
    assert _search_document_count(session) == 6

    document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()

    assert document.document_type == "product"
    assert document.product_id is not None
    assert document.ingredient_id is None
    assert document.ingredient_evidence_id is None
    assert document.title == "라운드랩 자작나무 수분 크림"
    assert "성분 조인 요약" in document.content
    assert "판테놀" in document.content
    assert "장벽 강화" in document.content
    assert "보습" in document.content
    assert "cream" in document.keywords


def test_build_product_search_index_documents_is_idempotent() -> None:
    session = _seed_example_session()

    build_product_search_index_documents(session)
    result = build_product_search_index_documents(session)

    assert result.scanned == 2
    assert result.upserted == 0
    assert result.unchanged == 2
    assert _search_document_count(session) == 6


def test_build_product_search_index_documents_resets_embedding_when_content_changes() -> None:
    session = _seed_example_session()
    build_product_search_index_documents(session)
    document = session.execute(
        select(SearchDocument).where(SearchDocument.document_code == f"{DOCUMENT_CODE_PREFIX}prod_001")
    ).scalar_one()
    document.embedding = "[0.1,0.2]"
    document.embedding_model = "local-test"
    document.embedding_dimensions = 2
    session.flush()

    product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
    product.product_name = "자작나무 수분 크림 리뉴얼"
    result = build_product_search_index_documents(session)

    assert result.upserted == 1
    assert result.unchanged == 1
    assert document.embedding is None
    assert document.embedding_model is None
    assert document.embedding_dimensions is None
    assert document.title == "라운드랩 자작나무 수분 크림 리뉴얼"


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session


def _search_document_count(session: Session) -> int:
    return session.execute(select(func.count()).select_from(SearchDocument)).scalar_one()
