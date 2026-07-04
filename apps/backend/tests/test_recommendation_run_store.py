from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import (
    RecommendationResult,
    RecommendationRun,
    RecommendationRunConcern,
    RecommendationRunConstraint,
    RecommendationScoreEvidence,
    SearchCandidate,
)
from app.schemas.recommendation import RecommendationRequest
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.recommendation_pipeline import create_recommendation_response
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_run_store import (
    cleanup_expired_recommendation_runs,
    save_recommendation_run,
)
from app.services.repository import load_repository
from tests.test_data_loader import EXAMPLES_DIR


def test_save_recommendation_run_persists_run_context_constraints_and_concerns() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(
        "속건조 보습 세럼 2만원 이하 추천",
        repository=repository,
    )
    now = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)

    saved = save_recommendation_run(
        session,
        intent,
        skin_type="수부지",
        sensitivity="민감",
        avoid_ingredients=["향료"],
        recommendation_code="rec_store_test",
        now=now,
    )

    assert saved.run.recommendation_code == "rec_store_test"
    assert saved.run.concern_text == "속건조 보습 세럼 2만원 이하 추천"
    assert saved.run.skin_type == "수부지"
    assert saved.run.sensitivity == "민감"
    assert saved.run.avoid_ingredients == ["향료"]
    assert saved.run.expires_at == now + timedelta(hours=24)
    assert saved.run.scoring_version == "v0"
    assert saved.run.parser_result["concerns"][0]["tag_id"] == "concern_dryness"
    assert saved.run.parser_result["effects"][0]["effect_id"] == "effect_moisturizing"
    assert saved.run.request_context["purchase_conditions"]["categories"][0]["category_code"] == "serum"
    assert saved.run.request_context["purchase_conditions"]["price_max"] == 20000

    constraints = _load_constraints(session, saved.run.id)
    assert [constraint.constraint_type for constraint in constraints] == ["category", "price_max"]
    assert constraints[0].operator == "eq"
    assert constraints[0].normalized_value == "serum"
    assert constraints[0].category_id is not None
    assert constraints[1].operator == "lte"
    assert constraints[1].numeric_value == Decimal("20000")

    concerns = _load_concerns(session, saved.run.id)
    assert len(concerns) == 1
    assert concerns[0].matched_text == "속건조"
    assert concerns[0].confidence == Decimal("1.0000")


def test_save_recommendation_run_persists_brand_category_and_default_inputs() -> None:
    session = _seed_example_session()
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(
        "라운드랩 건조 크림 추천",
        repository=repository,
    )

    saved = save_recommendation_run(
        session,
        intent,
        skin_type="",
        sensitivity=None,
        avoid_ingredients=[" ", "알코올", ""],
        recommendation_code="rec_store_defaults",
        now=datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC),
    )

    assert saved.run.skin_type == "중성"
    assert saved.run.sensitivity == "보통"
    assert saved.run.avoid_ingredients == ["알코올"]

    constraints = _load_constraints(session, saved.run.id)
    assert [constraint.constraint_type for constraint in constraints] == ["category", "brand"]
    assert constraints[0].category_id is not None
    assert constraints[0].normalized_value == "cream"
    assert constraints[1].brand_id is not None
    assert constraints[1].normalized_value == "라운드랩"


def test_cleanup_expired_recommendation_runs_deletes_run_and_children() -> None:
    session = _seed_example_session()
    now = datetime(2026, 6, 29, 4, 0, 0, tzinfo=UTC)
    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="?띻굔議?蹂댁뒿 異붿쿇"),
        commit=False,
    )
    run = _load_run(session, response.recommendation_id)
    run.expires_at = now - timedelta(seconds=1)
    session.flush()

    dry_run = cleanup_expired_recommendation_runs(session, now=now, dry_run=True)

    assert dry_run.dry_run is True
    assert dry_run.recommendation_runs == 1
    assert dry_run.search_candidates > 0
    assert dry_run.recommendation_results > 0
    assert _count_rows(session, RecommendationRun) == 1

    result = cleanup_expired_recommendation_runs(session, now=now)

    assert result.dry_run is False
    assert result.recommendation_runs == 1
    assert _count_rows(session, RecommendationScoreEvidence) == 0
    assert _count_rows(session, RecommendationResult) == 0
    assert _count_rows(session, SearchCandidate) == 0
    assert _count_rows(session, RecommendationRunConstraint) == 0
    assert _count_rows(session, RecommendationRunConcern) == 0
    assert _count_rows(session, RecommendationRun) == 0


def test_create_recommendation_response_persists_candidate_pool_diagnostics() -> None:
    session = _seed_example_session()

    response = create_recommendation_response(
        session,
        RecommendationRequest(concern_text="속건조 보습 추천"),
        result_limit=10,
        candidate_pool_limit=20,
        commit=False,
    )

    run = _load_run(session, response.recommendation_id)
    diagnostics = run.request_context["candidate_pool_diagnostics"]

    assert diagnostics["candidate_generation_version"] == "legacy_id_order_v0"
    assert diagnostics["strategy"] == "legacy_id_order"
    assert diagnostics["requested_candidate_pool_limit"] == 20
    assert diagnostics["result_limit"] == 10
    assert diagnostics["loaded_candidate_count"] == 2
    assert diagnostics["avoid_filtered_count"] == 0
    assert diagnostics["after_avoid_filter_count"] == 2
    assert diagnostics["search_match_count"] == 2
    assert diagnostics["scored_candidate_count"] == 2
    assert diagnostics["final_result_count"] == 2
    assert diagnostics["source_counts"] == {"legacy_id_order": 2}
    assert diagnostics["fallback_used"] is False
    assert diagnostics["hard_filter_total_count"] is None


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session


def _load_run(session: Session, recommendation_code: str) -> RecommendationRun:
    return session.execute(
        select(RecommendationRun).where(
            RecommendationRun.recommendation_code == recommendation_code,
        )
    ).scalar_one()


def _count_rows(
    session: Session,
    model: type[
        RecommendationRun
        | RecommendationRunConstraint
        | RecommendationRunConcern
        | SearchCandidate
        | RecommendationResult
        | RecommendationScoreEvidence
    ],
) -> int:
    return len(session.execute(select(model.id)).scalars().all())


def _load_constraints(
    session: Session,
    recommendation_run_id: int,
) -> list[RecommendationRunConstraint]:
    return list(
        session.execute(
            select(RecommendationRunConstraint)
            .where(RecommendationRunConstraint.recommendation_run_id == recommendation_run_id)
            .order_by(RecommendationRunConstraint.id.asc())
        ).scalars()
    )


def _load_concerns(
    session: Session,
    recommendation_run_id: int,
) -> list[RecommendationRunConcern]:
    return list(
        session.execute(
            select(RecommendationRunConcern)
            .where(RecommendationRunConcern.recommendation_run_id == recommendation_run_id)
            .order_by(RecommendationRunConcern.id.asc())
        ).scalars()
    )
