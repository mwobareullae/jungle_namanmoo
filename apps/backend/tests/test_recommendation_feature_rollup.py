from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Wishlist
from app.db.models.recommendation import (
    ProductEffectRecommendationFeature,
    ProductRecommendationFeature,
    UserPreferenceProfile,
)
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
from app.services.recommendation_feature_versions import (
    PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION,
    PRODUCT_RECOMMENDATION_FEATURE_VERSION,
    USER_PREFERENCE_PROFILE_VERSION,
)
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from app.services.scoring import (
    _load_candidate_scoring_bundles,
    load_behavior_personalization_context,
    score_candidates,
)
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from app.services.user_preference_profile_rollup import (
    rollup_user_preference_profiles,
)
from tests.test_data_loader import EXAMPLES_DIR


def test_product_feature_rollup_is_idempotent() -> None:
    session = _seed_example_session()
    computed_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)

    first = rollup_product_recommendation_features(
        session,
        batch_size=1,
        computed_at=computed_at,
    )
    session.commit()
    first_snapshot = _product_feature_snapshot(session)
    second = rollup_product_recommendation_features(
        session,
        batch_size=2,
        computed_at=computed_at,
    )
    session.commit()

    assert first.product_count == second.product_count == 2
    assert first.product_feature_count == second.product_feature_count == 2
    assert first.effect_feature_count == second.effect_feature_count == 6
    assert _product_feature_snapshot(session) == first_snapshot
    assert session.query(ProductRecommendationFeature).count() == 2
    assert session.query(ProductEffectRecommendationFeature).count() == 6


def test_precomputed_scoring_preserves_rank_score_and_top_explanation() -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
    )
    rollup_product_recommendation_features(session)
    session.commit()
    diagnostics: dict[str, object] = {}

    scored = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
        result_limit=1,
        diagnostics=diagnostics,
    )

    assert _rank_and_score(scored) == _rank_and_score(baseline)
    assert scored[0].score_breakdown == baseline[0].score_breakdown
    assert scored[0].score_evidence == baseline[0].score_evidence
    assert scored[0].reason_summary == baseline[0].reason_summary
    assert scored[1].score_breakdown == {}
    assert scored[1].score_evidence == ()
    assert diagnostics["product_feature_hit_count"] == 2
    assert diagnostics["product_feature_miss_count"] == 0
    assert diagnostics["effect_feature_hit_count"] == 2
    assert diagnostics["effect_feature_miss_count"] == 0
    assert diagnostics["legacy_fallback_count"] == 0
    assert diagnostics["score_detail_count"] == 1


def test_candidate_scoring_bundle_loads_all_candidates_with_one_query() -> None:
    session = _seed_example_session()
    _intent, candidates, _matches = _recommendation_inputs(session)
    rollup_product_recommendation_features(session)
    session.commit()
    engine = session.get_bind()
    select_count = 0

    def count_selects(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        bundles, feature_miss_ids = _load_candidate_scoring_bundles(
            session,
            candidates,
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)

    candidate_ids = {candidate.db_product_id for candidate in candidates}
    assert set(bundles) == candidate_ids
    assert feature_miss_ids == set()
    assert select_count == 1


@pytest.mark.parametrize("fallback_mode", ["missing", "stale_product", "stale_effect"])
def test_product_feature_missing_or_stale_rows_fall_back_per_product(
    fallback_mode: str,
) -> None:
    session = _seed_example_session()
    intent, candidates, matches = _recommendation_inputs(session)
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
    )
    rollup_product_recommendation_features(session)
    session.commit()
    target_product_id = baseline[0].db_product_id
    if fallback_mode == "missing":
        session.execute(
            delete(ProductRecommendationFeature).where(
                ProductRecommendationFeature.product_id == target_product_id
            )
        )
    elif fallback_mode == "stale_product":
        row = session.get(ProductRecommendationFeature, target_product_id)
        assert row is not None
        row.feature_version = "stale"
    else:
        row = session.execute(
            select(ProductEffectRecommendationFeature)
            .where(
                ProductEffectRecommendationFeature.product_id
                == target_product_id
            )
            .limit(1)
        ).scalar_one()
        row.feature_version = "stale"
    session.commit()
    diagnostics: dict[str, object] = {}

    scored = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type="건성",
        sensitivity="보통",
        diagnostics=diagnostics,
    )

    assert _rank_and_score(scored) == _rank_and_score(baseline)
    assert [product.score_breakdown for product in scored] == [
        product.score_breakdown for product in baseline
    ]
    assert diagnostics["legacy_fallback_count"] == 1
    if fallback_mode == "stale_effect":
        assert diagnostics["effect_feature_miss_count"] == 1
    else:
        assert diagnostics["product_feature_miss_count"] == 1


def test_user_preference_rollup_is_idempotent_and_preserves_behavior_score() -> None:
    session = _seed_example_session()
    now = datetime.now(UTC)
    user = User(email="feature-rollup@example.com", display_name="feature-rollup")
    product = session.execute(
        select(Product).where(Product.product_code == "prod_002")
    ).scalar_one()
    session.add(user)
    session.flush()
    session.add(
        Wishlist(user_id=user.id, product_id=product.id, added_at=now)
    )
    session.flush()
    baseline_context = load_behavior_personalization_context(session, user.id)
    assert baseline_context is not None
    intent, candidates, matches = _recommendation_inputs(
        session,
        concern_text="민감하고 진정 위주 추천",
    )
    baseline = score_candidates(
        session,
        intent,
        candidates,
        matches,
        behavior_personalization_context=baseline_context,
    )

    first = rollup_user_preference_profiles(
        session,
        user_ids=(user.id,),
        computed_at=now,
    )
    session.commit()
    first_snapshot = _user_profile_snapshot(session, user.id)
    second = rollup_user_preference_profiles(
        session,
        user_ids=(user.id,),
        computed_at=now,
    )
    session.commit()
    diagnostics: dict[str, object] = {}
    precomputed_context = load_behavior_personalization_context(
        session,
        user.id,
        diagnostics=diagnostics,
    )
    assert precomputed_context is not None
    scored = score_candidates(
        session,
        intent,
        candidates,
        matches,
        behavior_personalization_context=precomputed_context,
    )

    assert first.profile_count == second.profile_count == 1
    assert _user_profile_snapshot(session, user.id) == first_snapshot
    assert diagnostics["user_profile_hit"] is True
    assert _rank_and_score(scored) == _rank_and_score(baseline)
    assert [
        product.score_breakdown["behavior_personalization_score"]
        for product in scored
    ] == [
        product.score_breakdown["behavior_personalization_score"]
        for product in baseline
    ]

    profile = session.execute(
        select(UserPreferenceProfile).where(
            UserPreferenceProfile.user_id == user.id
        )
    ).scalar_one()
    profile.profile_version = "stale"
    session.commit()
    fallback_diagnostics: dict[str, object] = {}
    fallback_context = load_behavior_personalization_context(
        session,
        user.id,
        diagnostics=fallback_diagnostics,
    )

    assert fallback_context is not None
    assert fallback_diagnostics["user_profile_hit"] is False
    assert fallback_diagnostics["legacy_fallback_count"] == 1
    assert fallback_context.source_profiles == baseline_context.source_profiles


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session


def _recommendation_inputs(
    session: Session,
    *,
    concern_text: str = "속건조 보습 추천",
):
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(concern_text, repository=repository)
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    return intent, candidates, matches


def _rank_and_score(products) -> list[tuple[str, int, float]]:
    return [
        (product.product_id, product.rank, product.total_score)
        for product in products
    ]


def _product_feature_snapshot(session: Session) -> tuple[list[tuple], list[tuple]]:
    product_rows = session.execute(
        select(ProductRecommendationFeature).order_by(
            ProductRecommendationFeature.product_id
        )
    ).scalars()
    effect_rows = session.execute(
        select(ProductEffectRecommendationFeature).order_by(
            ProductEffectRecommendationFeature.product_id,
            ProductEffectRecommendationFeature.effect_id,
        )
    ).scalars()
    return (
        [
            (
                row.product_id,
                row.top_ingredient_codes,
                row.top_effect_codes,
                row.feature_version,
                row.computed_at,
            )
            for row in product_rows
        ],
        [
            (
                row.product_id,
                row.effect_id,
                row.ingredient_effect_score,
                row.ingredient_evidence_score,
                row.concentration_score,
                row.concentration_context,
                row.top_ingredient_ids,
                row.best_evidence_ids,
                row.feature_version,
                row.computed_at,
            )
            for row in effect_rows
        ],
    )


def _user_profile_snapshot(session: Session, user_id: int) -> list[tuple]:
    rows = session.execute(
        select(UserPreferenceProfile)
        .where(UserPreferenceProfile.user_id == user_id)
        .order_by(UserPreferenceProfile.source)
    ).scalars()
    return [
        (
            row.source,
            row.category_scores,
            row.brand_scores,
            row.ingredient_scores,
            row.effect_scores,
            row.price_band_scores,
            row.product_ids,
            row.total_weight,
            row.effect_top3_sum,
            row.ingredient_top5_sum,
            row.category_max,
            row.brand_max,
            row.price_band_max,
            row.event_count,
            row.last_event_at,
            row.profile_version,
            row.computed_at,
        )
        for row in rows
    ]


def test_feature_version_constants_fit_database_columns() -> None:
    assert len(PRODUCT_RECOMMENDATION_FEATURE_VERSION) <= 64
    assert len(PRODUCT_EFFECT_RECOMMENDATION_FEATURE_VERSION) <= 64
    assert len(USER_PREFERENCE_PROFILE_VERSION) <= 64
