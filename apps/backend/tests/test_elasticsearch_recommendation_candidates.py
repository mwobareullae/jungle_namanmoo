from dataclasses import replace

from app.services.elasticsearch_recommendation_candidates import (
    RECOMMENDATION_CANDIDATE_SOURCE_FIELDS,
    build_recommendation_candidate_request,
    search_elasticsearch_recommendation_candidates,
)
from app.services.purchase_conditions import (
    MatchedBrand,
    MatchedCategory,
    ParsedPurchaseConditions,
)
from app.services.recommendation_intent import build_recommendation_intent


def test_recommendation_candidate_query_uses_catalog_fields_and_hard_filters() -> None:
    intent = _intent_with_hard_filters()

    request = build_recommendation_candidate_request(
        intent,
        avoid_ingredients=["Panthenol", "ING_CENTELLA"],
        limit=500,
    )

    assert request["size"] == 500
    assert request["source"] == list(RECOMMENDATION_CANDIDATE_SOURCE_FIELDS)
    bool_query = request["query"]["function_score"]["query"]["bool"]
    assert {"term": {"is_recommendable": True}} in bool_query["filter"]
    assert {"exists": {"field": "lowest_price"}} in bool_query["filter"]
    assert {"terms": {"category_code": ["serum"]}} in bool_query["filter"]
    assert {"terms": {"brand_code": ["brand_a"]}} in bool_query["filter"]
    assert {
        "range": {"lowest_price": {"gte": 10_000, "lte": 20_000}}
    } in bool_query["filter"]

    avoid_clause = bool_query["must_not"][0]["bool"]
    assert {"terms": {"ingredient_codes": ["panthenol", "ing_centella"]}} in (
        avoid_clause["should"]
    )
    assert {
        "terms": {"ingredient_names.exact": ["panthenol", "ing_centella"]}
    } in avoid_clause["should"]

    relevance_fields = {
        field.split("^", maxsplit=1)[0]
        for clause in bool_query["should"]
        if "multi_match" in clause
        for field in clause["multi_match"]["fields"]
    }
    assert {"product_name", "brand_name", "category_name", "all_text"} <= (
        relevance_fields
    )
    assert not {"title", "keywords", "content"} & relevance_fields


def test_recommendation_candidates_fill_short_result_with_same_hard_filters() -> None:
    direct_response = _response([_hit(1)], total=1)
    fill_response = _response([_hit(1), _hit(2)], total=2)
    client = _FakeElasticsearchClient([direct_response, fill_response])
    provider = _FakeElasticsearchProvider(client)

    result = search_elasticsearch_recommendation_candidates(
        _intent_with_hard_filters(),
        avoid_ingredients=["panthenol"],
        limit=3,
        client_provider=provider,
        index_alias="catalog_current",
    )

    assert [candidate.db_product_id for candidate in result.candidates] == [1, 2]
    assert all(candidate.thumbnail_url is None for candidate in result.candidates)
    assert result.direct_match_count == 1
    assert result.popularity_fill_count == 1
    assert result.raw_hit_count == 3
    assert result.pre_dedupe_count == 3
    assert result.deduped_count == 2
    assert result.total_hit_count == 1
    assert result.successful is True
    assert provider.success_marked is True

    direct_call, fill_call = client.search_calls
    assert direct_call["index"] == "catalog_current"
    assert fill_call["index"] == "catalog_current"
    direct_bool = direct_call["query"]["function_score"]["query"]["bool"]
    fill_bool = fill_call["query"]["bool"]
    assert fill_bool["filter"] == direct_bool["filter"]
    assert direct_bool["must_not"][0] in fill_bool["must_not"]
    assert {"terms": {"product_db_id": [1]}} in fill_bool["must_not"]


def test_recommendation_candidates_never_exceed_requested_limit() -> None:
    client = _FakeElasticsearchClient(
        [_response([_hit(1), _hit(2), _hit(1), _hit(3)], total=4)]
    )
    provider = _FakeElasticsearchProvider(client)

    result = search_elasticsearch_recommendation_candidates(
        build_recommendation_intent("hydration recommendation"),
        avoid_ingredients=[],
        limit=2,
        client_provider=provider,
        index_alias="catalog_current",
    )

    assert [candidate.db_product_id for candidate in result.candidates] == [1, 2]
    assert len(result.candidates) == 2
    assert len(client.search_calls) == 1


def test_recommendation_candidates_return_failure_for_es_error() -> None:
    provider = _FakeElasticsearchProvider(_FailingElasticsearchClient())

    result = search_elasticsearch_recommendation_candidates(
        build_recommendation_intent("hydration recommendation"),
        avoid_ingredients=[],
        limit=500,
        client_provider=provider,
        index_alias="catalog_current",
    )

    assert result.candidates == ()
    assert result.successful is False
    assert result.failure_reason == "alias missing"
    assert provider.failure_reason == "alias missing"


def _intent_with_hard_filters():
    base_intent = build_recommendation_intent("hydration serum from brand a")
    return replace(
        base_intent,
        purchase_conditions=ParsedPurchaseConditions(
            categories=(
                MatchedCategory(
                    category_code="serum",
                    name="Serum",
                    matched_text="serum",
                ),
            ),
            brands=(
                MatchedBrand(
                    brand_code="brand_a",
                    name="Brand A",
                    matched_text="brand a",
                ),
            ),
            price_min=10_000,
            price_max=20_000,
            price_text="10000 to 20000",
            price_max_text="20000",
        ),
    )


def _hit(product_db_id: int) -> dict:
    return {
        "_source": {
            "product_db_id": product_db_id,
            "product_id": f"prod_{product_db_id:03d}",
            "product_name": f"Product {product_db_id}",
            "brand_code": "brand_a",
            "brand_name": "Brand A",
            "category_code": "serum",
            "lowest_price": 10_000 + product_db_id,
        }
    }


def _response(hits: list[dict], *, total: int) -> dict:
    return {
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": hits,
        }
    }


class _FakeElasticsearchProvider:
    def __init__(self, client, *, enabled: bool = True) -> None:
        self.client = client
        self.enabled = enabled
        self.success_marked = False
        self.failure_reason = None

    def get_client(self):
        return self.client

    def mark_success(self) -> None:
        self.success_marked = True
        self.failure_reason = None

    def mark_failure(self, reason: str) -> None:
        self.failure_reason = reason

    def status(self):
        return _FakeStatus(self.failure_reason)


class _FakeStatus:
    def __init__(self, failure_reason: str | None) -> None:
        self.failure_reason = failure_reason


class _FakeElasticsearchClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.search_calls: list[dict] = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return self.responses.pop(0)


class _FailingElasticsearchClient:
    def search(self, **kwargs):
        raise RuntimeError("alias missing")
