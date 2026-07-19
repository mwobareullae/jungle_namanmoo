from dataclasses import replace

from redis.exceptions import RedisError

from app.services.product_candidates import ProductCandidate
from app.services.purchase_conditions import ParsedPurchaseConditions
from app.services.recommendation_candidate_cache import (
    CachedCandidateBundle,
    RedisRecommendationCandidateCache,
    build_candidate_cache_key,
)
from app.services.recommendation_intent import build_recommendation_intent
from app.services.repository import load_repository
from tests.test_data_loader import EXAMPLES_DIR


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True


class _BrokenRedis:
    def get(self, key: str) -> str | None:
        raise RedisError("redis unavailable")

    def set(self, key: str, value: str, *, ex: int) -> bool:
        raise RedisError("redis unavailable")


def test_candidate_cache_key_is_stable_for_equivalent_set_like_filters() -> None:
    intent = _build_intent()

    first = build_candidate_cache_key(
        intent,
        avoid_ingredients=["fragrance", "alcohol"],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        key_prefix="mubarelle:test:",
    )
    second = build_candidate_cache_key(
        intent,
        avoid_ingredients=["alcohol", "fragrance", "fragrance"],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        key_prefix="mubarelle:test:",
    )
    different_limit = build_candidate_cache_key(
        intent,
        avoid_ingredients=["alcohol", "fragrance"],
        target_pool_size=50,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        key_prefix="mubarelle:test:",
    )

    assert first == second
    assert first != different_limit
    assert first.startswith("mubarelle:test:recommendation:candidate_bundle:v1:")


def test_candidate_cache_round_trip_restores_bundle_with_general_ttl() -> None:
    client = _FakeRedis()
    cache = _cache(client)
    intent = _build_intent()
    bundle = _bundle()

    write = cache.write(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        bundle=bundle,
    )
    lookup = cache.read(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
    )

    assert write.failure_reason is None
    assert write.ttl_seconds == 300
    assert lookup.hit is True
    assert lookup.bundle == bundle
    assert set(client.expirations.values()) == {300}


def test_candidate_cache_uses_shorter_ttl_for_price_conditions() -> None:
    client = _FakeRedis()
    cache = _cache(client)
    intent = replace(
        _build_intent(),
        purchase_conditions=ParsedPurchaseConditions(
            categories=(),
            brands=(),
            price_min=None,
            price_max=20_000,
            price_text="20000",
            price_max_text="under 20000",
        ),
    )

    write = cache.write(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        bundle=_bundle(),
    )

    assert write.ttl_seconds == 60
    assert set(client.expirations.values()) == {60}


def test_candidate_cache_invalid_payload_is_reported_as_a_cache_miss() -> None:
    client = _FakeRedis()
    cache = _cache(client)
    intent = _build_intent()
    key = build_candidate_cache_key(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        key_prefix="mubarelle:test:",
    )
    client.values[key] = "not-json"

    lookup = cache.read(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
    )

    assert lookup.hit is False
    assert lookup.failure_reason == "redis_payload_invalid"


def test_candidate_cache_redis_errors_fail_open() -> None:
    cache = _cache(_BrokenRedis())
    intent = _build_intent()

    lookup = cache.read(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
    )
    write = cache.write(
        intent,
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
        bundle=_bundle(),
    )

    assert lookup.hit is False
    assert lookup.failure_reason == "redis_read_failed"
    assert write.failure_reason == "redis_write_failed"


def test_candidate_cache_is_disabled_by_default_behavior() -> None:
    client = _FakeRedis()
    cache = RedisRecommendationCandidateCache(
        enabled=False,
        redis_url="redis://unused",
        key_prefix="mubarelle:test:",
        ttl_seconds=300,
        price_ttl_seconds=60,
        socket_connect_timeout_seconds=0.05,
        socket_timeout_seconds=0.05,
        client=client,
    )

    lookup = cache.read(
        _build_intent(),
        avoid_ingredients=[],
        target_pool_size=500,
        candidate_generation_version="candidate_pool_catalog_es_v2",
    )

    assert lookup.hit is False
    assert lookup.cache_enabled is False
    assert client.values == {}


def _cache(client) -> RedisRecommendationCandidateCache:
    return RedisRecommendationCandidateCache(
        enabled=True,
        redis_url="redis://unused",
        key_prefix="mubarelle:test:",
        ttl_seconds=300,
        price_ttl_seconds=60,
        socket_connect_timeout_seconds=0.05,
        socket_timeout_seconds=0.05,
        client=client,
    )


def _bundle() -> CachedCandidateBundle:
    return CachedCandidateBundle(
        candidates=(
            ProductCandidate(
                db_product_id=1,
                product_id="prod_001",
                brand_code="test_brand",
                brand="Test Brand",
                category_code="serum",
                name="Test Product 1",
                thumbnail_url=None,
                lowest_price=10_000,
            ),
        ),
        raw_hit_count=1,
        direct_match_count=1,
        popularity_fill_count=0,
        pre_dedupe_count=1,
        deduped_count=1,
        total_hit_count=1,
    )


def _build_intent():
    return build_recommendation_intent(
        "hydration recommendation",
        repository=load_repository(EXAMPLES_DIR),
    )
