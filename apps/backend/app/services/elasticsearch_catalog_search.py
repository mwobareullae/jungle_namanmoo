from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_query import CatalogSearchQuery
from app.services.catalog_search_text import extract_chosung
from app.services.elasticsearch_client import (
    ElasticsearchClientProvider,
    default_elasticsearch_client_provider,
)


PRICE_RANGE_AGGREGATION = {
    "field": "lowest_price",
    "keyed": True,
    "ranges": [
        {"key": "under_10000", "from": 0, "to": 10_000},
        {"key": "10000_19999", "from": 10_000, "to": 20_000},
        {"key": "20000_29999", "from": 20_000, "to": 30_000},
        {"key": "30000_49999", "from": 30_000, "to": 50_000},
        {"key": "50000_plus", "from": 50_000},
    ],
}


@dataclass(frozen=True)
class ElasticsearchCatalogSearchResult:
    product_db_ids: tuple[int, ...]
    total_hit_count: int
    aggregations: dict[str, Any]
    attempted: bool
    duration_ms: int
    index_alias: str
    failure_reason: str | None = None

    @property
    def successful(self) -> bool:
        return self.attempted and self.failure_reason is None


def search_elasticsearch_catalog_products(
    parsed_query: CatalogSearchQuery,
    *,
    offset: int,
    limit: int,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_alias: str = settings.elasticsearch_catalog_products_alias,
) -> ElasticsearchCatalogSearchResult:
    started_at = perf_counter()
    if not client_provider.enabled:
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(),
            total_hit_count=0,
            aggregations={},
            attempted=False,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason="Elasticsearch is disabled by search backend mode.",
        )

    client = client_provider.get_client()
    if client is None:
        status = client_provider.status()
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(),
            total_hit_count=0,
            aggregations={},
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason=status.failure_reason or "Elasticsearch client unavailable.",
        )

    request = build_catalog_search_request(
        parsed_query,
        offset=max(0, offset),
        limit=max(1, limit),
    )
    try:
        response = client.search(index=index_alias, **request)
        payload = _response_dict(response)
        client_provider.mark_success()
        return ElasticsearchCatalogSearchResult(
            product_db_ids=tuple(_extract_product_db_ids(payload)),
            total_hit_count=_total_hit_count(payload),
            aggregations=dict(payload.get("aggregations") or {}),
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
        )
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        return ElasticsearchCatalogSearchResult(
            product_db_ids=(),
            total_hit_count=0,
            aggregations={},
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason=str(exc),
        )


def build_catalog_search_request(
    parsed_query: CatalogSearchQuery,
    *,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    return {
        "from_": max(0, offset),
        "size": max(1, limit),
        "query": _build_scored_query(parsed_query),
        "sort": _sort_clause(parsed_query.sort),
        "track_total_hits": True,
        "track_scores": True,
        "source": ["product_db_id", "product_id"],
        "aggregations": {
            "brands": {"terms": {"field": "brand_code", "size": 50}},
            "categories": {"terms": {"field": "category_group", "size": 20}},
            "price_ranges": {"range": PRICE_RANGE_AGGREGATION},
            "availability": {
                "filters": {
                    "filters": {
                        "in_stock": {"term": {"in_stock": True}},
                        "sold_out": {"term": {"sales_status": "SOLD_OUT"}},
                    }
                }
            },
        },
    }


def _build_scored_query(parsed_query: CatalogSearchQuery) -> dict[str, Any]:
    return {
        "script_score": {
            "query": _build_base_query(parsed_query),
            "script": {
                "source": (
                    "double popularity = doc['popularity_score'].size() == 0 ? 0.0 "
                    ": Math.max(doc['popularity_score'].value, 0.0); "
                    "double popularityRatio = Math.min(Math.log(1.0 + popularity) / Math.log(101.0), 1.0); "
                    "double rating = doc['rating'].size() == 0 ? 0.0 "
                    ": Math.min(Math.max(doc['rating'].value, 0.0), 5.0); "
                    "double reviews = doc['review_count'].size() == 0 ? 0.0 "
                    ": Math.max(doc['review_count'].value, 0.0); "
                    "double reviewRatio = Math.min(Math.log(1.0 + reviews) / Math.log(10001.0), 1.0); "
                    "double marketFactor = 1.0 + (0.10 * popularityRatio) "
                    "+ (0.03 * rating / 5.0) + (0.02 * reviewRatio); "
                    "double stockFactor = doc['sales_status'].size() != 0 "
                    "&& doc['sales_status'].value.equals('SOLD_OUT') ? 0.5 : 1.0; "
                    "return Math.max(_score, 0.0001) * marketFactor * stockFactor;"
                )
            },
        }
    }


def _build_base_query(parsed_query: CatalogSearchQuery) -> dict[str, Any]:
    filters = _filter_clauses(parsed_query)
    if not parsed_query.text_query:
        return {"bool": {"must": [{"match_all": {}}], "filter": filters}}

    should: list[dict[str, Any]] = [
        {
            "term": {
                "product_id": {
                    "value": parsed_query.original_query.casefold(),
                    "boost": 40.0,
                }
            }
        },
        {
            "term": {
                "product_name_normalized": {
                    "value": parsed_query.normalized_query,
                    "boost": 30.0,
                }
            }
        },
        {
            "term": {
                "product_name_compact": {
                    "value": parsed_query.compact_query,
                    "boost": 24.0,
                }
            }
        },
        {
            "match_phrase": {
                "product_name": {
                    "query": parsed_query.text_query,
                    "boost": 16.0,
                    "slop": 0,
                }
            }
        },
        {
            "multi_match": {
                "query": parsed_query.text_query,
                "type": "cross_fields",
                "operator": "and",
                "fields": [
                    "product_name^10",
                    "brand_name^7",
                    "category_name^4",
                    "category_aliases^4",
                    "ingredient_names^2",
                    "ingredient_aliases^1.5",
                    "effect_names^2",
                    "effect_aliases^1.5",
                    "brand_aliases^1.5",
                    "aliases^1.5",
                ],
            }
        },
    ]
    chosung_query = extract_chosung(parsed_query.text_query)
    if chosung_query:
        should.append(
            {
                "multi_match": {
                    "query": chosung_query,
                    "operator": "and",
                    "fields": ["product_name_chosung^1.5", "brand_name_chosung^1.5"],
                }
            }
        )
    return {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
            "filter": filters,
        }
    }


def _filter_clauses(parsed_query: CatalogSearchQuery) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    search_filters = parsed_query.filters
    if search_filters.brand_codes:
        filters.append({"terms": {"brand_code": list(search_filters.brand_codes)}})
    category_should: list[dict[str, Any]] = []
    if search_filters.category_codes:
        category_should.append({"terms": {"category_code": list(search_filters.category_codes)}})
    if search_filters.category_groups:
        category_should.append({"terms": {"category_group": list(search_filters.category_groups)}})
    if category_should:
        filters.append(
            {
                "bool": {
                    "should": category_should,
                    "minimum_should_match": 1,
                }
            }
        )
    price_range: dict[str, int] = {}
    if search_filters.min_price is not None:
        price_range["gte"] = search_filters.min_price
    if search_filters.max_price is not None:
        price_range["lte"] = search_filters.max_price
    if price_range:
        filters.append({"range": {"lowest_price": price_range}})
    if search_filters.min_rating is not None:
        filters.append({"range": {"rating": {"gte": search_filters.min_rating}}})
    if search_filters.in_stock is True:
        filters.append({"term": {"in_stock": True}})
    return filters


def _sort_clause(sort: CatalogSearchSort) -> list[dict[str, Any]]:
    stable_id = {"product_id": {"order": "asc"}}
    if sort == CatalogSearchSort.POPULAR:
        return [
            {"popularity_score": {"order": "desc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
            stable_id,
        ]
    if sort == CatalogSearchSort.NEWEST:
        return [
            {"created_at": {"order": "desc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
            stable_id,
        ]
    if sort == CatalogSearchSort.PRICE_ASC:
        return [
            {"lowest_price": {"order": "asc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
            stable_id,
        ]
    if sort == CatalogSearchSort.PRICE_DESC:
        return [
            {"lowest_price": {"order": "desc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
            stable_id,
        ]
    if sort == CatalogSearchSort.RATING:
        return [
            {"rating": {"order": "desc", "missing": "_last"}},
            {"review_count": {"order": "desc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
            stable_id,
        ]
    return [{"_score": {"order": "desc"}}, stable_id]


def _extract_product_db_ids(payload: dict[str, Any]) -> list[int]:
    product_db_ids: list[int] = []
    seen: set[int] = set()
    for hit in ((payload.get("hits") or {}).get("hits") or []):
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source") or {}
        try:
            product_db_id = int(source.get("product_db_id"))
        except (TypeError, ValueError):
            continue
        if product_db_id in seen:
            continue
        seen.add(product_db_id)
        product_db_ids.append(product_db_id)
    return product_db_ids


def _total_hit_count(payload: dict[str, Any]) -> int:
    total = (payload.get("hits") or {}).get("total")
    if isinstance(total, dict):
        total = total.get("value")
    try:
        return int(total)
    except (TypeError, ValueError):
        return len((payload.get("hits") or {}).get("hits") or [])


def _response_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    body = getattr(response, "body", None)
    if isinstance(body, dict):
        return body
    return dict(response)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
