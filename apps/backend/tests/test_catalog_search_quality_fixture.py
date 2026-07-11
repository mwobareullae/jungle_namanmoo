import json
from collections import Counter
from pathlib import Path


FIXTURE_PATH = Path(__file__).with_name("catalog_search_quality_cases.json")
ALLOWED_CASE_TYPES = {
    "exact_product",
    "brand",
    "category",
    "attribute",
    "compound",
    "typo_alias",
    "no_result",
}
ALLOWED_CASE_STATUSES = {"ready", "catalog_data_blocked"}
ALLOWED_OUTCOMES = {"products", "correction", "no_results"}
MINIMUM_CASE_COUNTS = {
    "exact_product": 12,
    "brand": 6,
    "category": 10,
    "attribute": 6,
    "compound": 6,
    "typo_alias": 5,
    "no_result": 4,
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_catalog_search_quality_fixture_has_required_coverage() -> None:
    payload = _load_fixture()
    cases = payload["cases"]

    assert payload["version"] == "catalog-search-quality-v1"
    assert payload["catalog_snapshot"]["product_count"] == 79_952
    assert len(cases) >= 60

    case_counts = Counter(case["type"] for case in cases)
    for case_type, minimum_count in MINIMUM_CASE_COUNTS.items():
        assert case_counts[case_type] >= minimum_count


def test_catalog_search_quality_fixture_cases_are_well_formed() -> None:
    cases = _load_fixture()["cases"]
    case_ids = [case["id"] for case in cases]

    assert len(case_ids) == len(set(case_ids))

    for case in cases:
        assert case["id"].strip()
        assert case["query"].strip()
        assert case["type"] in ALLOWED_CASE_TYPES
        assert case["status"] in ALLOWED_CASE_STATUSES

        expected = case["expected"]
        assert expected["outcome"] in ALLOWED_OUTCOMES
        assert isinstance(expected.get("top_product_ids", []), list)
        assert isinstance(expected.get("brand_names", []), list)
        assert isinstance(expected.get("category_codes", []), list)
        assert isinstance(expected.get("required_terms", []), list)
        assert isinstance(expected.get("forbidden_product_ids", []), list)

        if case["type"] == "exact_product":
            assert expected["outcome"] == "products"
            assert expected["top_product_ids"]
            assert expected["top_k"] == 1

        if case["type"] == "no_result":
            assert expected["outcome"] == "no_results"
            assert expected["allow_popular_fallback"] is False


def test_catalog_search_quality_fixture_tracks_non_recommendable_catalog_scope() -> None:
    cases = _load_fixture()["cases"]

    assert any(
        case.get("catalog_flags", {}).get("is_recommendable") is False
        for case in cases
    )
    assert any(case["type"] == "exact_product" and case["expected"]["top_product_ids"] for case in cases)
