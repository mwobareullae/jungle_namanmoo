from __future__ import annotations

import asyncio
import time

import pytest
from redis.exceptions import RedisError

from app.schemas.common import ApiError
from app.services.agent_runtime_control import AgentRuntimeControl


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float | None]] = {}
        self.keys: list[str] = []
        self.raise_error = False

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        self._raise_if_needed()
        self._expire_keys()
        self.keys.append(key)
        if nx and key in self._values:
            return False
        expiry = time.monotonic() + px / 1000 if px is not None else None
        self._values[key] = (value, expiry)
        return True

    def eval(self, script: str, _key_count: int, *args: object) -> object:
        self._raise_if_needed()
        self._expire_keys()
        key = str(args[0])
        self.keys.append(key)
        if "redis.call('incr'" in script:
            ttl_seconds = int(args[1])
            existing = self._values.get(key)
            count = int(existing[0]) + 1 if existing else 1
            expiry = existing[1] if existing else time.monotonic() + ttl_seconds
            self._values[key] = (str(count), expiry)
            ttl = max(1, int(expiry - time.monotonic())) if expiry is not None else -1
            return [count, ttl]
        owner_token = str(args[1])
        existing = self._values.get(key)
        if existing and existing[0] == owner_token:
            del self._values[key]
            return 1
        return 0

    def value(self, key: str) -> str | None:
        self._expire_keys()
        current = self._values.get(key)
        return current[0] if current else None

    def _expire_keys(self) -> None:
        now = time.monotonic()
        for key, (_value, expiry) in list(self._values.items()):
            if expiry is not None and expiry <= now:
                del self._values[key]

    def _raise_if_needed(self) -> None:
        if self.raise_error:
            raise RedisError("Redis unavailable")


def build_control(fake_redis: FakeRedis, **overrides: object) -> AgentRuntimeControl:
    options: dict[str, object] = {
        "max_concurrency": 3,
        "queue_timeout_seconds": 0.02,
        "busy_retry_after_seconds": 2,
        "lease_ttl_seconds": 0.05,
        "authenticated_rate_limit_per_minute": 30,
        "anonymous_rate_limit_per_minute": 20,
        "poll_interval_seconds": 0.002,
    }
    options.update(overrides)
    return AgentRuntimeControl(
        key_prefix="test:",
        client=fake_redis,
        **options,
    )


@pytest.mark.anyio
async def test_global_slots_allow_three_then_reject_the_fourth() -> None:
    control = build_control(FakeRedis())
    release = asyncio.Event()
    entered = asyncio.Event()
    entered_count = 0

    async def hold_slot() -> None:
        nonlocal entered_count
        async with control.acquire_global_slot():
            entered_count += 1
            if entered_count == 3:
                entered.set()
            await release.wait()

    holders = [asyncio.create_task(hold_slot()) for _ in range(3)]
    await asyncio.wait_for(entered.wait(), timeout=1)

    with pytest.raises(ApiError) as captured:
        async with control.acquire_global_slot():
            raise AssertionError("fourth request must not acquire a global slot")

    assert captured.value.status_code == 429
    assert captured.value.code == "AGENT_OPENAI_BUSY"
    assert captured.value.headers == {"Retry-After": "2"}

    release.set()
    await asyncio.gather(*holders)


@pytest.mark.anyio
async def test_global_slot_releases_after_exception_and_cancellation() -> None:
    control = build_control(FakeRedis(), max_concurrency=1)

    with pytest.raises(RuntimeError):
        async with control.acquire_global_slot():
            raise RuntimeError("tool failed")

    async with control.acquire_global_slot():
        pass

    entered = asyncio.Event()

    async def hold_then_cancel() -> None:
        async with control.acquire_global_slot():
            entered.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(hold_then_cancel())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with control.acquire_global_slot():
        pass


@pytest.mark.anyio
async def test_global_slot_ttl_recovers_after_owner_stops_without_release() -> None:
    fake_redis = FakeRedis()
    control = build_control(fake_redis, max_concurrency=1, lease_ttl_seconds=0.01)
    assert fake_redis.set("test:agent:workflow_slots:v1:1", "abandoned", nx=True, px=10)

    await asyncio.sleep(0.02)
    async with control.acquire_global_slot() as lease:
        assert lease.slot_number == 1


@pytest.mark.anyio
async def test_global_slot_release_only_deletes_the_matching_owner_token() -> None:
    fake_redis = FakeRedis()
    control = build_control(fake_redis, max_concurrency=1)

    async with control.acquire_global_slot() as lease:
        assert fake_redis.set(
            "test:agent:workflow_slots:v1:1",
            "new-owner",
            nx=False,
            px=100,
        )
        assert lease.owner_token != "new-owner"

    assert fake_redis.value("test:agent:workflow_slots:v1:1") == "new-owner"


def test_rate_limit_is_actor_scoped_and_hides_actor_identifiers() -> None:
    fake_redis = FakeRedis()
    control = build_control(
        fake_redis,
        authenticated_rate_limit_per_minute=2,
        anonymous_rate_limit_per_minute=1,
    )

    first = control.check_rate_limit(actor_type="authenticated", actor_id=12345)
    second = control.check_rate_limit(actor_type="authenticated", actor_id=12345)
    assert first.current_count == 1
    assert second.current_count == 2

    with pytest.raises(ApiError) as captured:
        control.check_rate_limit(actor_type="authenticated", actor_id=12345)
    assert captured.value.status_code == 429
    assert captured.value.code == "AGENT_RATE_LIMITED"
    assert "Retry-After" in captured.value.headers

    anonymous = control.check_rate_limit(actor_type="anonymous", actor_id="cart-secret-value")
    assert anonymous.current_count == 1
    with pytest.raises(ApiError) as anonymous_captured:
        control.check_rate_limit(actor_type="anonymous", actor_id="cart-secret-value")
    assert anonymous_captured.value.code == "AGENT_RATE_LIMITED"

    assert all("12345" not in key and "cart-secret-value" not in key for key in fake_redis.keys)


@pytest.mark.parametrize("operation", ["rate_limit", "slot"])
@pytest.mark.anyio
async def test_redis_failure_fails_closed_for_agent_admission(operation: str) -> None:
    fake_redis = FakeRedis()
    fake_redis.raise_error = True
    control = build_control(fake_redis)

    if operation == "rate_limit":
        with pytest.raises(ApiError) as captured:
            control.check_rate_limit(actor_type="anonymous", actor_id="cart")
    else:
        with pytest.raises(ApiError) as captured:
            async with control.acquire_global_slot():
                pass

    assert captured.value.status_code == 503
    assert captured.value.code == "AGENT_CAPACITY_UNAVAILABLE"
