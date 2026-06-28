import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from app.services.scoring import score_candidates
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_score_candidates_prioritizes_ingredient_effect_and_evidence_data() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("속건조 보습 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
    )

    assert [product.product_id for product in scored_products] == ["prod_001", "prod_002"]
    top = scored_products[0]
    assert top.rank == 1
    assert top.total_score > 90
    assert top.score_breakdown["ingredient_effect_score"] == pytest.approx(1.0)
    assert top.score_breakdown["ingredient_evidence_score"] == pytest.approx(1.0)
    assert top.score_breakdown["skin_profile_score"] > 0.9
    assert top.score_breakdown["risk_penalty"] == 0.0
    assert set(top.key_ingredients) >= {"글리세린", "세라마이드엔피"}


def test_score_candidates_uses_skin_type_and_sensitivity_profile() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="지성",
        sensitivity="민감",
    )

    scored_by_id = {product.product_id: product for product in scored_products}
    assert scored_products[0].product_id == "prod_002"
    assert scored_by_id["prod_002"].score_breakdown["skin_profile_score"] == pytest.approx(1.0)
    assert scored_by_id["prod_001"].score_breakdown["skin_profile_score"] < 0.5
    assert scored_by_id["prod_002"].total_score > scored_by_id["prod_001"].total_score


def test_score_candidates_uses_price_condition_as_small_bonus() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("라운드랩 크림 2만원 이하 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(session, intent, candidates, matches)

    assert [product.product_id for product in scored_products] == ["prod_001"]
    assert scored_products[0].score_breakdown["price_score"] == pytest.approx(1.0)


def test_score_candidates_handles_purchase_only_query_without_effects() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("라운드랩 크림 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(session, intent, candidates, matches)

    assert [product.product_id for product in scored_products] == ["prod_001"]
    assert scored_products[0].score_breakdown["ingredient_effect_score"] == pytest.approx(0.0)
    assert scored_products[0].score_breakdown["ingredient_evidence_score"] == pytest.approx(0.0)
    assert 0 <= scored_products[0].total_score <= 100


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
