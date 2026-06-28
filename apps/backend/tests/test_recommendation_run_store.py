from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import (
    RecommendationRunConcern,
    RecommendationRunConstraint,
)
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_run_store import save_recommendation_run
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


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    return session


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
