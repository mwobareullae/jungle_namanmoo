from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.services.candidate_pool import generate_candidate_pool
from app.services.recommendation_intent import build_recommendation_intent
from app.services.scoring import ScoredProduct, score_candidates
from app.services.search_matching import match_product_search_documents


QUALITY_FIXTURE_VERSION = "recommendation-coarse-top50-quality-v1"


@dataclass(frozen=True)
class CoarseQualityCase:
    case_id: str
    query: str
    skin_type: str = "중성"
    sensitivity: str = "보통"
    avoid_ingredients: tuple[str, ...] = ()
    weight: float = 1.0


@dataclass(frozen=True)
class CoarseQualityCaseResult:
    case_id: str
    query: str
    weight: float
    candidate_count: int = 0
    baseline_result_count: int = 0
    coarse_result_count: int = 0
    baseline_top1_product_id: str | None = None
    top1_retained: bool | None = None
    top10_recall_at_50: float | None = None
    exact_value_parity: bool | None = None
    coarse_shortlist_size: int = 0
    scoring_fallback: bool = False
    scoring_fallback_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_coarse_quality_cases(payload: object) -> tuple[CoarseQualityCase, ...]:
    if not isinstance(payload, dict):
        raise ValueError("quality fixture must be an object")
    if payload.get("version") != QUALITY_FIXTURE_VERSION:
        raise ValueError(
            f"quality fixture version must be {QUALITY_FIXTURE_VERSION}"
        )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("quality fixture cases must be a non-empty list")

    cases: list[CoarseQualityCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("quality case must be an object")
        case_id = str(raw_case.get("id", "")).strip()
        query = str(raw_case.get("query", "")).strip()
        if not case_id or case_id in seen_ids:
            raise ValueError("quality case id must be non-empty and unique")
        if not query:
            raise ValueError(f"quality case query is required: {case_id}")
        seen_ids.add(case_id)
        cases.append(
            CoarseQualityCase(
                case_id=case_id,
                query=query,
                skin_type=str(raw_case.get("skin_type", "중성")).strip(),
                sensitivity=str(raw_case.get("sensitivity", "보통")).strip(),
                avoid_ingredients=tuple(
                    str(value).strip()
                    for value in raw_case.get("avoid_ingredients", [])
                    if str(value).strip()
                ),
                weight=float(raw_case.get("weight", 1.0)),
            )
        )
    return tuple(cases)


def evaluate_coarse_quality_cases(
    session: Session,
    cases: tuple[CoarseQualityCase, ...],
    *,
    candidate_pool_limit: int = 500,
) -> list[CoarseQualityCaseResult]:
    return [
        _evaluate_coarse_quality_case(
            session,
            case,
            candidate_pool_limit=candidate_pool_limit,
        )
        for case in cases
    ]


def summarize_coarse_quality_results(
    results: list[CoarseQualityCaseResult],
) -> dict[str, Any]:
    successful = [result for result in results if result.error is None]
    top1_results = [
        result for result in successful if result.top1_retained is not None
    ]
    recall_results = [
        result
        for result in successful
        if result.top10_recall_at_50 is not None
    ]
    weighted_recall_denominator = sum(result.weight for result in recall_results)
    weighted_recall = (
        sum(
            float(result.top10_recall_at_50) * result.weight
            for result in recall_results
        )
        / weighted_recall_denominator
        if weighted_recall_denominator > 0
        else None
    )
    return {
        "case_count": len(results),
        "successful_case_count": len(successful),
        "error_case_count": len(results) - len(successful),
        "fallback_case_count": sum(
            1 for result in successful if result.scoring_fallback
        ),
        "top1_eligible_case_count": len(top1_results),
        "top1_retained_count": sum(
            1 for result in top1_results if result.top1_retained
        ),
        "top1_retention_rate": (
            sum(1 for result in top1_results if result.top1_retained)
            / len(top1_results)
            if top1_results
            else None
        ),
        "top10_recall_at_50_mean": (
            mean(float(result.top10_recall_at_50) for result in recall_results)
            if recall_results
            else None
        ),
        "top10_recall_at_50_weighted": weighted_recall,
        "top10_recall_at_50_min": (
            min(float(result.top10_recall_at_50) for result in recall_results)
            if recall_results
            else None
        ),
        "exact_value_parity_case_count": sum(
            1 for result in successful if result.exact_value_parity is True
        ),
        "exact_value_parity_rate": (
            sum(1 for result in successful if result.exact_value_parity is True)
            / len(successful)
            if successful
            else None
        ),
    }


def render_coarse_quality_markdown(
    results: list[CoarseQualityCaseResult],
    *,
    candidate_pool_limit: int,
) -> str:
    summary = summarize_coarse_quality_results(results)
    lines = [
        "# Coarse Top50 추천 품질 비교",
        "",
        f"- candidate_pool_limit: {candidate_pool_limit}",
        f"- cases: {summary['successful_case_count']}/{summary['case_count']}",
        f"- fallback cases: {summary['fallback_case_count']}",
        f"- top1 retention: {_format_ratio(summary['top1_retention_rate'])}",
        f"- top10 recall@50 mean: {_format_ratio(summary['top10_recall_at_50_mean'])}",
        f"- top10 recall@50 min: {_format_ratio(summary['top10_recall_at_50_min'])}",
        f"- exact value parity: {_format_ratio(summary['exact_value_parity_rate'])}",
        "",
        "| case | candidates | baseline | coarse | top1 | recall@50 | parity | fallback |",
        "| --- | ---: | ---: | ---: | --- | ---: | --- | --- |",
    ]
    for result in results:
        if result.error is not None:
            lines.append(
                f"| {result.case_id} | - | - | - | ERROR | - | - | "
                f"{_clean_markdown_cell(result.error)} |"
            )
            continue
        lines.append(
            f"| {result.case_id} "
            f"| {result.candidate_count} "
            f"| {result.baseline_result_count} "
            f"| {result.coarse_result_count} "
            f"| {_format_optional_bool(result.top1_retained)} "
            f"| {_format_ratio(result.top10_recall_at_50)} "
            f"| {_format_optional_bool(result.exact_value_parity)} "
            f"| {result.scoring_fallback} |"
        )
    return "\n".join(lines) + "\n"


def _evaluate_coarse_quality_case(
    session: Session,
    case: CoarseQualityCase,
    *,
    candidate_pool_limit: int,
) -> CoarseQualityCaseResult:
    try:
        intent = build_recommendation_intent(case.query)
        candidate_pool = generate_candidate_pool(
            session,
            intent,
            skin_type=case.skin_type,
            sensitivity=case.sensitivity,
            avoid_ingredients=list(case.avoid_ingredients),
            target_pool_size=candidate_pool_limit,
        )
        candidates = candidate_pool.candidates
        matches = match_product_search_documents(session, intent, candidates)
        baseline = score_candidates(
            session,
            intent,
            candidates,
            matches,
            skin_type=case.skin_type,
            sensitivity=case.sensitivity,
            manual_skin_type_explicit=True,
            manual_sensitivity_explicit=True,
            result_limit=None,
            scoring_read_path="legacy_bulk",
        )
        diagnostics: dict[str, object] = {}
        coarse = score_candidates(
            session,
            intent,
            candidates,
            matches,
            skin_type=case.skin_type,
            sensitivity=case.sensitivity,
            manual_skin_type_explicit=True,
            manual_sensitivity_explicit=True,
            result_limit=None,
            scoring_read_path="coarse_top50_v1",
            diagnostics=diagnostics,
        )
        baseline_top10 = [product.db_product_id for product in baseline[:10]]
        coarse_ids = {product.db_product_id for product in coarse}
        baseline_by_id = {
            product.db_product_id: product for product in baseline
        }
        top1_retained = (
            baseline[0].db_product_id in coarse_ids if baseline else None
        )
        recall_at_50 = (
            len(set(baseline_top10) & coarse_ids) / len(baseline_top10)
            if baseline_top10
            else None
        )
        exact_value_parity = all(
            product.db_product_id in baseline_by_id
            and _same_exact_values(product, baseline_by_id[product.db_product_id])
            for product in coarse
        )
        return CoarseQualityCaseResult(
            case_id=case.case_id,
            query=case.query,
            weight=case.weight,
            candidate_count=len(candidates),
            baseline_result_count=len(baseline),
            coarse_result_count=len(coarse),
            baseline_top1_product_id=(baseline[0].product_id if baseline else None),
            top1_retained=top1_retained,
            top10_recall_at_50=recall_at_50,
            exact_value_parity=exact_value_parity,
            coarse_shortlist_size=int(diagnostics.get("coarse_shortlist_size", 0)),
            scoring_fallback=bool(diagnostics.get("scoring_fallback", False)),
            scoring_fallback_reason=(
                str(diagnostics["scoring_fallback_reason"])
                if diagnostics.get("scoring_fallback_reason") is not None
                else None
            ),
        )
    except Exception as exc:
        session.rollback()
        return CoarseQualityCaseResult(
            case_id=case.case_id,
            query=case.query,
            weight=case.weight,
            error=str(exc),
        )


def _same_exact_values(left: ScoredProduct, right: ScoredProduct) -> bool:
    return (
        left.total_score == right.total_score
        and left.reason_summary == right.reason_summary
        and left.evidence_tags == right.evidence_tags
        and left.key_ingredients == right.key_ingredients
        and left.score_breakdown == right.score_breakdown
        and left.score_evidence == right.score_evidence
    )


def _format_ratio(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "PASS" if value else "FAIL"


def _clean_markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "/")
