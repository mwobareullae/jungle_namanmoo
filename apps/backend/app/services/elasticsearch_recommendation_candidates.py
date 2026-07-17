from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.services.catalog_search_filters import feature_codes_for_effect_codes
from app.services.elasticsearch_client import (
    ElasticsearchClientProvider,
    default_elasticsearch_client_provider,
)
from app.services.product_candidates import ProductCandidate
from app.services.recommendation_intent import RecommendationIntent


RECOMMENDATION_CANDIDATE_SOURCE = "catalog_es_recommendation"
RECOMMENDATION_CANDIDATE_STRATEGY_VERSION = "candidate_pool_catalog_es_v2"
RECOMMENDATION_CANDIDATE_SOURCE_FIELDS = (
    "product_db_id",
    "product_id",
    "product_name",
    "brand_code",
    "brand_name",
    "category_code",
    "lowest_price",
)
RECOMMENDATION_RELEVANCE_FIELDS = (
    "product_name^8",
    "brand_name^7",
    "brand_aliases^7",
    "category_name^4",
    "category_aliases^3",
    "ingredient_names^4",
    "ingredient_aliases^3",
    "effect_names^6",
    "effect_aliases^5",
    "all_text^1",
)
RECOMMENDATION_INTENT_FIELDS = (
    "effect_names^8",
    "effect_aliases^6",
    "ingredient_names^5",
    "ingredient_aliases^4",
    "product_name^3",
    "category_name^3",
    "category_aliases^2",
    "all_text^1",
)


@dataclass(frozen=True)
class ElasticsearchRecommendationCandidateResult:
    candidates: tuple[ProductCandidate, ...]
    raw_hit_count: int
    direct_match_count: int
    popularity_fill_count: int
    pre_dedupe_count: int
    deduped_count: int
    attempted: bool
    index_alias: str
    query_text: str
    duration_ms: int
    failure_reason: str | None = None
    skipped_reason: str | None = None
    total_hit_count: int | None = None

    @property
    def successful(self) -> bool:
        return self.attempted and self.failure_reason is None and self.skipped_reason is None


def search_elasticsearch_recommendation_candidates(
    intent: RecommendationIntent,
    *,
    avoid_ingredients: list[str],
    limit: int,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_alias: str = settings.elasticsearch_catalog_products_alias,
) -> ElasticsearchRecommendationCandidateResult:
    started_at = perf_counter()
    requested_limit = max(1, limit)
    query_text = intent.semantic_query_text.strip()

    if not client_provider.enabled:
        return _skipped_result(
            index_alias=index_alias,
            query_text=query_text,
            started_at=started_at,
            reason="search backend mode is postgres",
        )

    client = client_provider.get_client()
    if client is None:
        status = client_provider.status()
        return _failed_result(
            index_alias=index_alias,
            query_text=query_text,
            started_at=started_at,
            reason=status.failure_reason or "Elasticsearch client unavailable",
        )

    direct_hits: list[dict[str, Any]] = []
    fill_hits: list[dict[str, Any]] = []
    try:
        direct_response = client.search(
            index=index_alias,
            **build_recommendation_candidate_request(
                intent,
                avoid_ingredients=avoid_ingredients,
                limit=requested_limit,
            ),
        )
        direct_payload = _response_dict(direct_response)
        direct_hits = _hits(direct_payload)
        direct_candidates = _dedupe_candidates(_extract_candidates(direct_hits))
        total_hit_count = _total_hit_count(direct_payload)

        remaining = max(0, requested_limit - len(direct_candidates))
        if remaining:
            fill_response = client.search(
                index=index_alias,
                **build_recommendation_popularity_fill_request(
                    intent,
                    avoid_ingredients=avoid_ingredients,
                    excluded_product_db_ids=tuple(
                        candidate.db_product_id for candidate in direct_candidates
                    ),
                    limit=remaining,
                ),
            )
            fill_hits = _hits(_response_dict(fill_response))

        fill_candidates = _dedupe_candidates(_extract_candidates(fill_hits))
        merged_candidates = [*direct_candidates, *fill_candidates]
        deduped_candidates = _dedupe_candidates(merged_candidates)
        final_candidates = deduped_candidates[:requested_limit]
        direct_ids = {candidate.db_product_id for candidate in direct_candidates}
        popularity_fill_count = sum(
            candidate.db_product_id not in direct_ids
            for candidate in final_candidates[len(direct_candidates) :]
        )

        client_provider.mark_success()
        return ElasticsearchRecommendationCandidateResult(
            candidates=tuple(final_candidates),
            raw_hit_count=len(direct_hits) + len(fill_hits),
            direct_match_count=min(len(direct_candidates), requested_limit),
            popularity_fill_count=popularity_fill_count,
            pre_dedupe_count=len(merged_candidates),
            deduped_count=len(deduped_candidates),
            attempted=True,
            index_alias=index_alias,
            query_text=query_text,
            duration_ms=_elapsed_ms(started_at),
            total_hit_count=total_hit_count,
        )
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        return _failed_result(
            index_alias=index_alias,
            query_text=query_text,
            started_at=started_at,
            reason=str(exc),
            raw_hit_count=len(direct_hits) + len(fill_hits),
        )


def build_recommendation_candidate_request(
    intent: RecommendationIntent,
    *,
    avoid_ingredients: list[str],
    limit: int,
) -> dict[str, Any]:
    bool_query = _base_bool_query(intent, avoid_ingredients=avoid_ingredients)
    return {
        "size": max(1, limit),
        "track_total_hits": True,
        "track_scores": True,
        "query": {
            "function_score": {
                "query": bool_query,
                "functions": _small_market_signal_functions(),
                "score_mode": "sum",
                "boost_mode": "sum",
                "max_boost": 2.0,
            }
        },
        "sort": [
            {"_score": {"order": "desc"}},
            {"popularity_score": {"order": "desc", "missing": "_last"}},
            {"rating": {"order": "desc", "missing": "_last"}},
            {"review_count": {"order": "desc", "missing": "_last"}},
            {"product_id": {"order": "asc"}},
        ],
        "source": list(RECOMMENDATION_CANDIDATE_SOURCE_FIELDS),
    }


def build_recommendation_popularity_fill_request(
    intent: RecommendationIntent,
    *,
    avoid_ingredients: list[str],
    excluded_product_db_ids: tuple[int, ...],
    limit: int,
) -> dict[str, Any]:
    filters = _hard_filters(intent)
    must_not = _avoid_ingredient_clauses(avoid_ingredients)
    if excluded_product_db_ids:
        must_not.append(
            {"terms": {"product_db_id": list(excluded_product_db_ids)}}
        )
    return {
        "size": max(1, limit),
        "track_total_hits": False,
        "query": {
            "bool": {
                "must": [{"match_all": {}}],
                "filter": filters,
                "must_not": must_not,
            }
        },
        "sort": [
            {"popularity_score": {"order": "desc", "missing": "_last"}},
            {"in_stock": {"order": "desc", "missing": "_last"}},
            {"rating": {"order": "desc", "missing": "_last"}},
            {"review_count": {"order": "desc", "missing": "_last"}},
            {"product_id": {"order": "asc"}},
        ],
        "source": list(RECOMMENDATION_CANDIDATE_SOURCE_FIELDS),
    }


def _base_bool_query(
    intent: RecommendationIntent,
    *,
    avoid_ingredients: list[str],
) -> dict[str, Any]:
    should: list[dict[str, Any]] = [
        {
            "multi_match": {
                "query": intent.concern_text,
                "type": "best_fields",
                "operator": "or",
                "fields": list(RECOMMENDATION_RELEVANCE_FIELDS),
            }
        }
    ]
    if intent.search_terms:
        should.append(
            {
                "multi_match": {
                    "query": " ".join(intent.search_terms),
                    "type": "best_fields",
                    "operator": "or",
                    "fields": list(RECOMMENDATION_INTENT_FIELDS),
                }
            }
        )
    effect_codes = tuple(
        effect.effect_id
        for effect in (*intent.effects, *intent.priority_effects)
    )
    feature_codes = feature_codes_for_effect_codes(effect_codes)
    if feature_codes:
        should.append(
            {
                "terms": {
                    "feature_codes": list(feature_codes),
                    "boost": 6.0,
                }
            }
        )
    return {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
            "filter": _hard_filters(intent),
            "must_not": _avoid_ingredient_clauses(avoid_ingredients),
        }
    }


def _hard_filters(intent: RecommendationIntent) -> list[dict[str, Any]]:
    conditions = intent.purchase_conditions
    filters: list[dict[str, Any]] = [
        {"term": {"is_recommendable": True}},
        {"exists": {"field": "lowest_price"}},
    ]
    if conditions.categories:
        filters.append(
            {
                "terms": {
                    "category_code": [
                        category.category_code for category in conditions.categories
                    ]
                }
            }
        )
    if conditions.brands:
        filters.append(
            {
                "terms": {
                    "brand_code": [brand.brand_code for brand in conditions.brands]
                }
            }
        )
    price_range: dict[str, int] = {}
    if conditions.price_min is not None:
        price_range["gte"] = conditions.price_min
    if conditions.price_max is not None:
        price_range["lte"] = conditions.price_max
    if price_range:
        filters.append({"range": {"lowest_price": price_range}})
    return filters


def _avoid_ingredient_clauses(avoid_ingredients: list[str]) -> list[dict[str, Any]]:
    terms = _normalized_filter_terms(avoid_ingredients)
    if not terms:
        return []
    return [
        {
            "bool": {
                "should": [
                    {"terms": {"ingredient_codes": terms}},
                    {"terms": {"ingredient_names.exact": terms}},
                    {"terms": {"ingredient_aliases.exact": terms}},
                ],
                "minimum_should_match": 1,
            }
        }
    ]


def _small_market_signal_functions() -> list[dict[str, Any]]:
    return [
        {
            "field_value_factor": {
                "field": "popularity_score",
                "factor": 0.01,
                "modifier": "log1p",
                "missing": 0,
            }
        },
        {
            "field_value_factor": {
                "field": "rating",
                "factor": 0.02,
                "modifier": "none",
                "missing": 0,
            }
        },
        {
            "field_value_factor": {
                "field": "review_count",
                "factor": 0.0001,
                "modifier": "log1p",
                "missing": 0,
            }
        },
    ]


def _extract_candidates(hits: list[dict[str, Any]]) -> list[ProductCandidate]:
    candidates: list[ProductCandidate] = []
    for hit in hits:
        source = hit.get("_source") or {}
        product_db_id = _parse_int(source.get("product_db_id"))
        lowest_price = _parse_int(source.get("lowest_price"))
        product_id = _required_text(source.get("product_id"))
        product_name = _required_text(source.get("product_name"))
        brand_code = _required_text(source.get("brand_code"))
        brand_name = _required_text(source.get("brand_name"))
        category_code = _required_text(source.get("category_code"))
        if (
            product_db_id is None
            or lowest_price is None
            or product_id is None
            or product_name is None
            or brand_code is None
            or brand_name is None
            or category_code is None
        ):
            continue
        candidates.append(
            ProductCandidate(
                db_product_id=product_db_id,
                product_id=product_id,
                brand_code=brand_code,
                brand=brand_name,
                category_code=category_code,
                name=product_name,
                thumbnail_url=None,
                lowest_price=lowest_price,
            )
        )
    return candidates


def _dedupe_candidates(candidates: list[ProductCandidate]) -> list[ProductCandidate]:
    deduped: list[ProductCandidate] = []
    seen: set[int] = set()
    for candidate in candidates:
        if candidate.db_product_id in seen:
            continue
        seen.add(candidate.db_product_id)
        deduped.append(candidate)
    return deduped


def _normalized_filter_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().casefold()
        if normalized and normalized not in seen:
            terms.append(normalized)
            seen.add(normalized)
    return terms


def _response_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    return dict(response)


def _hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = (payload.get("hits") or {}).get("hits") or []
    return [value for value in values if isinstance(value, dict)]


def _total_hit_count(payload: dict[str, Any]) -> int:
    total = (payload.get("hits") or {}).get("total")
    if isinstance(total, dict):
        parsed = _parse_int(total.get("value"))
        return parsed if parsed is not None else len(_hits(payload))
    parsed = _parse_int(total)
    return parsed if parsed is not None else len(_hits(payload))


def _parse_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _skipped_result(
    *,
    index_alias: str,
    query_text: str,
    started_at: float,
    reason: str,
) -> ElasticsearchRecommendationCandidateResult:
    return ElasticsearchRecommendationCandidateResult(
        candidates=(),
        raw_hit_count=0,
        direct_match_count=0,
        popularity_fill_count=0,
        pre_dedupe_count=0,
        deduped_count=0,
        attempted=False,
        index_alias=index_alias,
        query_text=query_text,
        duration_ms=_elapsed_ms(started_at),
        skipped_reason=reason,
        total_hit_count=0,
    )


def _failed_result(
    *,
    index_alias: str,
    query_text: str,
    started_at: float,
    reason: str,
    raw_hit_count: int = 0,
) -> ElasticsearchRecommendationCandidateResult:
    return ElasticsearchRecommendationCandidateResult(
        candidates=(),
        raw_hit_count=raw_hit_count,
        direct_match_count=0,
        popularity_fill_count=0,
        pre_dedupe_count=0,
        deduped_count=0,
        attempted=True,
        index_alias=index_alias,
        query_text=query_text,
        duration_ms=_elapsed_ms(started_at),
        failure_reason=reason,
        total_hit_count=0,
    )


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
