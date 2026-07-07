from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.pgvector_product_search import (
    _exact_keyword_bonus_sql,
    _query_terms,
    search_pgvector_product_candidates,
)
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from app.services.search_index_builder import build_product_search_index_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_search_pgvector_product_candidates_skips_non_postgres_sessions() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)

    result = search_pgvector_product_candidates(session, intent, limit=10)

    assert result.successful is False
    assert result.attempted is False
    assert result.product_db_ids == ()
    assert result.skipped_reason == "pgvector skipped for sqlite"


def test_query_terms_excludes_noisy_exact_bonus_terms() -> None:
    assert _query_terms("민감 피부 장벽 세럼 추천") == ("민감", "장벽")


def test_exact_keyword_bonus_sql_strips_brand_fields_before_matching() -> None:
    sql, params = _exact_keyword_bonus_sql(("피지", "토너"))

    assert "replace" in sql.lower()
    assert "b.name" in sql
    assert "b.brand_code" in sql
    assert "p.product_name" in sql
    assert "sd.title" in sql
    assert "sd.keywords" in sql
    assert params == {
        "exact_term_0": "%피지%",
        "exact_term_1": "%토너%",
    }


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session
