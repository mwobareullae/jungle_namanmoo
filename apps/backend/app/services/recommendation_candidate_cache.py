from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Any, Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.product_candidates import ProductCandidate
from app.services.recommendation_intent import RecommendationIntent


CANDIDATE_CACHE_SCHEMA_VERSION = 1
CANDIDATE_CACHE_NAMESPACE = "recommendation:candidate_bundle:v1"


@dataclass(frozen=True)
class CachedCandidateBundle:
    candidates: tuple[ProductCandidate, ...]
    raw_hit_count: int
    direct_match_count: int
    popularity_fill_count: int
    pre_dedupe_count: int
    deduped_count: int
    total_hit_count: int | None


@dataclass(frozen=True)
class CandidateCacheLookup:
    bundle: CachedCandidateBundle | None
    lookup_ms: float
    ttl_seconds: int | None
    cache_enabled: bool
    failure_reason: str | None = None

    @property
    def hit(self) -> bool:
        return self.bundle is not None


@dataclass(frozen=True)
class CandidateCacheWrite:
    write_ms: float
    ttl_seconds: int | None
    failure_reason: str | None = None


class RecommendationCandidateCache(Protocol):
    def read(
        self,
        intent: RecommendationIntent,
        *,
        avoid_ingredients: list[str],
        target_pool_size: int,
        candidate_generation_version: str,
    ) -> CandidateCacheLookup: ...

    def write(
        self,
        intent: RecommendationIntent,
        *,
        avoid_ingredients: list[str],
        target_pool_size: int,
        candidate_generation_version: str,
        bundle: CachedCandidateBundle,
    ) -> CandidateCacheWrite: ...


class RedisRecommendationCandidateCache:
    def __init__(
        self,
        *,
        enabled: bool,
        redis_url: str,
        key_prefix: str,
        ttl_seconds: int,
        price_ttl_seconds: int,
        socket_connect_timeout_seconds: float,
        socket_timeout_seconds: float,
        client: Redis | None = None,
    ) -> None:
        self._enabled = enabled
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._ttl_seconds = max(1, ttl_seconds)
        self._price_ttl_seconds = max(1, price_ttl_seconds)
        self._socket_connect_timeout_seconds = max(0.001, socket_connect_timeout_seconds)
        self._socket_timeout_seconds = max(0.001, socket_timeout_seconds)
        self._client = client

    @classmethod
    def from_settings(cls) -> RedisRecommendationCandidateCache:
        return cls(
            enabled=settings.recommendation_candidate_cache_enabled,
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            ttl_seconds=settings.recommendation_candidate_cache_ttl_seconds,
            price_ttl_seconds=settings.recommendation_candidate_price_cache_ttl_seconds,
            socket_connect_timeout_seconds=(
                settings.recommendation_candidate_cache_socket_connect_timeout_seconds
            ),
            socket_timeout_seconds=settings.recommendation_candidate_cache_socket_timeout_seconds,
        )

    def read(
        self,
        intent: RecommendationIntent,
        *,
        avoid_ingredients: list[str],
        target_pool_size: int,
        candidate_generation_version: str,
    ) -> CandidateCacheLookup:
        started_at = perf_counter()
        if not self._enabled:
            return CandidateCacheLookup(
                bundle=None,
                lookup_ms=_elapsed_ms(started_at),
                ttl_seconds=None,
                cache_enabled=False,
            )

        ttl_seconds = self._ttl_for(intent)
        key = build_candidate_cache_key(
            intent,
            avoid_ingredients=avoid_ingredients,
            target_pool_size=target_pool_size,
            candidate_generation_version=candidate_generation_version,
            key_prefix=self._key_prefix,
        )
        try:
            raw_payload = self._get_client().get(key)
        except (RedisError, OSError, ValueError):
            return CandidateCacheLookup(
                bundle=None,
                lookup_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
                cache_enabled=True,
                failure_reason="redis_read_failed",
            )

        if raw_payload is None:
            return CandidateCacheLookup(
                bundle=None,
                lookup_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
                cache_enabled=True,
            )

        try:
            return CandidateCacheLookup(
                bundle=_deserialize_candidate_bundle(
                    raw_payload,
                    candidate_generation_version=candidate_generation_version,
                ),
                lookup_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
                cache_enabled=True,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return CandidateCacheLookup(
                bundle=None,
                lookup_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
                cache_enabled=True,
                failure_reason="redis_payload_invalid",
            )

    def write(
        self,
        intent: RecommendationIntent,
        *,
        avoid_ingredients: list[str],
        target_pool_size: int,
        candidate_generation_version: str,
        bundle: CachedCandidateBundle,
    ) -> CandidateCacheWrite:
        started_at = perf_counter()
        if not self._enabled:
            return CandidateCacheWrite(
                write_ms=_elapsed_ms(started_at),
                ttl_seconds=None,
            )

        ttl_seconds = self._ttl_for(intent)
        key = build_candidate_cache_key(
            intent,
            avoid_ingredients=avoid_ingredients,
            target_pool_size=target_pool_size,
            candidate_generation_version=candidate_generation_version,
            key_prefix=self._key_prefix,
        )
        payload = _serialize_candidate_bundle(
            bundle,
            candidate_generation_version=candidate_generation_version,
        )
        try:
            self._get_client().set(key, payload, ex=ttl_seconds)
            return CandidateCacheWrite(
                write_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
            )
        except (RedisError, OSError, ValueError):
            return CandidateCacheWrite(
                write_ms=_elapsed_ms(started_at),
                ttl_seconds=ttl_seconds,
                failure_reason="redis_write_failed",
            )

    def _get_client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=self._socket_connect_timeout_seconds,
                socket_timeout=self._socket_timeout_seconds,
            )
        return self._client

    def _ttl_for(self, intent: RecommendationIntent) -> int:
        conditions = intent.purchase_conditions
        if conditions.price_min is not None or conditions.price_max is not None:
            return self._price_ttl_seconds
        return self._ttl_seconds


@lru_cache(maxsize=1)
def get_default_recommendation_candidate_cache() -> RedisRecommendationCandidateCache:
    return RedisRecommendationCandidateCache.from_settings()


def build_candidate_cache_key(
    intent: RecommendationIntent,
    *,
    avoid_ingredients: list[str],
    target_pool_size: int,
    candidate_generation_version: str,
    key_prefix: str,
) -> str:
    payload = {
        "schema_version": CANDIDATE_CACHE_SCHEMA_VERSION,
        "candidate_generation_version": candidate_generation_version,
        "concern_text": intent.concern_text.strip(),
        "search_terms": list(intent.search_terms),
        "effects": [effect.effect_id for effect in intent.effects],
        "priority_effects": [effect.effect_id for effect in intent.priority_effects],
        "category_codes": sorted(
            category.category_code for category in intent.purchase_conditions.categories
        ),
        "brand_codes": sorted(
            brand.brand_code for brand in intent.purchase_conditions.brands
        ),
        "price_min": intent.purchase_conditions.price_min,
        "price_max": intent.purchase_conditions.price_max,
        "avoid_ingredients": sorted(
            {
                value.strip()
                for value in avoid_ingredients
                if value and value.strip()
            }
        ),
        "candidate_pool_limit": max(1, target_pool_size),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"{key_prefix}{CANDIDATE_CACHE_NAMESPACE}:{digest}"


def _serialize_candidate_bundle(
    bundle: CachedCandidateBundle,
    *,
    candidate_generation_version: str,
) -> str:
    payload = {
        "schema_version": CANDIDATE_CACHE_SCHEMA_VERSION,
        "candidate_generation_version": candidate_generation_version,
        "candidates": [
            {
                "db_product_id": candidate.db_product_id,
                "product_id": candidate.product_id,
                "brand_code": candidate.brand_code,
                "brand": candidate.brand,
                "category_code": candidate.category_code,
                "name": candidate.name,
                "thumbnail_url": candidate.thumbnail_url,
                "lowest_price": candidate.lowest_price,
            }
            for candidate in bundle.candidates
        ],
        "metadata": {
            "raw_hit_count": bundle.raw_hit_count,
            "direct_match_count": bundle.direct_match_count,
            "popularity_fill_count": bundle.popularity_fill_count,
            "pre_dedupe_count": bundle.pre_dedupe_count,
            "deduped_count": bundle.deduped_count,
            "total_hit_count": bundle.total_hit_count,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deserialize_candidate_bundle(
    raw_payload: str | bytes,
    *,
    candidate_generation_version: str,
) -> CachedCandidateBundle:
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8")
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("candidate cache payload must be an object")
    if payload.get("schema_version") != CANDIDATE_CACHE_SCHEMA_VERSION:
        raise ValueError("candidate cache schema version mismatch")
    if payload.get("candidate_generation_version") != candidate_generation_version:
        raise ValueError("candidate generation version mismatch")

    raw_candidates = payload.get("candidates")
    metadata = payload.get("metadata")
    if not isinstance(raw_candidates, list) or not isinstance(metadata, dict):
        raise ValueError("candidate cache payload is incomplete")

    candidates = tuple(_candidate_from_payload(value) for value in raw_candidates)
    if len({candidate.db_product_id for candidate in candidates}) != len(candidates):
        raise ValueError("candidate cache payload contains duplicate product IDs")

    return CachedCandidateBundle(
        candidates=candidates,
        raw_hit_count=_required_non_negative_int(metadata.get("raw_hit_count")),
        direct_match_count=_required_non_negative_int(metadata.get("direct_match_count")),
        popularity_fill_count=_required_non_negative_int(
            metadata.get("popularity_fill_count")
        ),
        pre_dedupe_count=_required_non_negative_int(metadata.get("pre_dedupe_count")),
        deduped_count=_required_non_negative_int(metadata.get("deduped_count")),
        total_hit_count=_optional_non_negative_int(metadata.get("total_hit_count")),
    )


def _candidate_from_payload(value: Any) -> ProductCandidate:
    if not isinstance(value, dict):
        raise ValueError("candidate payload must be an object")
    thumbnail_url = value.get("thumbnail_url")
    if thumbnail_url is not None and not isinstance(thumbnail_url, str):
        raise ValueError("candidate thumbnail_url must be text or null")
    return ProductCandidate(
        db_product_id=_required_positive_int(value.get("db_product_id")),
        product_id=_required_text(value.get("product_id")),
        brand_code=_required_text(value.get("brand_code")),
        brand=_required_text(value.get("brand")),
        category_code=_required_text(value.get("category_code")),
        name=_required_text(value.get("name")),
        thumbnail_url=thumbnail_url,
        lowest_price=_required_non_negative_int(value.get("lowest_price")),
    )


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("candidate cache field must be non-empty text")
    return value


def _required_positive_int(value: Any) -> int:
    parsed = _required_non_negative_int(value)
    if parsed <= 0:
        raise ValueError("candidate cache field must be a positive integer")
    return parsed


def _required_non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("candidate cache field must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate cache field must be an integer") from exc
    if parsed < 0:
        raise ValueError("candidate cache field must be non-negative")
    return parsed


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    return _required_non_negative_int(value)


def _elapsed_ms(started_at: float) -> float:
    return (perf_counter() - started_at) * 1000
