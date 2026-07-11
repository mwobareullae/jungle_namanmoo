from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_query import CatalogSearchFilters, CatalogSearchQuery
from app.services.elasticsearch_catalog_search import build_catalog_search_request


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
