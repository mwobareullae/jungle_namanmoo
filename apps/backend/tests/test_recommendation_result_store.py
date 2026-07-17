from dataclasses import replace
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
from app.services.scoring import SCORING_VERSION, ScoredProduct, score_candidates
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

    timings: dict[str, float] = {}
    saved = save_recommendation_results(
        session,
        run_id,
        scored_products,
        timings=timings,
    )

    result_rows = _load_results(session, run_id)
    evidence_rows = _load_evidence(session, run_id)

    assert saved.result_count == 2
    assert saved.evidence_count == len(evidence_rows)
    assert [row.rank_order for row in result_rows] == [1, 2]
    assert [row.product_id for row in result_rows] == [
        scored_products[0].db_product_id,
        scored_products[1].db_product_id,
    ]
    assert result_rows[0].total_score == _score_to_decimal(scored_products[0].total_score)
    breakdown = result_rows[0].score_breakdown
    assert breakdown["scoring_version"] == SCORING_VERSION
    assert "skin_profile_score" in breakdown
    assert "market_signal_score" in breakdown
    assert "skin_test_context_score" in breakdown
    assert breakdown["skin_test_context_applied"] is False
    assert "base_weights" in breakdown
    assert "weights" in breakdown
    assert len(evidence_rows) > 0
    assert len(evidence_rows) <= len(result_rows) * 3
    assert evidence_rows[0].recommendation_result_id == result_rows[0].id
    assert evidence_rows[0].ingredient_id is not None
    assert evidence_rows[0].effect_id is not None
    assert evidence_rows[0].contribution_score is not None
    result_id_by_product_id = {
        result.product_id: result.id
        for result in result_rows
    }
    expected_evidence = [
        (
            result_id_by_product_id[scored_product.db_product_id],
            evidence.ingredient_id,
            evidence.effect_id,
            evidence.evidence_id,
            Decimal(str(evidence.contribution_score)).quantize(Decimal("0.0001")),
            evidence.reason,
        )
        for scored_product in sorted(scored_products, key=lambda product: product.rank)
        for evidence in scored_product.score_evidence[:3]
    ]
    assert [
        (
            evidence.recommendation_result_id,
            evidence.ingredient_id,
            evidence.effect_id,
            evidence.evidence_id,
            evidence.contribution_score,
            evidence.reason,
        )
        for evidence in evidence_rows
    ] == expected_evidence
    assert set(timings) == {
        "result_existing_lookup_ms",
        "result_payload_build_ms",
        "result_bulk_row_count",
        "evidence_payload_build_ms",
        "evidence_bulk_row_count",
        "result_raw_sql_execute_ms",
        "result_raw_sql_result_count",
        "result_raw_sql_evidence_count",
        "result_raw_sql_unmatched_evidence_count",
    }
    assert timings["result_bulk_row_count"] == len(result_rows)
    assert timings["evidence_bulk_row_count"] == len(evidence_rows)
    assert timings["result_raw_sql_result_count"] == len(result_rows)
    assert timings["result_raw_sql_evidence_count"] == len(evidence_rows)
    assert timings["result_raw_sql_unmatched_evidence_count"] == 0
    assert all(value >= 0 for value in timings.values())


def test_save_recommendation_results_replaces_existing_run_results() -> None:
    session = _seed_example_session()
    run_id, scored_products = _build_scored_products(
        session,
        "민감하고 진정 위주 추천",
        skin_type="지성",
        sensitivity="높음",
    )

    save_recommendation_results(session, run_id, scored_products)
    save_recommendation_results(session, run_id, scored_products[:1], result_limit=1)

    result_rows = _load_results(session, run_id)
    evidence_rows = _load_evidence(session, run_id)

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

    result_rows = _load_results(session, run_id)
    evidence_rows = _load_evidence(session, run_id)

    assert saved.result_count == 1
    assert saved.evidence_count <= 1
    assert len(result_rows) == saved.result_count
    assert len(evidence_rows) == saved.evidence_count


def test_save_recommendation_results_supports_empty_evidence_batch() -> None:
    session = _seed_example_session()
    run_id, scored_products = _build_scored_products(
        session,
        "hydration recommendation",
        skin_type="normal",
        sensitivity="normal",
    )

    timings: dict[str, float] = {}
    saved = save_recommendation_results(
        session,
        run_id,
        [replace(scored_products[0], score_evidence=())],
        timings=timings,
    )

    assert saved.result_count == 1
    assert saved.evidence_count == 0
    assert timings["result_bulk_row_count"] == 1
    assert timings["evidence_bulk_row_count"] == 0


def test_save_recommendation_results_supports_empty_result_batch() -> None:
    session = _seed_example_session()
    run_id, _ = _build_scored_products(
        session,
        "hydration recommendation",
        skin_type="normal",
        sensitivity="normal",
    )

    timings: dict[str, float] = {}
    saved = save_recommendation_results(session, run_id, [], timings=timings)

    assert saved.result_count == 0
    assert saved.evidence_count == 0
    assert timings["result_bulk_row_count"] == 0
    assert timings["evidence_bulk_row_count"] == 0


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


def _load_evidence(
    session: Session,
    recommendation_run_id: int,
) -> list[RecommendationScoreEvidence]:
    return session.execute(
        select(RecommendationScoreEvidence)
        .join(
            RecommendationResult,
            RecommendationScoreEvidence.recommendation_result_id == RecommendationResult.id,
        )
        .where(RecommendationResult.recommendation_run_id == recommendation_run_id)
        .order_by(RecommendationScoreEvidence.id.asc())
    ).scalars().all()


def _score_to_decimal(score: float) -> Decimal:
    return Decimal(str(score)).quantize(Decimal("0.01"))
