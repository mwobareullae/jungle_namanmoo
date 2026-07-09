from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric, Wishlist
from app.db.models.skin import BaumannTypeProfile, SkinProfile, SkinTestResult
from app.db.models.taxonomy import Ingredient, RiskFlag
from app.db.session import make_engine
from app.services.parser import ParsedEffect
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from app.services.scoring import (
    SkinTestScoringContext,
    load_behavior_personalization_context,
    load_skin_test_scoring_context,
    score_candidates,
)
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from app.services.skin_test_service import ensure_default_skin_test
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
    assert top.total_score > 79
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
        sensitivity="높음",
    )

    scored_by_id = {product.product_id: product for product in scored_products}
    assert (
        scored_by_id["prod_002"].score_breakdown["skin_profile_score"]
        > scored_by_id["prod_001"].score_breakdown["skin_profile_score"]
    )
    assert scored_by_id["prod_002"].score_breakdown["skin_profile_score"] == pytest.approx(0.82)
    assert scored_by_id["prod_001"].score_breakdown["skin_profile_score"] <= 0.5


def test_score_candidates_uses_price_condition_as_small_bonus() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("라운드랩 크림 2만원 이하 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(session, intent, candidates, matches)

    assert [product.product_id for product in scored_products] == ["prod_001"]
    assert scored_products[0].score_breakdown["price_score"] == pytest.approx(1.0)


def test_score_candidates_boosts_search_match_for_strong_search_intent() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("수분 진정 크림", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(session, intent, candidates, matches)

    assert scored_products
    breakdown = scored_products[0].score_breakdown
    assert breakdown["weight_profile"] == "search_intent_boost"
    assert breakdown["base_weights"]["search_match"] == pytest.approx(0.15)
    assert breakdown["weights"]["search_match"] == pytest.approx(0.15625)
    assert breakdown["weights"]["skin_test_context"] == pytest.approx(0.0)
    assert "category" in breakdown["search_intent_signals"]
    assert "search_terms" in breakdown["search_intent_signals"]


def test_score_candidates_keeps_default_weights_for_open_concern_query() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(session, intent, candidates, matches)

    assert scored_products
    breakdown = scored_products[0].score_breakdown
    assert breakdown["weight_profile"] == "default"
    assert breakdown["base_weights"]["search_match"] == pytest.approx(0.07)
    assert breakdown["weights"]["search_match"] == pytest.approx(0.0736842105)
    assert breakdown["weights"]["skin_test_context"] == pytest.approx(0.0)
    assert "category" not in breakdown["search_intent_signals"]


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
        sensitivity="높음",
    )
    normal_by_id = {product.product_id: product for product in normal_scores}
    sensitive_by_id = {product.product_id: product for product in sensitive_scores}

    assert normal_by_id["prod_002"].score_breakdown["risk_penalty"] == 0.0
    assert sensitive_by_id["prod_002"].score_breakdown["risk_penalty"] == pytest.approx(6.0)
    assert sensitive_by_id["prod_002"].score_breakdown["risk_warnings"] == ["민감 피부 주의"]


def test_score_candidates_applies_skin_test_context_and_market_signal() -> None:
    session = _seed_example_session()
    _add_popularity_metrics(session, {"prod_001": 20, "prod_002": 90})
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("?띻굔議?蹂댁뒿 異붿쿇", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    context = _skin_test_context(
        commerce_profile={
            "category_preference": {"code": "ampoule_serum_essence"},
            "buying_criteria": {"code": "review"},
            "decision_trigger": {"code": "similar_review"},
        },
    )

    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_test_context=context,
    )

    scored_by_id = {product.product_id: product for product in scored_products}
    first_breakdown = scored_products[0].score_breakdown
    assert first_breakdown["skin_test_context_applied"] is True
    assert first_breakdown["weights"]["skin_test_context"] > 0
    assert first_breakdown["applied_multipliers"]["market_signal"] == pytest.approx(4.0)
    assert scored_by_id["prod_002"].score_breakdown["market_signal_score"] == pytest.approx(0.9)
    assert (
        scored_by_id["prod_002"].score_breakdown["skin_test_context_score"]
        > scored_by_id["prod_001"].score_breakdown["skin_test_context_score"]
    )


def test_score_candidates_uses_value_preference_for_relative_price() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("?띻굔議?蹂댁뒿 異붿쿇", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    context = _skin_test_context(
        commerce_profile={
            "buying_criteria": {"code": "value"},
            "price_investment": {"code": "value_volume"},
        },
    )

    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_test_context=context,
    )

    scored_by_id = {product.product_id: product for product in scored_products}
    assert scored_products[0].score_breakdown["applied_multipliers"]["price"] == pytest.approx(1.8)
    assert (
        scored_by_id["prod_001"].score_breakdown["price_score"]
        > scored_by_id["prod_002"].score_breakdown["price_score"]
    )


def test_score_candidates_applies_behavior_personalization_from_wishlist() -> None:
    session = _seed_example_session()
    user = User(email="behavior-context@example.com", display_name="behavior-context")
    product = session.execute(
        select(Product).where(Product.product_code == "prod_002")
    ).scalar_one()
    session.add(user)
    session.flush()
    session.add(
        Wishlist(
            user_id=user.id,
            product_id=product.id,
            added_at=datetime.now(UTC),
        )
    )
    session.flush()

    behavior_context = load_behavior_personalization_context(session, user.id)
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("誘쇨컧?섍퀬 吏꾩젙 ?꾩＜ 異붿쿇", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)

    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        behavior_personalization_context=behavior_context,
    )

    scored_by_id = {product.product_id: product for product in scored_products}
    assert behavior_context is not None
    assert "wishlist" in behavior_context.source_profiles
    assert scored_by_id["prod_002"].score_breakdown["behavior_personalization_applied"] is True
    assert "wishlist" in scored_by_id["prod_002"].score_breakdown["behavior_personalization_sources"]
    assert scored_by_id["prod_002"].score_breakdown["weights"]["behavior_personalization"] > 0
    assert (
        scored_by_id["prod_002"].score_breakdown["behavior_personalization_score"]
        > scored_by_id["prod_001"].score_breakdown["behavior_personalization_score"]
    )


def test_load_skin_test_scoring_context_uses_latest_profile_result() -> None:
    session = _seed_example_session()
    version = ensure_default_skin_test(session)
    baumann_profile = session.execute(
        select(BaumannTypeProfile).where(BaumannTypeProfile.type_code == "OSPW")
    ).scalar_one()
    user = User(email="skin-test-context@example.com", display_name="skin-test-context")
    session.add(user)
    session.flush()
    result = SkinTestResult(
        result_code="skin-test-context-result",
        user_id=user.id,
        version_id=version.id,
        baumann_type_profile_id=baumann_profile.id,
        type_code=baumann_profile.type_code,
        mapped_skin_type=baumann_profile.mapped_skin_type,
        mapped_sensitivity=baumann_profile.mapped_sensitivity,
        axis_scores=_axis_scores(),
        commerce_profile={"buying_criteria": {"code": "ingredient"}},
        recommended_effect_ids=[],
    )
    session.add(result)
    session.flush()
    session.add(
        SkinProfile(
            user_id=user.id,
            skin_type=baumann_profile.mapped_skin_type,
            sensitivity=baumann_profile.mapped_sensitivity,
            latest_skin_test_result_id=result.id,
        )
    )
    session.flush()

    context = load_skin_test_scoring_context(session, user.id)

    assert context is not None
    assert context.result_id == result.id
    assert context.type_code == "OSPW"
    assert context.axis_scores["OD"]["winner"] == "O"
    assert context.commerce_profile["buying_criteria"]["code"] == "ingredient"


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session


def _skin_test_context(
    *,
    commerce_profile: dict | None = None,
    axis_scores: dict | None = None,
) -> SkinTestScoringContext:
    return SkinTestScoringContext(
        result_id=1,
        type_code="OSPW",
        mapped_skin_type="oily",
        mapped_sensitivity="높음",
        axis_scores=axis_scores or _axis_scores(),
        commerce_profile=commerce_profile or {},
    )


def _axis_scores() -> dict:
    return {
        "OD": {"O": 2, "D": 0, "winner": "O", "strength": "strong"},
        "SR": {"S": 2, "R": 0, "winner": "S", "strength": "strong"},
        "PN": {"P": 1, "N": 0, "winner": "P", "strength": "weak"},
        "WT": {"W": 1, "T": 0, "winner": "W", "strength": "weak"},
    }


def _add_popularity_metrics(session: Session, scores_by_product_code: dict[str, int]) -> None:
    for product_code, popularity_score in scores_by_product_code.items():
        product = session.execute(
            select(Product).where(Product.product_code == product_code)
        ).scalar_one()
        session.add(
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=popularity_score,
            )
        )
    session.flush()
