from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_match_product_search_documents_scores_matching_product_without_filtering() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)

    matches = match_product_search_documents(session, intent, candidates)

    assert [match.product_id for match in matches] == ["prod_001", "prod_002"]
    matches_by_id = {match.product_id: match for match in matches}
    assert matches_by_id["prod_001"].keyword_score > matches_by_id["prod_002"].keyword_score
    assert matches_by_id["prod_001"].vector_score == 0.0
    assert matches_by_id["prod_001"].search_match_score == matches_by_id["prod_001"].keyword_score
    assert set(matches_by_id["prod_001"].matched_terms) >= {"보습", "장벽 강화"}
    assert matches_by_id["prod_002"].matched_terms == ()


def test_match_product_search_documents_applies_priority_effect_weight() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("진정 위주 세럼 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)

    matches = match_product_search_documents(session, intent, candidates)

    assert [match.product_id for match in matches] == ["prod_002"]
    assert matches[0].keyword_score == 1.0
    assert matches[0].matched_terms == ("진정",)


def test_match_product_search_documents_keeps_zero_score_candidates() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("주름 탄력 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)

    matches = match_product_search_documents(session, intent, candidates)

    assert [match.product_id for match in matches] == ["prod_001", "prod_002"]
    assert all(match.search_match_score == 0.0 for match in matches)


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
