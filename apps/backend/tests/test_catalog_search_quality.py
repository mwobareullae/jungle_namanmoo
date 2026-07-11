from datetime import timedelta

import pytest

from app.services.catalog_search_quality import (
    calculate_catalog_quality_metrics,
    evaluate_catalog_search_case,
    render_catalog_quality_markdown,
)


class _FakeResponse:
    def __init__(self, payload: dict, *, latency_ms: float = 12.0) -> None:
        self._payload = payload
        self.elapsed = timedelta(milliseconds=latency_ms)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[tuple[str, dict]] = []

    def get(self, path: str, *, params: dict):
        self.requests.append((path, params))
        return _FakeResponse(self.payload)


def test_quality_case_evaluator_checks_exact_product_and_filters() -> None:
    client = _FakeClient(
        {
            "corrected_query": None,
            "items": [
                {
                    "product_id": "prod_001",
                    "brand": "라운드랩",
                    "category_code": "cream",
                    "lowest_price": 19_900,
                    "rating": 4.8,
                    "sales_status": "ON_SALE",
                }
            ],
        }
    )
    case = {
        "id": "exact-test",
        "type": "exact_product",
        "status": "ready",
        "query": "자작나무 수분 크림",
        "expected": {
            "outcome": "products",
            "top_product_ids": ["prod_001"],
            "top_k": 1,
            "brand_names": ["라운드랩"],
            "category_codes": ["cream"],
            "filters": {"price_max": 20_000},
        },
    }

    result = evaluate_catalog_search_case(client, case)

    assert result.passed is True
    assert result.checks["exact_hit_at_1"] is True
    assert result.checks["filter_violation_count"] == 0
    assert client.requests[0] == (
        "search/products",
        {"q": "자작나무 수분 크림", "page": 1, "page_size": 1},
    )


def test_quality_case_evaluator_rejects_irrelevant_no_result_fill() -> None:
    client = _FakeClient(
        {
            "corrected_query": None,
            "items": [{"product_id": "popular_product"}],
        }
    )
    case = {
        "id": "no-result-test",
        "type": "no_result",
        "status": "ready",
        "query": "맥북 프로",
        "expected": {"outcome": "no_results", "allow_popular_fallback": False},
    }

    result = evaluate_catalog_search_case(client, case)

    assert result.passed is False
    assert result.checks["no_irrelevant_fill"] is False


def test_quality_metrics_and_markdown_apply_fixed_thresholds() -> None:
    passing = evaluate_catalog_search_case(
        _FakeClient(
            {
                "corrected_query": "토리든",
                "items": [{"product_id": "p", "brand": "토리든"}],
            }
        ),
        {
            "id": "typo-test",
            "type": "typo_alias",
            "status": "ready",
            "query": "토리덴",
            "expected": {
                "outcome": "correction",
                "correction": "토리든",
                "brand_names": ["토리든"],
            },
        },
    )

    metrics = calculate_catalog_quality_metrics([passing])
    report = {
        "generated_at": "2026-07-11T00:00:00+00:00",
        "summary": {
            "evaluated_case_count": 1,
            "passed_case_count": 1,
            "failed_case_count": 0,
            "overall_passed": all(metric["passed"] for metric in metrics.values()),
        },
        "metrics": metrics,
        "cases": [passing.to_dict()],
    }

    assert metrics["typo_recovery_rate"]["value"] == pytest.approx(1.0)
    markdown = render_catalog_quality_markdown(report)
    assert "일반 상품 검색 품질 보고서" in markdown
    assert "typo_recovery_rate" in markdown
