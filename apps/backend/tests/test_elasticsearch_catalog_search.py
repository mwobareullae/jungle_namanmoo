from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_query import CatalogSearchFilters, CatalogSearchQuery
from app.services.elasticsearch_catalog_search import (
    build_catalog_search_request,
    build_catalog_suggestion_request,
)


def test_catalog_search_request_contains_fixed_ranking_boosts_and_filters() -> None:
    parsed = CatalogSearchQuery(
        original_query="라운드랩 수분 크림",
        text_query="라운드랩 수분 크림",
        normalized_query="라운드랩 수분 크림",
        compact_query="라운드랩수분크림",
        filters=CatalogSearchFilters(
            brand_codes=("라운드랩",),
            category_codes=("cream",),
            category_groups=(),
            min_price=10_000,
            max_price=20_000,
            min_rating=4.0,
            in_stock=True,
        ),
        sort=CatalogSearchSort.RELEVANCE,
    )

    request = build_catalog_search_request(parsed, offset=20, limit=20)
    scored_query = request["query"]["script_score"]
    bool_query = scored_query["query"]["bool"]

    assert request["from_"] == 20
    assert request["size"] == 20
    assert request["track_total_hits"] is True
    assert bool_query["minimum_should_match"] == 1
    assert {"terms": {"brand_code": ["라운드랩"]}} in bool_query["filter"]
    assert {"range": {"lowest_price": {"gte": 10_000, "lte": 20_000}}} in bool_query["filter"]
    assert {"range": {"rating": {"gte": 4.0}}} in bool_query["filter"]
    assert {"term": {"in_stock": True}} in bool_query["filter"]

    should_text = str(bool_query["should"])
    assert "40.0" in should_text
    assert "30.0" in should_text
    assert "24.0" in should_text
    assert "16.0" in should_text
    assert "product_name^10" in should_text
    assert "brand_name^7" in should_text
    assert "ingredient_names^2" in should_text
    assert "0.10" in scored_query["script"]["source"]
    assert "0.03 * rating / 5.0" in scored_query["script"]["source"]
    assert "0.02 * reviewRatio" in scored_query["script"]["source"]
    assert "0.5" in scored_query["script"]["source"]


def test_catalog_search_request_uses_stable_non_relevance_sort() -> None:
    parsed = CatalogSearchQuery(
        original_query="세럼",
        text_query="세럼",
        normalized_query="세럼",
        compact_query="세럼",
        filters=CatalogSearchFilters((), (), (), None, None, None, None),
        sort=CatalogSearchSort.RATING,
    )

    request = build_catalog_search_request(parsed, offset=0, limit=10)

    assert request["sort"] == [
        {"rating": {"order": "desc", "missing": "_last"}},
        {"review_count": {"order": "desc", "missing": "_last"}},
        {"_score": {"order": "desc"}},
        {"product_id": {"order": "asc"}},
    ]
    assert set(request["aggregations"]) == {
        "brands",
        "categories",
        "price_ranges",
        "availability",
    }


def test_catalog_recovery_request_limits_fuzzy_to_one_edit() -> None:
    parsed = CatalogSearchQuery(
        original_query="토리덴",
        text_query="토리덴",
        normalized_query="토리덴",
        compact_query="토리덴",
        filters=CatalogSearchFilters((), (), (), None, None, None, None),
        sort=CatalogSearchSort.RELEVANCE,
    )

    request = build_catalog_search_request(
        parsed,
        offset=0,
        limit=20,
        recovery_variants=("토리든",),
        fuzzy_enabled=True,
        recovery_only=True,
    )
    should = request["query"]["script_score"]["query"]["bool"]["should"]
    fuzzy_clause = next(clause["multi_match"] for clause in should if "fuzziness" in clause.get("multi_match", {}))

    assert fuzzy_clause["fuzziness"] == 1
    assert fuzzy_clause["boost"] == 1.0
    assert len(request["suggest"]["catalog_correction"]["term"]) == 5
    assert "product_name_chosung" not in str(should)


def test_catalog_chosung_request_does_not_add_fuzzy_query() -> None:
    parsed = CatalogSearchQuery(
        original_query="ㅌㄹㄷ",
        text_query="ㅌㄹㄷ",
        normalized_query="ㅌㄹㄷ",
        compact_query="ㅌㄹㄷ",
        filters=CatalogSearchFilters((), (), (), None, None, None, None),
        sort=CatalogSearchSort.RELEVANCE,
    )

    request = build_catalog_search_request(parsed, offset=0, limit=20)
    query_text = str(request["query"])

    assert "product_name_chosung^1.5" in query_text
    assert "fuzziness" not in query_text


def test_catalog_suggestion_request_supports_prefix_compact_and_chosung() -> None:
    prefix_request = build_catalog_suggestion_request("라운", limit=8)
    chosung_request = build_catalog_suggestion_request("ㄹㅇㄷㄹ", limit=8)

    assert "product_name.edge^4" in str(prefix_request["query"])
    assert "product_name_compact" in str(prefix_request["query"])
    assert "brand_name_chosung^6" in str(chosung_request["query"])
    assert "suggest" not in chosung_request
