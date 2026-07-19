from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import AsyncIterator, Callable, Literal

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.performance_logging import elapsed_ms
from app.schemas.common import ApiError


logger = logging.getLogger(__name__)

_GLOBAL_SLOT_NAMESPACE = "agent:workflow_slots:v1"
_RATE_LIMIT_NAMESPACE = "agent:rate_limit:v1"
_RELEASE_SLOT_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""
_INCREMENT_RATE_LIMIT_SCRIPT = """
local count = redis.call('incr', KEYS[1])
if count == 1 then
  redis.call('expire', KEYS[1], ARGV[1])
end
local ttl = redis.call('ttl', KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class AgentGlobalSlotLease:
    """A Redis-owned global workflow slot held only while an Agent runs."""

    slot_number: int
    owner_token: str
    wait_ms: float
    acquire_ms: float


@dataclass(frozen=True)
class AgentRateLimitDecision:
    actor_type: Literal["authenticated", "anonymous"]
    limit_per_minute: int
    current_count: int
    retry_after_seconds: int
    check_ms: float


class AgentRuntimeControl:
    """Redis-backed admission control for costly Agent/OpenAI workflows.

    The process-local semaphore in ``agent_openai_runner`` remains a secondary
    guard. This controller is the cross-worker authority: one Redis lease is
    required before a request can enter the Agent workflow.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        key_prefix: str | None = None,
        max_concurrency: int | None = None,
        queue_timeout_seconds: float | None = None,
        busy_retry_after_seconds: int | None = None,
        lease_ttl_seconds: float | None = None,
        authenticated_rate_limit_per_minute: int | None = None,
        anonymous_rate_limit_per_minute: int | None = None,
        client: Redis | None = None,
        poll_interval_seconds: float = 0.05,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._key_prefix = key_prefix if key_prefix is not None else settings.redis_key_prefix
        self._max_concurrency = max(max_concurrency or settings.openai_agent_max_concurrency, 1)
        self._queue_timeout_seconds = max(
            queue_timeout_seconds
            if queue_timeout_seconds is not None
            else settings.openai_agent_queue_timeout_seconds,
            0.01,
        )
        self._busy_retry_after_seconds = max(
            busy_retry_after_seconds
            if busy_retry_after_seconds is not None
            else settings.openai_agent_busy_retry_after_seconds,
            1,
        )
        self._lease_ttl_seconds = max(
            lease_ttl_seconds
            if lease_ttl_seconds is not None
            else settings.openai_agent_global_lease_ttl_seconds,
            0.001,
        )
        self._authenticated_rate_limit_per_minute = max(
            authenticated_rate_limit_per_minute
            if authenticated_rate_limit_per_minute is not None
            else settings.openai_agent_authenticated_rate_limit_per_minute,
            1,
        )
        self._anonymous_rate_limit_per_minute = max(
            anonymous_rate_limit_per_minute
            if anonymous_rate_limit_per_minute is not None
            else settings.openai_agent_anonymous_rate_limit_per_minute,
            1,
        )
        self._client = client
        self._poll_interval_seconds = max(poll_interval_seconds, 0.001)
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock

    def check_rate_limit(
        self,
        *,
        actor_type: Literal["authenticated", "anonymous"],
        actor_id: int | str,
    ) -> AgentRateLimitDecision:
        """Consume one fixed-window Agent request allowance.

        Redis is deliberately fail-closed for Agent admission only. Without a
        reliable counter, this endpoint cannot safely protect the shared LLM
        budget; unrelated commerce APIs never call this service.
        """

        started_at = self._monotonic_clock()
        limit_per_minute = self._limit_for(actor_type)
        key = self._rate_limit_key(actor_type=actor_type, actor_id=actor_id)
        try:
            result = self._get_client().eval(
                _INCREMENT_RATE_LIMIT_SCRIPT,
                1,
                key,
                60,
            )
            current_count, ttl_seconds = _parse_rate_limit_result(result)
        except (RedisError, OSError, ValueError, TypeError) as exc:
            raise _capacity_unavailable_error() from exc

        decision = AgentRateLimitDecision(
            actor_type=actor_type,
            limit_per_minute=limit_per_minute,
            current_count=current_count,
            retry_after_seconds=max(ttl_seconds, 1),
            check_ms=elapsed_ms(started_at),
        )
        if current_count > limit_per_minute:
            raise ApiError(
                429,
                "AGENT_RATE_LIMITED",
                "AI 요청이 잠시 많아요. 잠시 후 다시 시도해 주세요.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        return decision

    @asynccontextmanager
    async def acquire_global_slot(self) -> AsyncIterator[AgentGlobalSlotLease]:
        """Acquire one globally shared Agent/OpenAI workflow lease.

        A slot may wait for the configured queue budget. The caller should only
        start the separate OpenAI execution timeout after this context enters.
        """

        started_at = self._monotonic_clock()
        deadline = started_at + self._queue_timeout_seconds
        owner_token = secrets.token_urlsafe(24)

        while True:
            for slot_number in range(1, self._max_concurrency + 1):
                acquire_started_at = self._monotonic_clock()
                try:
                    acquired = self._get_client().set(
                        self._slot_key(slot_number),
                        owner_token,
                        nx=True,
                        px=max(1, round(self._lease_ttl_seconds * 1000)),
                    )
                except (RedisError, OSError, ValueError, TypeError) as exc:
                    raise _capacity_unavailable_error() from exc

                if acquired:
                    lease = AgentGlobalSlotLease(
                        slot_number=slot_number,
                        owner_token=owner_token,
                        wait_ms=elapsed_ms(started_at),
                        acquire_ms=elapsed_ms(acquire_started_at),
                    )
                    try:
                        yield lease
                    finally:
                        self._release_slot(lease)
                    return

            remaining_seconds = deadline - self._monotonic_clock()
            if remaining_seconds <= 0:
                raise _agent_busy_error(self._busy_retry_after_seconds)
            await asyncio.sleep(min(self._poll_interval_seconds, remaining_seconds))

    def _release_slot(self, lease: AgentGlobalSlotLease) -> None:
        try:
            self._get_client().eval(
                _RELEASE_SLOT_SCRIPT,
                1,
                self._slot_key(lease.slot_number),
                lease.owner_token,
            )
        except (RedisError, OSError, ValueError, TypeError):
            # A failed release cannot safely become a user-facing failure after
            # an Agent/tool has completed. The bounded lease TTL recovers it.
            logger.warning("agent_global_slot_release_failed", extra={"slot": lease.slot_number})

    def _get_client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        return self._client

    def _slot_key(self, slot_number: int) -> str:
        return f"{self._key_prefix}{_GLOBAL_SLOT_NAMESPACE}:{slot_number}"

    def _rate_limit_key(
        self,
        *,
        actor_type: Literal["authenticated", "anonymous"],
        actor_id: int | str,
    ) -> str:
        actor_digest = hashlib.sha256(str(actor_id).encode("utf-8")).hexdigest()[:32]
        window = int(self._wall_clock() // 60)
        return f"{self._key_prefix}{_RATE_LIMIT_NAMESPACE}:{actor_type}:{window}:{actor_digest}"

    def _limit_for(self, actor_type: Literal["authenticated", "anonymous"]) -> int:
        if actor_type == "authenticated":
            return self._authenticated_rate_limit_per_minute
        return self._anonymous_rate_limit_per_minute


@lru_cache(maxsize=1)
def get_default_agent_runtime_control() -> AgentRuntimeControl:
    return AgentRuntimeControl()


def _parse_rate_limit_result(value: object) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("unexpected Redis rate limit result")
    try:
        current_count = int(value[0])
        ttl_seconds = int(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Redis rate limit result") from exc
    if current_count < 1:
        raise ValueError("invalid Redis rate limit count")
    return current_count, ttl_seconds


def _agent_busy_error(retry_after_seconds: int) -> ApiError:
    return ApiError(
        429,
        "AGENT_OPENAI_BUSY",
        "AI 요청이 잠시 많아요. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": str(max(retry_after_seconds, 1))},
    )


def _capacity_unavailable_error() -> ApiError:
    return ApiError(
        503,
        "AGENT_CAPACITY_UNAVAILABLE",
        "AI 요청 제어 서비스를 사용할 수 없어요. 잠시 후 다시 시도해 주세요.",
    )
