from dataclasses import dataclass
from decimal import Decimal
from typing import MutableMapping

from sqlalchemy import bindparam, delete, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms
from app.db.models.recommendation import RecommendationResult, RecommendationScoreEvidence
from app.services.scoring import ScoredProduct


TOTAL_SCORE_QUANTIZE = Decimal("0.01")
CONTRIBUTION_SCORE_QUANTIZE = Decimal("0.0001")
DEFAULT_RESULT_LIMIT = 50
DEFAULT_EVIDENCE_LIMIT_PER_RESULT = 3


@dataclass(frozen=True)
class SavedRecommendationResultSummary:
    result_count: int
    evidence_count: int


# This is deliberately PostgreSQL-specific. The recommendation endpoint writes
# a small, bounded result set and never consumes ORM instances after saving it.
# A single CTE avoids ORM hydration and keeps result/evidence FK mapping inside
# the database transaction.
_INSERT_RECOMMENDATION_RESULTS_AND_EVIDENCE = text(
    """
    WITH result_input AS (
        SELECT *
        FROM jsonb_to_recordset(CAST(:result_payload AS jsonb)) AS payload(
            product_id BIGINT,
            rank_order INTEGER,
            total_score NUMERIC(6, 2),
            reason_summary TEXT,
            score_breakdown JSONB
        )
    ),
    inserted_results AS (
        INSERT INTO recommendation_results (
            recommendation_run_id,
            product_id,
            rank_order,
            total_score,
            reason_summary,
            score_breakdown
        )
        SELECT
            :recommendation_run_id,
            result_input.product_id,
            result_input.rank_order,
            result_input.total_score,
            result_input.reason_summary,
            result_input.score_breakdown
        FROM result_input
        ORDER BY result_input.rank_order
        RETURNING id, product_id
    ),
    evidence_input AS (
        SELECT *
        FROM jsonb_to_recordset(CAST(:evidence_payload AS jsonb)) AS payload(
            product_id BIGINT,
            ingredient_id BIGINT,
            effect_id BIGINT,
            evidence_id BIGINT,
            contribution_score NUMERIC(6, 4),
            reason TEXT
        )
    ),
    inserted_evidence AS (
        INSERT INTO recommendation_score_evidence (
            recommendation_result_id,
            ingredient_id,
            effect_id,
            evidence_id,
            contribution_score,
            reason
        )
        SELECT
            inserted_results.id,
            evidence_input.ingredient_id,
            evidence_input.effect_id,
            evidence_input.evidence_id,
            evidence_input.contribution_score,
            evidence_input.reason
        FROM evidence_input
        JOIN inserted_results
            ON inserted_results.product_id = evidence_input.product_id
        RETURNING id
    )
    SELECT
        (SELECT count(*) FROM result_input) AS requested_result_count,
        (SELECT count(*) FROM inserted_results) AS inserted_result_count,
        (SELECT count(*) FROM evidence_input) AS requested_evidence_count,
        (SELECT count(*) FROM inserted_evidence) AS inserted_evidence_count,
        (
            SELECT count(*)
            FROM evidence_input
            LEFT JOIN inserted_results
                ON inserted_results.product_id = evidence_input.product_id
            WHERE inserted_results.id IS NULL
        ) AS unmatched_evidence_count
    """
).bindparams(
    bindparam("result_payload", type_=JSONB),
    bindparam("evidence_payload", type_=JSONB),
)


def save_recommendation_results(
    session: Session,
    recommendation_run_id: int,
    scored_products: list[ScoredProduct],
    *,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    evidence_limit_per_result: int = DEFAULT_EVIDENCE_LIMIT_PER_RESULT,
    timings: MutableMapping[str, float] | None = None,
) -> SavedRecommendationResultSummary:
    _delete_existing_results(session, recommendation_run_id, timings=timings)

    stage_started_at = current_time()
    ranked_products = _ranked_products(scored_products, result_limit)
    result_payloads = [
        {
            "product_id": scored_product.db_product_id,
            "rank_order": rank_order,
            "total_score": str(
                _to_decimal(scored_product.total_score, TOTAL_SCORE_QUANTIZE)
            ),
            "reason_summary": scored_product.reason_summary,
            "score_breakdown": scored_product.score_breakdown,
        }
        for rank_order, scored_product in enumerate(ranked_products, start=1)
    ]
    _record_timing(timings, "result_payload_build_ms", stage_started_at)
    _record_count(timings, "result_bulk_row_count", len(result_payloads))

    stage_started_at = current_time()
    evidence_payloads = [
        {
            "product_id": scored_product.db_product_id,
            "ingredient_id": evidence.ingredient_id,
            "effect_id": evidence.effect_id,
            "evidence_id": evidence.evidence_id,
            "contribution_score": str(
                _to_decimal(
                    evidence.contribution_score,
                    CONTRIBUTION_SCORE_QUANTIZE,
                )
            ),
            "reason": evidence.reason,
        }
        for scored_product in ranked_products
        for evidence in scored_product.score_evidence[:evidence_limit_per_result]
    ]
    _record_timing(timings, "evidence_payload_build_ms", stage_started_at)
    _record_count(timings, "evidence_bulk_row_count", len(evidence_payloads))

    stage_started_at = current_time()
    summary = _persist_result_payloads(
        session,
        recommendation_run_id=recommendation_run_id,
        result_payloads=result_payloads,
        evidence_payloads=evidence_payloads,
    )
    _record_timing(timings, "result_raw_sql_execute_ms", stage_started_at)
    _record_count(timings, "result_raw_sql_result_count", summary.result_count)
    _record_count(timings, "result_raw_sql_evidence_count", summary.evidence_count)
    _record_count(
        timings,
        "result_raw_sql_unmatched_evidence_count",
        summary.unmatched_evidence_count,
    )

    return SavedRecommendationResultSummary(
        result_count=summary.result_count,
        evidence_count=summary.evidence_count,
    )


@dataclass(frozen=True)
class _RawPersistenceSummary:
    result_count: int
    evidence_count: int
    unmatched_evidence_count: int


def _persist_result_payloads(
    session: Session,
    *,
    recommendation_run_id: int,
    result_payloads: list[dict],
    evidence_payloads: list[dict],
) -> _RawPersistenceSummary:
    if session.get_bind().dialect.name == "postgresql":
        return _persist_result_payloads_postgresql(
            session,
            recommendation_run_id=recommendation_run_id,
            result_payloads=result_payloads,
            evidence_payloads=evidence_payloads,
        )

    # SQLite is used by the fast unit suite. Production and benchmark paths
    # are PostgreSQL; this compatibility implementation keeps those unit tests
    # focused on persistence semantics.
    return _persist_result_payloads_sqlite_compat(
        session,
        recommendation_run_id=recommendation_run_id,
        result_payloads=result_payloads,
        evidence_payloads=evidence_payloads,
    )


def _persist_result_payloads_postgresql(
    session: Session,
    *,
    recommendation_run_id: int,
    result_payloads: list[dict],
    evidence_payloads: list[dict],
) -> _RawPersistenceSummary:
    row = session.execute(
        _INSERT_RECOMMENDATION_RESULTS_AND_EVIDENCE,
        {
            "recommendation_run_id": recommendation_run_id,
            "result_payload": result_payloads,
            "evidence_payload": evidence_payloads,
        },
    ).mappings().one()
    requested_result_count = int(row["requested_result_count"])
    result_count = int(row["inserted_result_count"])
    requested_evidence_count = int(row["requested_evidence_count"])
    evidence_count = int(row["inserted_evidence_count"])
    unmatched_evidence_count = int(row["unmatched_evidence_count"])
    if (
        result_count != requested_result_count
        or evidence_count != requested_evidence_count
        or unmatched_evidence_count != 0
    ):
        raise RuntimeError("recommendation raw SQL persistence counts did not match input")
    return _RawPersistenceSummary(
        result_count=result_count,
        evidence_count=evidence_count,
        unmatched_evidence_count=unmatched_evidence_count,
    )


def _persist_result_payloads_sqlite_compat(
    session: Session,
    *,
    recommendation_run_id: int,
    result_payloads: list[dict],
    evidence_payloads: list[dict],
) -> _RawPersistenceSummary:
    if result_payloads:
        session.execute(
            insert(RecommendationResult),
            [
                {
                    **payload,
                    "recommendation_run_id": recommendation_run_id,
                    "total_score": Decimal(payload["total_score"]),
                }
                for payload in result_payloads
            ],
        )

    result_id_by_product_id = dict(
        session.execute(
            select(RecommendationResult.product_id, RecommendationResult.id).where(
                RecommendationResult.recommendation_run_id == recommendation_run_id,
            )
        ).all()
    )
    unmatched_evidence_count = sum(
        payload["product_id"] not in result_id_by_product_id
        for payload in evidence_payloads
    )
    if unmatched_evidence_count:
        raise RuntimeError("recommendation evidence referenced an unsaved result")
    if evidence_payloads:
        session.execute(
            insert(RecommendationScoreEvidence),
            [
                {
                    "recommendation_result_id": result_id_by_product_id[payload["product_id"]],
                    "ingredient_id": payload["ingredient_id"],
                    "effect_id": payload["effect_id"],
                    "evidence_id": payload["evidence_id"],
                    "contribution_score": Decimal(payload["contribution_score"]),
                    "reason": payload["reason"],
                }
                for payload in evidence_payloads
            ],
        )
    return _RawPersistenceSummary(
        result_count=len(result_payloads),
        evidence_count=len(evidence_payloads),
        unmatched_evidence_count=0,
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
