from decimal import Decimal
from typing import MutableMapping

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms
from app.db.models.recommendation import SearchCandidate
from app.services.product_candidates import ProductCandidate
from app.services.search_matching import SearchMatch


SCORE_QUANTIZE = Decimal("0.0001")


def save_search_candidates(
    session: Session,
    recommendation_run_id: int,
    candidates: list[ProductCandidate],
    matches: list[SearchMatch],
    *,
    timings: MutableMapping[str, float] | None = None,
) -> list[SearchCandidate]:
    stage_started_at = current_time()
    candidate_by_product_code = {
        candidate.product_id: candidate
        for candidate in candidates
    }
    candidate_order = {
        candidate.product_id: index
        for index, candidate in enumerate(candidates)
    }

    unknown_product_codes = [
        match.product_id
        for match in matches
        if match.product_id not in candidate_by_product_code
    ]
    if unknown_product_codes:
        raise ValueError(f"Unknown search match product_id: {unknown_product_codes[0]}")
    _record_timing(timings, "candidate_trace_match_validation_ms", stage_started_at)

    stage_started_at = current_time()
    session.execute(
        delete(SearchCandidate).where(
            SearchCandidate.recommendation_run_id == recommendation_run_id,
        )
    )
    _record_timing(timings, "candidate_trace_delete_ms", stage_started_at)

    stage_started_at = current_time()
    sorted_matches = sorted(
        matches,
        key=lambda match: (
            -match.search_match_score,
            candidate_order[match.product_id],
        ),
    )

    rows = [
        SearchCandidate(
            recommendation_run_id=recommendation_run_id,
            product_id=candidate_by_product_code[match.product_id].db_product_id,
            keyword_score=_score_to_decimal(match.keyword_score),
            vector_score=_score_to_decimal(match.vector_score),
            search_match_score=_score_to_decimal(match.search_match_score),
            rank_order=rank_order,
        )
        for rank_order, match in enumerate(sorted_matches, start=1)
    ]
    _record_timing(timings, "candidate_trace_row_build_ms", stage_started_at)

    stage_started_at = current_time()
    session.add_all(rows)
    _record_timing(timings, "candidate_trace_add_ms", stage_started_at)

    stage_started_at = current_time()
    session.flush()
    _record_timing(timings, "candidate_trace_flush_ms", stage_started_at)
    return rows


def _score_to_decimal(score: float) -> Decimal:
    return Decimal(str(score)).quantize(SCORE_QUANTIZE)


def _record_timing(
    timings: MutableMapping[str, float] | None,
    key: str,
    started_at: float,
) -> None:
    if timings is not None:
        timings[key] = round(elapsed_ms(started_at), 2)
