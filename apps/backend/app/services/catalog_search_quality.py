from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


QUALITY_TARGETS = {
    "exact_hit_at_1": {"operator": "gte", "target": 1.0},
    "brand_precision_at_10": {"operator": "gte", "target": 0.90},
    "category_precision_at_20": {"operator": "gte", "target": 0.90},
    "filter_violation_rate": {"operator": "lte", "target": 0.0},
    "irrelevant_fill_rate": {"operator": "lte", "target": 0.0},
    "typo_recovery_rate": {"operator": "gte", "target": 0.90},
    "wrong_correction_rate": {"operator": "lte", "target": 0.02},
}


class CatalogSearchHttpClient(Protocol):
    def get(self, path: str, *, params: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class CatalogQualityCaseResult:
    case_id: str
    case_type: str
    query: str
    status: str
    passed: bool
    latency_ms: float
    result_count: int
    returned_product_ids: tuple[str, ...]
    corrected_query: str | None
    checks: dict[str, bool | float | int | None]
    failure_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_type": self.case_type,
            "query": self.query,
            "status": self.status,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 2),
            "result_count": self.result_count,
            "returned_product_ids": list(self.returned_product_ids),
            "corrected_query": self.corrected_query,
            "checks": self.checks,
            "failure_reasons": list(self.failure_reasons),
        }


def evaluate_catalog_search_cases(
    client: CatalogSearchHttpClient,
    fixture: dict[str, Any],
    *,
    include_blocked: bool = False,
) -> dict[str, Any]:
    case_results: list[CatalogQualityCaseResult] = []
    skipped_case_ids: list[str] = []
    for case in fixture["cases"]:
        if case.get("status") != "ready" and not include_blocked:
            skipped_case_ids.append(case["id"])
            continue
        case_results.append(evaluate_catalog_search_case(client, case))

    metrics = calculate_catalog_quality_metrics(case_results)
    return {
        "version": "catalog-search-quality-report-v1",
        "fixture_version": fixture.get("version"),
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "evaluated_case_count": len(case_results),
            "passed_case_count": sum(result.passed for result in case_results),
            "failed_case_count": sum(not result.passed for result in case_results),
            "skipped_case_count": len(skipped_case_ids),
            "overall_passed": all(metric["passed"] for metric in metrics.values()),
        },
        "metrics": metrics,
        "skipped_case_ids": skipped_case_ids,
        "cases": [result.to_dict() for result in case_results],
    }


def evaluate_catalog_search_case(
    client: CatalogSearchHttpClient,
    case: dict[str, Any],
) -> CatalogQualityCaseResult:
    expected = case["expected"]
    top_k = min(max(int(expected.get("top_k") or 20), 1), 50)
    response = client.get(
        "search/products",
        params={"q": case["query"], "page": 1, "page_size": top_k},
    )
    latency_ms = float(getattr(response, "elapsed", 0).total_seconds() * 1000)
    response.raise_for_status()
    payload = response.json()
    items = list(payload.get("items") or [])
    corrected_query = payload.get("corrected_query")
    failure_reasons: list[str] = []
    checks: dict[str, bool | float | int | None] = {}

    outcome = expected["outcome"]
    if outcome == "no_results":
        no_result_passed = len(items) == 0
        checks["no_irrelevant_fill"] = no_result_passed
        if not no_result_passed:
            failure_reasons.append("expected no results but products were returned")
    else:
        has_results = len(items) > 0
        checks["has_results"] = has_results
        if not has_results:
            failure_reasons.append("expected products but result was empty")

    top_product_ids = expected.get("top_product_ids") or []
    if top_product_ids:
        hit_at_1 = bool(items) and items[0].get("product_id") in set(top_product_ids)
        checks["exact_hit_at_1"] = hit_at_1
        if not hit_at_1:
            failure_reasons.append("expected product was not ranked first")

    expected_brands = set(expected.get("brand_names") or [])
    if expected_brands:
        precision = _precision(items[:10], "brand", expected_brands)
        checks["brand_precision_at_10"] = precision
        if case["type"] == "brand" and precision < 0.90:
            failure_reasons.append("brand precision was below 0.90")

    expected_categories = set(expected.get("category_codes") or [])
    if expected_categories:
        precision = _precision(items[:20], "category_code", expected_categories)
        checks["category_precision_at_20"] = precision
        if case["type"] in {"category", "attribute", "compound"} and precision < 0.90:
            failure_reasons.append("category precision was below 0.90")

    filter_violations = _count_filter_violations(items, expected.get("filters") or {})
    checks["filter_violation_count"] = filter_violations
    if filter_violations:
        failure_reasons.append(f"hard filter violations: {filter_violations}")

    expected_correction = expected.get("correction")
    if case["type"] == "typo_alias":
        recovered = _typo_case_recovered(
            items,
            corrected_query=corrected_query,
            expected=expected,
        )
        checks["typo_recovered"] = recovered
        checks["expected_correction_matched"] = (
            expected_correction is None or corrected_query == expected_correction
        )
        if not recovered:
            failure_reasons.append("typo query was not recovered")
    else:
        wrong_correction = bool(corrected_query) and corrected_query != expected_correction
        checks["wrong_correction"] = wrong_correction
        if wrong_correction:
            failure_reasons.append("unexpected correction was suggested")

    forbidden_ids = set(expected.get("forbidden_product_ids") or [])
    forbidden_returned = any(item.get("product_id") in forbidden_ids for item in items)
    checks["forbidden_product_returned"] = forbidden_returned
    if forbidden_returned:
        failure_reasons.append("forbidden product was returned")

    return CatalogQualityCaseResult(
        case_id=case["id"],
        case_type=case["type"],
        query=case["query"],
        status=case.get("status", "ready"),
        passed=not failure_reasons,
        latency_ms=latency_ms,
        result_count=len(items),
        returned_product_ids=tuple(str(item.get("product_id")) for item in items),
        corrected_query=corrected_query,
        checks=checks,
        failure_reasons=tuple(failure_reasons),
    )


def calculate_catalog_quality_metrics(
    case_results: list[CatalogQualityCaseResult],
) -> dict[str, dict[str, Any]]:
    exact_values = [
        bool(result.checks["exact_hit_at_1"])
        for result in case_results
        if result.case_type == "exact_product" and "exact_hit_at_1" in result.checks
    ]
    brand_values = [
        float(result.checks["brand_precision_at_10"])
        for result in case_results
        if result.case_type == "brand" and "brand_precision_at_10" in result.checks
    ]
    category_values = [
        float(result.checks["category_precision_at_20"])
        for result in case_results
        if result.case_type == "category" and "category_precision_at_20" in result.checks
    ]
    filter_checks = [
        int(result.checks.get("filter_violation_count") or 0)
        for result in case_results
    ]
    filter_denominator = sum(result.result_count for result in case_results) or 1
    no_result_cases = [result for result in case_results if "no_irrelevant_fill" in result.checks]
    typo_cases = [result for result in case_results if "typo_recovered" in result.checks]
    non_typo_cases = [result for result in case_results if "wrong_correction" in result.checks]

    raw_metrics = {
        "exact_hit_at_1": (_mean(exact_values), len(exact_values)),
        "brand_precision_at_10": (_mean(brand_values), len(brand_values)),
        "category_precision_at_20": (_mean(category_values), len(category_values)),
        "filter_violation_rate": (sum(filter_checks) / filter_denominator, filter_denominator),
        "irrelevant_fill_rate": (
            _mean([not bool(result.checks["no_irrelevant_fill"]) for result in no_result_cases]),
            len(no_result_cases),
        ),
        "typo_recovery_rate": (
            _mean([bool(result.checks["typo_recovered"]) for result in typo_cases]),
            len(typo_cases),
        ),
        "wrong_correction_rate": (
            _mean([bool(result.checks["wrong_correction"]) for result in non_typo_cases]),
            len(non_typo_cases),
        ),
    }
    metrics: dict[str, dict[str, Any]] = {}
    for name, (value, sample_count) in raw_metrics.items():
        target = QUALITY_TARGETS[name]
        passed = value >= target["target"] if target["operator"] == "gte" else value <= target["target"]
        metrics[name] = {
            "value": round(value, 6),
            "sample_count": sample_count,
            "operator": target["operator"],
            "target": target["target"],
            "passed": passed,
        }
    return metrics


def render_catalog_quality_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 일반 상품 검색 품질 보고서",
        "",
        f"- 생성 시각: `{report['generated_at']}`",
        f"- 평가: {summary['evaluated_case_count']}건",
        f"- 통과/실패: {summary['passed_case_count']}/{summary['failed_case_count']}",
        f"- 전체 임계치 통과: {'PASS' if summary['overall_passed'] else 'FAIL'}",
        "",
        "## 지표",
        "",
        "| 지표 | 결과 | 기준 | 표본 | 판정 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, metric in report["metrics"].items():
        operator = ">=" if metric["operator"] == "gte" else "<="
        lines.append(
            f"| `{name}` | {metric['value']:.4f} | {operator} {metric['target']:.2f} "
            f"| {metric['sample_count']} | {'PASS' if metric['passed'] else 'FAIL'} |"
        )
    failed_cases = [case for case in report["cases"] if not case["passed"]]
    lines.extend(["", "## 실패 케이스", ""])
    if not failed_cases:
        lines.append("- 없음")
    else:
        for case in failed_cases:
            reasons = "; ".join(case["failure_reasons"])
            lines.append(f"- `{case['case_id']}` `{case['query']}`: {reasons}")
    lines.append("")
    return "\n".join(lines)


def _precision(items: list[dict[str, Any]], field: str, expected_values: set[str]) -> float:
    if not items:
        return 0.0
    return sum(item.get(field) in expected_values for item in items) / len(items)


def _count_filter_violations(items: list[dict[str, Any]], filters: dict[str, Any]) -> int:
    violations = 0
    for item in items:
        price = item.get("lowest_price")
        rating = item.get("rating")
        if filters.get("price_min") is not None and (price is None or price < filters["price_min"]):
            violations += 1
            continue
        if filters.get("price_max") is not None and (price is None or price > filters["price_max"]):
            violations += 1
            continue
        if filters.get("rating_min") is not None and (rating is None or rating < filters["rating_min"]):
            violations += 1
            continue
        if filters.get("availability") == "IN_STOCK" and item.get("sales_status") != "ON_SALE":
            violations += 1
    return violations


def _typo_case_recovered(
    items: list[dict[str, Any]],
    *,
    corrected_query: str | None,
    expected: dict[str, Any],
) -> bool:
    expected_correction = expected.get("correction")
    if expected_correction and corrected_query == expected_correction:
        return True
    expected_product_ids = set(expected.get("top_product_ids") or [])
    if expected_product_ids and any(item.get("product_id") in expected_product_ids for item in items):
        return True
    expected_brands = set(expected.get("brand_names") or [])
    if expected_brands and any(item.get("brand") in expected_brands for item in items):
        return True
    expected_categories = set(expected.get("category_codes") or [])
    return bool(expected_categories) and any(
        item.get("category_code") in expected_categories for item in items
    )


def _mean(values: list[bool | float]) -> float:
    if not values:
        return 0.0
    return sum(float(value) for value in values) / len(values)
