from __future__ import annotations

from dataclasses import dataclass
import queue
import socket
import threading
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings
from app.services.elasticsearch_client import (
    ElasticsearchClientProvider,
    default_elasticsearch_client_provider,
)
from app.services.recommendation_intent import RecommendationIntent


ES_KEYWORD_SEARCH_SOURCE = "es_keyword_search"
SEARCH_FIELDS = (
    "title^4",
    "keywords^3",
    "brand_name^2",
    "category_name^2",
    "content",
)


@dataclass(frozen=True)
class ElasticsearchProductSearchResult:
    product_db_ids: tuple[int, ...]
    raw_hit_count: int
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


def search_elasticsearch_product_candidates(
    intent: RecommendationIntent,
    *,
    limit: int,
    offset: int = 0,
    client_provider: ElasticsearchClientProvider = default_elasticsearch_client_provider,
    index_alias: str = settings.elasticsearch_products_alias,
) -> ElasticsearchProductSearchResult:
    started_at = perf_counter()
    query_text = _build_query_text(intent)

    if not client_provider.enabled:
        return _skipped_result(
            index_alias=index_alias,
            query_text=query_text,
            started_at=started_at,
            reason="search backend mode is postgres",
        )

    if not query_text and not intent.purchase_conditions.has_constraints:
        return _skipped_result(
            index_alias=index_alias,
            query_text=query_text,
            started_at=started_at,
            reason="empty query and no hard filters",
        )

    client = client_provider.get_client()
    if client is None:
        status = client_provider.status()
        return ElasticsearchProductSearchResult(
            product_db_ids=(),
            raw_hit_count=0,
            attempted=True,
            index_alias=index_alias,
            query_text=query_text,
            duration_ms=_elapsed_ms(started_at),
            failure_reason=status.failure_reason or "Elasticsearch client unavailable",
            total_hit_count=0,
        )

    reachable, unreachable_reason = _endpoint_is_reachable(client_provider)
    if not reachable:
        failure_reason = f"Elasticsearch endpoint unavailable: {unreachable_reason}"
        client_provider.mark_failure(failure_reason)
        return ElasticsearchProductSearchResult(
            product_db_ids=(),
            raw_hit_count=0,
            attempted=True,
            index_alias=index_alias,
            query_text=query_text,
            duration_ms=_elapsed_ms(started_at),
            failure_reason=failure_reason,
            total_hit_count=0,
        )

    try:
        response = client.search(
            index=index_alias,
            size=max(1, limit),
            from_=max(0, offset),
            query=_build_query(intent, query_text),
            source=[
                "product_db_id",
                "product_id",
                "document_code",
                "title",
            ],
        )
        product_db_ids = _extract_product_db_ids(response)
        client_provider.mark_success()
        return ElasticsearchProductSearchResult(
            product_db_ids=tuple(product_db_ids[:limit]),
            raw_hit_count=_hit_count(response),
            attempted=True,
            index_alias=index_alias,
            query_text=query_text,
            duration_ms=_elapsed_ms(started_at),
            total_hit_count=_total_hit_count(response),
        )
    except Exception as exc:
        client_provider.mark_failure(str(exc))
        return ElasticsearchProductSearchResult(
            product_db_ids=(),
            raw_hit_count=0,
            attempted=True,
            index_alias=index_alias,
            query_text=query_text,
            duration_ms=_elapsed_ms(started_at),
            failure_reason=str(exc),
            total_hit_count=0,
        )


def _build_query(intent: RecommendationIntent, query_text: str) -> dict[str, Any]:
    filters: list[dict[str, Any]] = []
    conditions = intent.purchase_conditions
    if conditions.categories:
        filters.append(
            {
                "terms": {
                    "category_code": [
                        category.category_code
                        for category in conditions.categories
                    ]
                }
            }
        )
    if conditions.brands:
        filters.append(
            {
                "terms": {
                    "brand_code": [
                        brand.brand_code
                        for brand in conditions.brands
                    ]
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

    if not query_text:
        return {"bool": {"must": [{"match_all": {}}], "filter": filters}}

    return {
        "bool": {
            "must": [
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": list(SEARCH_FIELDS),
                        "type": "best_fields",
                        "operator": "or",
                    }
                }
            ],
            "filter": filters,
        }
    }


def _endpoint_is_reachable(client_provider: ElasticsearchClientProvider) -> tuple[bool, str | None]:
    url = getattr(client_provider, "url", None)
    if not url:
        return True, None
    parsed = urlparse(url)
    if not parsed.hostname:
        return True, None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    timeout_seconds = max(float(getattr(client_provider, "timeout_seconds", 2.0)), 0.1)
    result_queue: queue.Queue[tuple[bool, str | None]] = queue.Queue(maxsize=1)
    thread = threading.Thread(
        target=_check_socket_connection,
        args=(parsed.hostname, port, timeout_seconds, result_queue),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        return False, f"connection check timed out after {timeout_seconds}s"
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        return False, "connection check did not return a result"


def _check_socket_connection(
    hostname: str,
    port: int,
    timeout_seconds: float,
    result_queue: queue.Queue[tuple[bool, str | None]],
) -> None:
    try:
        with socket.create_connection((hostname, port), timeout=timeout_seconds):
            result_queue.put((True, None))
    except Exception as exc:
        result_queue.put((False, str(exc)))


def _build_query_text(intent: RecommendationIntent) -> str:
    terms = [
        intent.concern_text,
        *intent.search_terms,
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(term.strip())
    return " ".join(deduped)


def _extract_product_db_ids(response: Any) -> list[int]:
    product_db_ids: list[int] = []
    seen: set[int] = set()
    for hit in _hits(response):
        source = hit.get("_source") or {}
        value = source.get("product_db_id")
        if value is None and isinstance(source.get("product_id"), int):
            value = source.get("product_id")
        product_db_id = _parse_int(value)
        if product_db_id is None or product_db_id in seen:
            continue
        seen.add(product_db_id)
        product_db_ids.append(product_db_id)
    return product_db_ids


def _hit_count(response: Any) -> int:
    return len(_hits(response))


def _total_hit_count(response: Any) -> int:
    if not isinstance(response, dict):
        response = dict(response)
    total = (response.get("hits") or {}).get("total")
    if isinstance(total, dict):
        value = total.get("value")
        parsed = _parse_int(value)
        return parsed if parsed is not None else _hit_count(response)
    parsed = _parse_int(total)
    return parsed if parsed is not None else _hit_count(response)


def _hits(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        response = dict(response)
    hits_payload = response.get("hits") or {}
    hits = hits_payload.get("hits") or []
    return [
        hit
        for hit in hits
        if isinstance(hit, dict)
    ]


def _parse_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _skipped_result(
    *,
    index_alias: str,
    query_text: str,
    started_at: float,
    reason: str,
) -> ElasticsearchProductSearchResult:
    return ElasticsearchProductSearchResult(
        product_db_ids=(),
        raw_hit_count=0,
        attempted=False,
        index_alias=index_alias,
        query_text=query_text,
        duration_ms=_elapsed_ms(started_at),
        skipped_reason=reason,
        total_hit_count=0,
    )


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)
