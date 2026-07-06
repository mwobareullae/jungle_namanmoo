from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.recommendation import RecommendationResult, RecommendationScoreEvidence
from app.db.session import make_engine
from app.services.db_seed import seed_database
from app.services.product_candidates import list_product_candidates
from app.services.recommendation_intent import build_recommendation_intent
from app.services.recommendation_result_store import save_recommendation_results
from app.services.recommendation_run_store import save_recommendation_run
from app.services.repository import load_repository
from app.services.scoring import ScoredProduct, score_candidates
from app.services.search_index_builder import build_product_search_index_documents
from app.services.search_matching import match_product_search_documents
from tests.test_data_loader import EXAMPLES_DIR


def test_save_recommendation_results_persists_scores_and_evidence() -> None:
    session = _seed_example_session()
    run_id, scored_products = _build_scored_products(
        session,
        "속건조 보습 추천",
        skin_type="건성",
        sensitivity="보통",
    )

    saved = save_recommendation_results(session, run_id, scored_products)

    assert [row.rank_order for row in saved.results] == [1, 2]
    assert [row.product_id for row in saved.results] == [
        scored_products[0].db_product_id,
        scored_products[1].db_product_id,
    ]
    assert saved.results[0].total_score == _score_to_decimal(scored_products[0].total_score)
    assert saved.results[0].score_breakdown["scoring_version"] == "v0"
    assert "skin_profile_score" in saved.results[0].score_breakdown
    assert len(saved.evidence) > 0
    assert len(saved.evidence) <= len(saved.results) * 3
    assert saved.evidence[0].recommendation_result_id == saved.results[0].id
    assert saved.evidence[0].ingredient_id is not None
    assert saved.evidence[0].effect_id is not None
    assert saved.evidence[0].contribution_score is not None


def test_save_recommendation_results_replaces_existing_run_results() -> None:
    session = _seed_example_session()
    run_id, scored_products = _build_scored_products(
        session,
        "민감하고 진정 위주 추천",
        skin_type="지성",
        sensitivity="민감",
    )

    save_recommendation_results(session, run_id, scored_products)
    save_recommendation_results(session, run_id, scored_products[:1], result_limit=1)

    result_rows = _load_results(session, run_id)
    evidence_rows = session.execute(
        select(RecommendationScoreEvidence)
        .join(RecommendationResult, RecommendationScoreEvidence.recommendation_result_id == RecommendationResult.id)
        .where(RecommendationResult.recommendation_run_id == run_id)
    ).scalars().all()

    assert len(result_rows) == 1
    assert result_rows[0].rank_order == 1
    assert result_rows[0].product_id == scored_products[0].db_product_id
    assert all(evidence.recommendation_result_id == result_rows[0].id for evidence in evidence_rows)


def test_save_recommendation_results_applies_result_and_evidence_limits() -> None:
    session = _seed_example_session()
    run_id, scored_products = _build_scored_products(
        session,
        "속건조 보습 추천",
        skin_type="건성",
        sensitivity="보통",
    )

    saved = save_recommendation_results(
        session,
        run_id,
        scored_products,
        result_limit=1,
        evidence_limit_per_result=1,
    )

    assert len(saved.results) == 1
    assert len(saved.evidence) <= 1
    assert _load_results(session, run_id) == list(saved.results)


def _build_scored_products(
    session: Session,
    concern_text: str,
    *,
    skin_type: str,
    sensitivity: str,
) -> tuple[int, list[ScoredProduct]]:
    repository = load_repository(EXAMPLES_DIR)
    intent = build_recommendation_intent(concern_text, repository=repository)
    saved_run = save_recommendation_run(
        session,
        intent,
        skin_type=skin_type,
        sensitivity=sensitivity,
        recommendation_code=f"rec_test_{abs(hash((concern_text, skin_type, sensitivity)))}",
    )
    candidates = list_product_candidates(session, intent.purchase_conditions)
    matches = match_product_search_documents(session, intent, candidates)
    scored_products = score_candidates(
        session,
        intent,
        candidates,
        matches,
        skin_type=skin_type,
        sensitivity=sensitivity,
    )
    return saved_run.run.id, scored_products


def _seed_example_session() -> Session:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_database(session, EXAMPLES_DIR)
    build_product_search_index_documents(session)
    return session


def _load_results(session: Session, recommendation_run_id: int) -> list[RecommendationResult]:
    return session.execute(
        select(RecommendationResult)
        .where(RecommendationResult.recommendation_run_id == recommendation_run_id)
        .order_by(RecommendationResult.rank_order.asc())
    ).scalars().all()


def _score_to_decimal(score: float) -> Decimal:
    return Decimal(str(score)).quantize(Decimal("0.01"))
