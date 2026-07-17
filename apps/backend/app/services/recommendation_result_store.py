from dataclasses import dataclass
from decimal import Decimal
from typing import MutableMapping

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms
from app.db.models.recommendation import RecommendationResult, RecommendationScoreEvidence
from app.services.scoring import ScoredProduct


TOTAL_SCORE_QUANTIZE = Decimal("0.01")
CONTRIBUTION_SCORE_QUANTIZE = Decimal("0.0001")
DEFAULT_RESULT_LIMIT = 50
DEFAULT_EVIDENCE_LIMIT_PER_RESULT = 3


@dataclass(frozen=True)
class SavedRecommendationResults:
    results: tuple[RecommendationResult, ...]
    evidence: tuple[RecommendationScoreEvidence, ...]


def save_recommendation_results(
    session: Session,
    recommendation_run_id: int,
    scored_products: list[ScoredProduct],
    *,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    evidence_limit_per_result: int = DEFAULT_EVIDENCE_LIMIT_PER_RESULT,
    timings: MutableMapping[str, float] | None = None,
) -> SavedRecommendationResults:
    _delete_existing_results(session, recommendation_run_id, timings=timings)

    stage_started_at = current_time()
    ranked_products = _ranked_products(scored_products, result_limit)
    result_payloads = [
        {
            "recommendation_run_id": recommendation_run_id,
            "product_id": scored_product.db_product_id,
            "rank_order": rank_order,
            "total_score": _to_decimal(scored_product.total_score, TOTAL_SCORE_QUANTIZE),
            "reason_summary": scored_product.reason_summary,
            "score_breakdown": scored_product.score_breakdown,
        }
        for rank_order, scored_product in enumerate(ranked_products, start=1)
    ]
    _record_timing(timings, "result_payload_build_ms", stage_started_at)
    _record_count(timings, "result_bulk_row_count", len(result_payloads))

    stage_started_at = current_time()
    result_rows = _insert_result_rows(session, result_payloads)
    _record_timing(timings, "result_bulk_insert_ms", stage_started_at)

    result_id_by_product_id = _result_id_by_product_id(
        result_rows,
        expected_product_ids={
            payload["product_id"]
            for payload in result_payloads
        },
    )

    stage_started_at = current_time()
    evidence_payloads = [
        {
            "recommendation_result_id": result_id_by_product_id[
                scored_product.db_product_id
            ],
            "ingredient_id": evidence.ingredient_id,
            "effect_id": evidence.effect_id,
            "evidence_id": evidence.evidence_id,
            "contribution_score": _to_decimal(
                evidence.contribution_score,
                CONTRIBUTION_SCORE_QUANTIZE,
            ),
            "reason": evidence.reason,
        }
        for scored_product in ranked_products
        for evidence in scored_product.score_evidence[:evidence_limit_per_result]
    ]
    _record_timing(timings, "evidence_payload_build_ms", stage_started_at)
    _record_count(timings, "evidence_bulk_row_count", len(evidence_payloads))

    stage_started_at = current_time()
    evidence_rows = _insert_evidence_rows(session, evidence_payloads)
    _record_timing(timings, "evidence_bulk_insert_ms", stage_started_at)

    return SavedRecommendationResults(
        results=tuple(sorted(result_rows, key=lambda result: result.rank_order)),
        evidence=tuple(sorted(evidence_rows, key=lambda evidence: evidence.id)),
    )


def _insert_result_rows(
    session: Session,
    payloads: list[dict],
) -> tuple[RecommendationResult, ...]:
    if not payloads:
        return ()

    return tuple(
        session.scalars(
            insert(RecommendationResult).returning(RecommendationResult),
            payloads,
        ).all()
    )


def _result_id_by_product_id(
    result_rows: tuple[RecommendationResult, ...],
    *,
    expected_product_ids: set[int],
) -> dict[int, int]:
    result_id_by_product_id = {
        result.product_id: result.id
        for result in result_rows
    }
    if (
        len(result_rows) != len(expected_product_ids)
        or len(result_id_by_product_id) != len(expected_product_ids)
        or set(result_id_by_product_id) != expected_product_ids
    ):
        raise RuntimeError("추천 결과 bulk insert 반환값이 요청 상품과 일치하지 않습니다.")
    return result_id_by_product_id


def _insert_evidence_rows(
    session: Session,
    payloads: list[dict],
) -> tuple[RecommendationScoreEvidence, ...]:
    if not payloads:
        return ()

    return tuple(
        session.scalars(
            insert(RecommendationScoreEvidence).returning(RecommendationScoreEvidence),
            payloads,
        ).all()
    )


def _delete_existing_results(
    session: Session,
    recommendation_run_id: int,
    *,
    timings: MutableMapping[str, float] | None,
) -> None:
    stage_started_at = current_time()
    result_ids = session.execute(
        select(RecommendationResult.id).where(
            RecommendationResult.recommendation_run_id == recommendation_run_id,
        )
    ).scalars().all()
    _record_timing(timings, "result_existing_lookup_ms", stage_started_at)

    if not result_ids:
        return

    stage_started_at = current_time()
    session.execute(
        delete(RecommendationScoreEvidence).where(
            RecommendationScoreEvidence.recommendation_result_id.in_(result_ids),
        )
    )
    _record_timing(timings, "result_existing_evidence_delete_ms", stage_started_at)

    stage_started_at = current_time()
    session.execute(
        delete(RecommendationResult).where(
            RecommendationResult.recommendation_run_id == recommendation_run_id,
        )
    )
    _record_timing(timings, "result_existing_result_delete_ms", stage_started_at)

    stage_started_at = current_time()
    session.flush()
    _record_timing(timings, "result_existing_delete_flush_ms", stage_started_at)


def _ranked_products(
    scored_products: list[ScoredProduct],
    result_limit: int,
) -> tuple[ScoredProduct, ...]:
    if result_limit <= 0:
        return ()

    return tuple(
        product
        for _, product in sorted(
            enumerate(scored_products),
            key=lambda item: (
                item[1].rank if item[1].rank > 0 else item[0] + 1,
                item[0],
            ),
        )[:result_limit]
    )


def _to_decimal(score: float, quantize: Decimal) -> Decimal:
    return Decimal(str(score)).quantize(quantize)


def _record_timing(
    timings: MutableMapping[str, float] | None,
    key: str,
    started_at: float,
) -> None:
    if timings is not None:
        timings[key] = round(elapsed_ms(started_at), 2)


def _record_count(
    timings: MutableMapping[str, float] | None,
    key: str,
    value: int,
) -> None:
    if timings is not None:
        timings[key] = float(value)
