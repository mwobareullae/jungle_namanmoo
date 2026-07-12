from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.schemas.catalog_search import CatalogSearchSort
from app.services.catalog_search_query import CatalogSearchQuery
from app.services.catalog_search_text import (
    compact_search_text,
    extract_chosung,
    is_all_chosung_query,
    normalize_query_text,
)
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
    suggested_queries: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        return self.attempted and self.failure_reason is None


@dataclass(frozen=True)
class CatalogSuggestionDocument:
    product_id: str
    product_name: str
    brand_name: str
    category_code: str
    category_group: str
    category_name: str


@dataclass(frozen=True)
class ElasticsearchCatalogSuggestionResult:
    documents: tuple[CatalogSuggestionDocument, ...]
    suggested_queries: tuple[str, ...]
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
    recovery_variants: Sequence[str] = (),
    fuzzy_enabled: bool = False,
    recovery_only: bool = False,
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
        recovery_variants=recovery_variants,
        fuzzy_enabled=fuzzy_enabled,
        recovery_only=recovery_only,
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
            suggested_queries=_extract_suggested_queries(payload, parsed_query.text_query),
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


def search_elasticsearch_catalog_suggestions(
    query: str,
    *,
    limit: int,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_alias: str = settings.elasticsearch_catalog_products_alias,
) -> ElasticsearchCatalogSuggestionResult:
    started_at = perf_counter()
    if not client_provider.enabled:
        return ElasticsearchCatalogSuggestionResult(
            documents=(),
            suggested_queries=(),
            attempted=False,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason="Elasticsearch is disabled by search backend mode.",
        )
    client = client_provider.get_client()
    if client is None:
        status = client_provider.status()
        return ElasticsearchCatalogSuggestionResult(
            documents=(),
            suggested_queries=(),
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason=status.failure_reason or "Elasticsearch client unavailable.",
        )
    try:
        response = client.search(
            index=index_alias,
            **build_catalog_suggestion_request(query, limit=limit),
        )
        payload = _response_dict(response)
        client_provider.mark_success()
        return ElasticsearchCatalogSuggestionResult(
            documents=tuple(_extract_suggestion_documents(payload)),
            suggested_queries=_extract_suggested_queries(payload, query),
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
        )
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        return ElasticsearchCatalogSuggestionResult(
            documents=(),
            suggested_queries=(),
            attempted=True,
            duration_ms=_elapsed_ms(started_at),
            index_alias=index_alias,
            failure_reason=str(exc),
        )


def build_catalog_suggestion_request(query: str, *, limit: int) -> dict[str, Any]:
    normalized_query = normalize_query_text(query)
    compact_query = compact_search_text(query)
    if is_all_chosung_query(normalized_query):
        should: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": extract_chosung(normalized_query),
                    "operator": "and",
                    "fields": [
                        "product_name_chosung^4",
                        "brand_name_chosung^6",
                        "aliases_chosung^5",
                    ],
                }
            }
        ]
    else:
        should = [
            {
                "multi_match": {
                    "query": normalized_query,
                    "operator": "and",
                    "fields": [
                        "product_name.edge^4",
                        "brand_name.edge^6",
                        "brand_aliases.edge^5",
                        "category_aliases.edge^3",
                        "all_text.edge^1",
                    ],
                }
            },
            {
                "multi_match": {
                    "query": normalized_query,
                    "operator": "and",
                    "fields": [
                        "product_name^2",
                        "brand_name^3",
                        "brand_aliases^3",
                        "category_aliases^2",
                        "ingredient_names^1",
                        "effect_names^1",
                    ],
                }
            },
        ]
        if compact_query:
            should.append(
                {
                    "bool": {
                        "should": [
                            {"prefix": {"product_name_compact": compact_query}},
                            {"prefix": {"brand_name_compact": compact_query}},
                            {"prefix": {"aliases_compact": compact_query}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

    request: dict[str, Any] = {
        "size": max(1, limit),
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
        "sort": [
            {"_score": {"order": "desc"}},
            {"popularity_score": {"order": "desc", "missing": "_last"}},
            {"product_id": {"order": "asc"}},
        ],
        "source": [
            "product_id",
            "product_name",
            "brand_name",
            "category_code",
            "category_group",
            "category_name",
        ],
    }
    if len(compact_query) >= 3 and not is_all_chosung_query(normalized_query):
        request["suggest"] = {
            "catalog_correction": {
                "text": normalized_query,
                "term": {
                    "field": "all_text",
                    "suggest_mode": "missing",
                    "max_edits": 1,
                    "prefix_length": 1,
                    "size": 3,
                },
            }
        }
    return request


def build_catalog_search_request(
    parsed_query: CatalogSearchQuery,
    *,
    offset: int,
    limit: int,
    recovery_variants: Sequence[str] = (),
    fuzzy_enabled: bool = False,
    recovery_only: bool = False,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "from_": max(0, offset),
        "size": max(1, limit),
        "query": _build_scored_query(
            parsed_query,
            recovery_variants=recovery_variants,
            fuzzy_enabled=fuzzy_enabled,
            recovery_only=recovery_only,
        ),
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
    if recovery_only and fuzzy_enabled:
        request["suggest"] = {
            "catalog_correction": {
                "text": parsed_query.text_query,
                "term": {
                    "field": "all_text",
                    "suggest_mode": "missing",
                    "max_edits": 1,
                    "prefix_length": 1,
                    "size": 5,
                },
            }
        }
    return request


def _build_scored_query(
    parsed_query: CatalogSearchQuery,
    *,
    recovery_variants: Sequence[str],
    fuzzy_enabled: bool,
    recovery_only: bool,
) -> dict[str, Any]:
    return {
        "script_score": {
            "query": _build_base_query(
                parsed_query,
                recovery_variants=recovery_variants,
                fuzzy_enabled=fuzzy_enabled,
                recovery_only=recovery_only,
            ),
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


def _build_base_query(
    parsed_query: CatalogSearchQuery,
    *,
    recovery_variants: Sequence[str],
    fuzzy_enabled: bool,
    recovery_only: bool,
) -> dict[str, Any]:
    filters = _filter_clauses(parsed_query)
    if not parsed_query.text_query:
        return {"bool": {"must": [{"match_all": {}}], "filter": filters}}

    if is_all_chosung_query(parsed_query.text_query):
        return {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": extract_chosung(parsed_query.text_query),
                            "operator": "and",
                            "fields": [
                                "product_name_chosung^1.5",
                                "brand_name_chosung^1.5",
                                "aliases_chosung^1.5",
                            ],
                        }
                    }
                ],
                "minimum_should_match": 1,
                "filter": filters,
            }
        }

    should: list[dict[str, Any]] = []
    if not recovery_only:
        should.extend([
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
                    "all_text^1",
                ],
            }
        },
        {
            "multi_match": {
                "query": parsed_query.text_query,
                "operator": "and",
                "fields": [
                    "product_name.edge^1.5",
                    "brand_name.edge^1.5",
                    "brand_aliases.edge^1.5",
                    "category_aliases.edge^1.5",
                    "all_text.edge^1.0",
                ],
            }
        },
        ])

    for variant in recovery_variants[:5]:
        normalized_variant = normalize_query_text(variant)
        compact_variant = compact_search_text(variant)
        if not normalized_variant:
            continue
        should.append(
            {
                "multi_match": {
                    "query": normalized_variant,
                    "type": "cross_fields",
                    "operator": "and",
                    "boost": 1.5,
                    "fields": [
                        "product_name^1.5",
                        "brand_name^1.5",
                        "brand_aliases^1.5",
                        "category_name^1.0",
                        "category_aliases^1.0",
                        "ingredient_names^1.0",
                        "ingredient_aliases^1.0",
                        "effect_names^1.0",
                        "effect_aliases^1.0",
                        "aliases^1.0",
                    ],
                }
            }
        )
        if compact_variant:
            should.append(
                {
                    "bool": {
                        "boost": 1.5,
                        "should": [
                            {"prefix": {"product_name_compact": compact_variant}},
                            {"prefix": {"brand_name_compact": compact_variant}},
                            {"prefix": {"aliases_compact": compact_variant}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

    if fuzzy_enabled and len(parsed_query.compact_query) >= 3:
        should.append(
            {
                "multi_match": {
                    "query": parsed_query.text_query,
                    "type": "best_fields",
                    "operator": "and",
                    "fuzziness": 1,
                    "prefix_length": 1,
                    "max_expansions": 20,
                    "boost": 1.0,
                    "fields": [
                        "product_name^1.0",
                        "brand_name^1.0",
                        "brand_aliases^1.0",
                        "ingredient_names^1.0",
                        "ingredient_aliases^1.0",
                        "effect_names^1.0",
                        "effect_aliases^1.0",
                    ],
                }
            }
        )

    if not should:
        return {"bool": {"must": [{"match_none": {}}], "filter": filters}}
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


def _extract_suggestion_documents(payload: dict[str, Any]) -> list[CatalogSuggestionDocument]:
    documents: list[CatalogSuggestionDocument] = []
    seen: set[str] = set()
    for hit in ((payload.get("hits") or {}).get("hits") or []):
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source") or {}
        product_id = str(source.get("product_id") or "").strip()
        product_name = str(source.get("product_name") or "").strip()
        if not product_id or not product_name or product_id in seen:
            continue
        seen.add(product_id)
        documents.append(
            CatalogSuggestionDocument(
                product_id=product_id,
                product_name=product_name,
                brand_name=str(source.get("brand_name") or "").strip(),
                category_code=str(source.get("category_code") or "").strip(),
                category_group=str(source.get("category_group") or "other").strip(),
                category_name=str(source.get("category_name") or "").strip(),
            )
        )
    return documents


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


def _extract_suggested_queries(payload: dict[str, Any], original_query: str) -> tuple[str, ...]:
    suggest = payload.get("suggest") or {}
    entries = suggest.get("catalog_correction") or []
    if not isinstance(entries, list) or not entries:
        return ()
    corrected_tokens: list[str] = []
    changed = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        original_token = str(entry.get("text") or "").strip()
        options = entry.get("options") or []
        replacement = original_token
        if options and isinstance(options[0], dict):
            replacement = str(options[0].get("text") or original_token).strip()
            changed = changed or replacement != original_token
        if replacement:
            corrected_tokens.append(replacement)
    if not changed or not corrected_tokens:
        return ()
    corrected = normalize_query_text(" ".join(corrected_tokens))
    if not corrected or corrected == normalize_query_text(original_query):
        return ()
    return (corrected,)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
