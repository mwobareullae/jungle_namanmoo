import argparse
import json
import sys
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.schemas.recommendation import RecommendedProduct, RecommendationRequest, RecommendationResponse
from app.services.recommendation_pipeline import (
    DEFAULT_CANDIDATE_POOL_LIMIT,
    DEFAULT_RESULT_LIMIT,
    create_recommendation_response,
)


DEFAULT_TOP_N = 10


@dataclass(frozen=True)
class QualityCase:
    label: str
    concern_text: str
    skin_type: str = "중성"
    sensitivity: str = "보통"
    avoid_ingredients: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityCaseResult:
    case: QualityCase
    elapsed_ms: float
    response: RecommendationResponse | None = None
    error: str | None = None


DEFAULT_CASES: tuple[QualityCase, ...] = (
    QualityCase(
        label="속건조 크림",
        concern_text="속건조가 있는데 크림 추천해줘",
        skin_type="건성",
    ),
    QualityCase(
        label="여드름 진정 세럼",
        concern_text="여드름 진정 세럼 추천해줘",
        skin_type="지성",
    ),
    QualityCase(
        label="라운드랩 토너 가격제한",
        concern_text="라운드랩 토너 2만원 이하 추천",
    ),
    QualityCase(
        label="미백 앰플",
        concern_text="칙칙하고 잡티가 고민인데 미백 앰플 추천",
    ),
    QualityCase(
        label="민감 진정 크림",
        concern_text="민감성 피부 진정 크림 추천",
        skin_type="건성",
        sensitivity="민감",
    ),
    QualityCase(
        label="피지 수부지 세럼",
        concern_text="피지가 많고 속은 건조한데 수부지 세럼 추천해줘",
        skin_type="수부지",
    ),
)


def main() -> None:
    _configure_stdout()
    args = _parse_args()
    cases = _parse_cases(args.query)

    with SessionLocal() as session:
        results = [
            run_quality_case(
                session,
                case,
                result_limit=args.result_limit,
                candidate_pool_limit=args.candidate_pool_limit,
                persist=args.persist,
            )
            for case in cases
        ]

    if args.format == "json":
        print(format_json_report(results, top_n=args.top_n))
    else:
        print(
            format_markdown_report(
                results,
                top_n=args.top_n,
                result_limit=args.result_limit,
                candidate_pool_limit=args.candidate_pool_limit,
                persist=args.persist,
            )
        )


def run_quality_case(
    session: Session,
    case: QualityCase,
    *,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    candidate_pool_limit: int = DEFAULT_CANDIDATE_POOL_LIMIT,
    persist: bool = False,
) -> QualityCaseResult:
    started_at = perf_counter()
    try:
        response = create_recommendation_response(
            session,
            RecommendationRequest(
                concern_text=case.concern_text,
                skin_type=case.skin_type,
                sensitivity=case.sensitivity,
                avoid_ingredients=list(case.avoid_ingredients),
            ),
            result_limit=result_limit,
            candidate_pool_limit=candidate_pool_limit,
            commit=persist,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000
        if not persist:
            session.rollback()
        return QualityCaseResult(case=case, elapsed_ms=elapsed_ms, response=response)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started_at) * 1000
        session.rollback()
        return QualityCaseResult(case=case, elapsed_ms=elapsed_ms, error=str(exc))


def format_markdown_report(
    results: list[QualityCaseResult],
    *,
    top_n: int = DEFAULT_TOP_N,
    result_limit: int = DEFAULT_RESULT_LIMIT,
    candidate_pool_limit: int = DEFAULT_CANDIDATE_POOL_LIMIT,
    persist: bool = False,
) -> str:
    mode = "persist" if persist else "rollback"
    lines = [
        "# 추천 품질 리포트",
        "",
        f"- mode: {mode}",
        f"- candidate_pool_limit: {candidate_pool_limit}",
        f"- result_limit: {result_limit}",
        f"- top_n: {top_n}",
        "",
    ]

    for result in results:
        lines.extend(_format_case_markdown(result, top_n=top_n))
        lines.append("")

    return "\n".join(lines).rstrip()


def format_json_report(results: list[QualityCaseResult], *, top_n: int = DEFAULT_TOP_N) -> str:
    payload = [
        _case_result_to_json(result, top_n=top_n)
        for result in results
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_case_markdown(result: QualityCaseResult, *, top_n: int) -> list[str]:
    case = result.case
    lines = [
        f"## {case.label}",
        "",
        f"- input: {case.concern_text}",
        f"- skin/sensitivity: {case.skin_type}/{case.sensitivity}",
        f"- elapsed_ms: {result.elapsed_ms:.2f}",
    ]

    if result.error:
        lines.append(f"- error: {_clean_cell(result.error)}")
        return lines

    if result.response is None:
        lines.append("- error: no response")
        return lines

    response = result.response
    summary = response.summary
    lines.extend(
        [
            f"- recommendation_id: {response.recommendation_id}",
            f"- matched_concerns: {_join_or_dash(summary.matched_concerns)}",
            f"- expected_effects: {_join_or_dash(summary.expected_effects)}",
            f"- purchase_constraints: {_purchase_constraints_text(response)}",
            f"- unmatched_terms: {_join_or_dash(response.unmatched_terms)}",
            "",
            "| rank | score | brand | product | price | reason | breakdown |",
            "| ---: | ---: | --- | --- | ---: | --- | --- |",
        ]
    )

    for product in response.products[:top_n]:
        lines.append(_product_row(product))

    if not response.products:
        lines.append("| - | - | - | 추천 결과 없음 | - | - | - |")

    return lines


def _product_row(product: RecommendedProduct) -> str:
    breakdown = product.score_breakdown
    breakdown_text = (
        f"eff {breakdown.ingredient_effect_score} / "
        f"ev {breakdown.ingredient_evidence_score} / "
        f"skin {breakdown.skin_type_score} / "
        f"price {breakdown.price_score} / "
        f"kw {breakdown.keyword_score} / "
        f"vec {breakdown.vector_score} / "
        f"search {breakdown.search_match_score} / "
        f"risk {breakdown.risk_penalty}"
    )
    return (
        f"| {product.rank} "
        f"| {product.total_score} "
        f"| {_clean_cell(product.brand)} "
        f"| {_clean_cell(product.name)} "
        f"| {product.lowest_price} "
        f"| {_clean_cell(product.reason_summary)} "
        f"| {breakdown_text} |"
    )


def _case_result_to_json(result: QualityCaseResult, *, top_n: int) -> dict:
    payload: dict = {
        "label": result.case.label,
        "input": result.case.concern_text,
        "skin_type": result.case.skin_type,
        "sensitivity": result.case.sensitivity,
        "elapsed_ms": round(result.elapsed_ms, 2),
    }
    if result.error or result.response is None:
        payload["error"] = result.error or "no response"
        return payload

    response = result.response
    payload.update(
        {
            "recommendation_id": response.recommendation_id,
            "matched_concerns": response.summary.matched_concerns,
            "expected_effects": response.summary.expected_effects,
            "purchase_constraints": response.summary.purchase_constraints.model_dump(),
            "unmatched_terms": response.unmatched_terms,
            "products": [
                product.model_dump()
                for product in response.products[:top_n]
            ],
        }
    )
    return payload


def _purchase_constraints_text(response: RecommendationResponse) -> str:
    constraints = response.summary.purchase_constraints
    parts: list[str] = []
    if constraints.categories:
        parts.append(
            "category="
            + ",".join(category.category_code for category in constraints.categories)
        )
    if constraints.brands:
        parts.append("brand=" + ",".join(brand.name for brand in constraints.brands))
    if constraints.price_min is not None:
        parts.append(f"price>={constraints.price_min}")
    if constraints.price_max is not None:
        parts.append(f"price<={constraints.price_max}")
    return ", ".join(parts) or "-"


def _parse_cases(raw_queries: list[str] | None) -> tuple[QualityCase, ...]:
    if not raw_queries:
        return DEFAULT_CASES
    return tuple(_parse_case(raw_query, index) for index, raw_query in enumerate(raw_queries, start=1))


def _parse_case(raw_query: str, index: int) -> QualityCase:
    parts = [part.strip() for part in raw_query.split("|")]
    if len(parts) == 1:
        return QualityCase(label=f"custom-{index}", concern_text=parts[0])
    if len(parts) not in {2, 4, 5}:
        raise SystemExit(
            "--query format: concern_text or label|concern_text or "
            "label|concern_text|skin_type|sensitivity|avoid1,avoid2"
        )

    avoid_ingredients: tuple[str, ...] = ()
    if len(parts) == 5:
        avoid_ingredients = tuple(
            ingredient.strip()
            for ingredient in parts[4].split(",")
            if ingredient.strip()
        )

    return QualityCase(
        label=parts[0],
        concern_text=parts[1],
        skin_type=parts[2] if len(parts) >= 4 else "중성",
        sensitivity=parts[3] if len(parts) >= 4 else "보통",
        avoid_ingredients=avoid_ingredients,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run recommendation quality smoke cases and print ranked result tables.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of ranked products to print per case.",
    )
    parser.add_argument(
        "--result-limit",
        type=int,
        default=DEFAULT_RESULT_LIMIT,
        help="Number of products generated by the recommendation pipeline.",
    )
    parser.add_argument(
        "--candidate-pool-limit",
        type=int,
        default=DEFAULT_CANDIDATE_POOL_LIMIT,
        help="Number of hard-filtered candidates searched before final result ranking.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Commit recommendation runs/results instead of rolling back after each case.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Report output format.",
    )
    parser.add_argument(
        "--query",
        action="append",
        help=(
            "Custom case. Use concern_text, label|concern_text, or "
            "label|concern_text|skin_type|sensitivity|avoid1,avoid2. "
            "Repeat this option to run multiple custom cases."
        ),
    )
    return parser.parse_args()


def _clean_cell(value: str, *, max_length: int = 80) -> str:
    cleaned = " ".join(value.split()).replace("|", "/")
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"


def _join_or_dash(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
