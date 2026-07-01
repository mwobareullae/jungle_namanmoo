import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.taxonomy import Ingredient, RiskFlag
from app.db.session import make_engine
from app.services.parser import ParsedEffect
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent
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
    assert top.total_score > 80
    assert top.score_breakdown["ingredient_effect_score"] == pytest.approx(1.0)
    assert top.score_breakdown["ingredient_evidence_score"] == pytest.approx(0.9478)
    assert top.score_breakdown["skin_profile_score"] == pytest.approx(0.788)
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
    assert scored_by_id["prod_002"].score_breakdown["skin_profile_score"] == pytest.approx(0.82)
    assert scored_by_id["prod_001"].score_breakdown["skin_profile_score"] <= 0.5
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


def test_score_candidates_adds_concentration_fit_bonus() -> None:
    session = _seed_example_session()
    intent = RecommendationIntent(
        concern_text="sebum",
        normalized_text="sebum",
        purchase_conditions=ParsedPurchaseConditions(
            categories=(),
            brands=(),
            price_min=None,
            price_max=None,
            price_text=None,
            price_max_text=None,
        ),
        concerns=(),
        effects=(ParsedEffect(effect_id="effect_sebum_control", name="sebum", weight=1.0),),
        excluded_concerns=(),
        priority_effects=(),
        unmatched_terms=(),
        needs_llm=False,
    )
    candidates = list_product_candidates(session, intent.purchase_conditions)

    scored_products = score_candidates(session, intent, candidates, [])
    scored_by_id = {product.product_id: product for product in scored_products}

    assert scored_by_id["prod_002"].score_breakdown["concentration_fit_score"] == pytest.approx(0.9)
    assert scored_by_id["prod_002"].score_breakdown["concentration_bucket"] == "optimal"
    assert scored_by_id["prod_001"].score_breakdown["concentration_fit_score"] == pytest.approx(0.5)


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


def test_score_candidates_adds_functional_claim_score_when_claim_matches_effect() -> None:
    session = _seed_example_session()
    product = session.execute(
        select(Product).where(Product.product_code == "prod_002")
    ).scalar_one()
    product.functional_cosmetic_claims = "미백"
    product.functional_claim_confidence = "high"
    session.flush()

    intent = RecommendationIntent(
        concern_text="brightening",
        normalized_text="brightening",
        purchase_conditions=ParsedPurchaseConditions(
            categories=(),
            brands=(),
            price_min=None,
            price_max=None,
            price_text=None,
            price_max_text=None,
        ),
        concerns=(),
        effects=(ParsedEffect(effect_id="effect_brightening", name="brightening", weight=1.0),),
        excluded_concerns=(),
        priority_effects=(ParsedEffect(effect_id="effect_brightening", name="brightening", weight=1.0),),
        unmatched_terms=(),
        needs_llm=False,
    )

    candidates = list_product_candidates(session, intent.purchase_conditions)
    scored_products = score_candidates(session, intent, candidates, [])
    scored_by_id = {product.product_id: product for product in scored_products}

    assert scored_by_id["prod_002"].score_breakdown["functional_claim_score"] == pytest.approx(1.0)
    assert scored_by_id["prod_002"].score_breakdown["functional_matched_claims"] == ["미백"]


def test_score_candidates_penalizes_sensitive_user_only_for_sensitive_risk_flags() -> None:
    session = _seed_example_session()
    ingredient = session.execute(
        select(Ingredient).where(Ingredient.ingredient_code == "ing_heartleaf")
    ).scalar_one()
    session.add(
        RiskFlag(
            ingredient_id=ingredient.id,
            risk_type="irritation",
            display_text="민감 피부 주의",
            severity="high",
            severity_score=0.8,
            applies_to="sensitive",
            condition="민감 피부",
            source_type="official",
        )
    )
    session.flush()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    normal_scores = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="지성",
        sensitivity="보통",
    )
    sensitive_scores = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="지성",
        sensitivity="민감",
    )
    normal_by_id = {product.product_id: product for product in normal_scores}
    sensitive_by_id = {product.product_id: product for product in sensitive_scores}

    assert normal_by_id["prod_002"].score_breakdown["risk_penalty"] == 0.0
    assert sensitive_by_id["prod_002"].score_breakdown["risk_penalty"] == pytest.approx(6.0)
    assert sensitive_by_id["prod_002"].score_breakdown["risk_warnings"] == ["민감 피부 주의"]


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session
