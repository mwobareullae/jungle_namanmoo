from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric, Wishlist
from app.db.models.skin import BaumannTypeProfile, SkinProfile, SkinTestResult
from app.db.models.review import ProductReviewMetric, ProductReviewSegmentMetric
from app.db.models.taxonomy import Ingredient, RiskFlag
from app.db.session import make_engine
from app.services.parser import ParsedEffect
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_intent import RecommendationIntent
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_pipeline import score_breakdown_to_api
from app.services.repository import load_repository
from app.services.scoring import (
    SCORING_VERSION,
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
    assert SCORING_VERSION == "v6_independent_evidence_top3"
    assert len(SCORING_VERSION) <= 40
    assert top.rank == 1
    assert top.total_score > 70
    assert top.score_breakdown["ingredient_effect_score"] == pytest.approx(1.0)
    assert top.score_breakdown["ingredient_evidence_score"] == pytest.approx(0.9478)
    assert top.score_breakdown["ingredient_effect_selection_policy"] == "top3_effect_score"
    assert (
        top.score_breakdown["ingredient_evidence_selection_policy"]
        == "independent_top3_effective_evidence_score"
    )
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
    assert breakdown["base_weights"]["search_match"] == pytest.approx(0.123364486)
    assert breakdown["weights"]["search_match"] == pytest.approx(0.1356350185)
    assert breakdown["base_weights"]["review_quality"] == pytest.approx(0.07)
    assert breakdown["base_weights"]["review_profile_affinity"] == pytest.approx(0.05)
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
    assert breakdown["base_weights"]["search_match"] == pytest.approx(0.06)
    assert breakdown["weights"]["search_match"] == pytest.approx(0.0674157303)
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
    assert first_breakdown["applied_multipliers"]["market_signal"] == pytest.approx(1.0)
    assert first_breakdown["applied_multipliers"]["review_quality"] == pytest.approx(1.485)
    assert first_breakdown["applied_multipliers"]["review_profile_affinity"] == pytest.approx(1.84)
    assert (
        first_breakdown["weights"]["review_quality"]
        + first_breakdown["weights"]["review_profile_affinity"]
    ) == pytest.approx(0.18)
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


def test_score_candidates_applies_review_quality_as_independent_axis() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    baseline = {
        product.product_id: product
        for product in score_candidates(session, intent, candidates, matches)
    }
    _add_review_metrics(
        session,
        quality_by_product={"prod_001": 0.9, "prod_002": 0.1},
    )

    scored = {
        product.product_id: product
        for product in score_candidates(session, intent, candidates, matches)
    }

    first = scored["prod_001"].score_breakdown
    second = scored["prod_002"].score_breakdown
    assert first["review_quality_applied"] is True
    assert first["review_quality_score"] == pytest.approx(0.9)
    assert first["review_quality_confidence"] == pytest.approx(0.8)
    assert first["review_count"] == 100
    assert second["review_quality_score"] == pytest.approx(0.1)
    assert scored["prod_001"].total_score > baseline["prod_001"].total_score
    assert scored["prod_002"].total_score < baseline["prod_002"].total_score


def test_score_candidates_uses_review_segments_and_neutralizes_small_samples() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감하고 진정 위주 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    _add_review_metrics(
        session,
        quality_by_product={"prod_001": 0.5, "prod_002": 0.5},
    )
    _add_review_segment(
        session,
        "prod_001",
        "SKIN_CONCERN",
        "concern_sensitive",
        score=0.7,
        effective_sample_size=10,
    )
    _add_review_segment(
        session,
        "prod_002",
        "SKIN_CONCERN",
        "concern_sensitive",
        score=0.95,
        effective_sample_size=4,
    )

    scored = {
        product.product_id: product
        for product in score_candidates(session, intent, candidates, matches)
    }

    first = scored["prod_001"].score_breakdown
    second = scored["prod_002"].score_breakdown
    assert first["review_profile_affinity_applied"] is True
    assert first["review_profile_affinity_dimensions"]["SKIN_CONCERN"] == pytest.approx(0.7)
    assert first["review_profile_affinity_score"] == pytest.approx(0.57)
    assert second["review_profile_affinity_applied"] is False
    assert second["review_profile_affinity_score"] == pytest.approx(0.5)
    assert second["review_profile_matched_segments"][0] == {
        "dimension": "SKIN_CONCERN",
        "value_code": "concern_sensitive",
        "strength": 1.0,
        "segment_score": 0.95,
        "applied_score": 0.5,
        "effective_sample_size": 4.0,
        "review_count": 10,
        "eligible": False,
        "sources": ["query_concern"],
    }


def test_review_affinity_records_manual_saved_and_skin_test_strengths() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent("민감 진정 추천", repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    _add_review_metrics(session, quality_by_product={"prod_001": 0.5})
    for dimension, value_code in (
        ("SKIN_TYPE", "dry"),
        ("SKIN_TYPE", "oily"),
        ("SENSITIVITY", "high"),
        ("SKIN_CONCERN", "concern_sensitive"),
        ("SKIN_CONCERN", "concern_pore"),
        ("SKIN_CONCERN", "concern_brightening_spots"),
        ("SKIN_CONCERN", "concern_wrinkle_elasticity"),
    ):
        _add_review_segment(
            session,
            "prod_001",
            dimension,
            value_code,
            score=0.6,
            effective_sample_size=10,
        )

    scored = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
        skin_test_context=_skin_test_context(),
        saved_concerns=("concern_pore",),
        manual_skin_type_explicit=True,
    )
    breakdown = next(
        product.score_breakdown for product in scored if product.product_id == "prod_001"
    )
    matched = {
        (item["dimension"], item["value_code"]): item
        for item in breakdown["review_profile_matched_segments"]
    }

    assert matched[("SKIN_TYPE", "dry")]["strength"] == pytest.approx(1.0)
    assert matched[("SKIN_TYPE", "dry")]["sources"] == ["manual_skin_type"]
    assert matched[("SKIN_TYPE", "oily")]["strength"] == pytest.approx(0.25)
    assert matched[("SKIN_TYPE", "oily")]["sources"] == ["skin_test"]
    assert matched[("SKIN_CONCERN", "concern_pore")]["strength"] == pytest.approx(0.75)
    assert matched[("SKIN_CONCERN", "concern_pore")]["sources"] == ["saved_concern"]
    assert matched[("SKIN_CONCERN", "concern_sensitive")]["strength"] == pytest.approx(1.0)
    assert matched[("SKIN_CONCERN", "concern_sensitive")]["sources"] == [
        "query_concern",
        "skin_test",
    ]


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


def test_score_breakdown_api_exposes_review_context() -> None:
    breakdown = score_breakdown_to_api(
        {
            "review_quality_score": 0.73,
            "review_quality_applied": True,
            "review_quality_confidence": 0.81,
            "review_count": 120,
            "review_profile_affinity_score": 0.61,
            "review_profile_affinity_applied": True,
            "review_profile_affinity_dimensions": {"SKIN_CONCERN": 0.7},
            "review_profile_matched_segments": [
                {
                    "dimension": "SKIN_CONCERN",
                    "value_code": "concern_sensitive",
                    "strength": 1.0,
                    "segment_score": 0.7,
                    "applied_score": 0.7,
                    "effective_sample_size": 14.25,
                    "review_count": 18,
                    "eligible": True,
                    "sources": ["query_concern"],
                }
            ],
        }
    )

    assert breakdown.review_quality_score == 73
    assert breakdown.review_quality_confidence == 81
    assert breakdown.review_count == 120
    assert breakdown.review_profile_affinity_score == 61
    assert breakdown.review_profile_affinity_dimensions == {"SKIN_CONCERN": 70}
    assert breakdown.review_profile_matched_segments[0].effective_sample_size == 14.25
    assert breakdown.review_profile_matched_segments[0].strength == 100


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


def _add_review_metrics(
    session: Session,
    *,
    quality_by_product: dict[str, float],
) -> None:
    for product_code, quality_score in quality_by_product.items():
        product = session.execute(
            select(Product).where(Product.product_code == product_code)
        ).scalar_one()
        session.add(
            ProductReviewMetric(
                product_id=product.id,
                review_count=100,
                rating_count=100,
                confidence=Decimal("0.8"),
                review_quality_score=Decimal(str(quality_score)),
            )
        )
    session.flush()


def _add_review_segment(
    session: Session,
    product_code: str,
    dimension: str,
    value_code: str,
    *,
    score: float,
    effective_sample_size: float,
) -> None:
    product = session.execute(
        select(Product).where(Product.product_code == product_code)
    ).scalar_one()
    session.add(
        ProductReviewSegmentMetric(
            product_id=product.id,
            dimension=dimension,
            value_code=value_code,
            review_count=10,
            rating_count=10,
            effective_sample_size=Decimal(str(effective_sample_size)),
            total_affinity_score=Decimal(str(score)),
        )
    )
    session.flush()
