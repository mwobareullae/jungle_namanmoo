from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized in {"auto", "postgres", "elasticsearch"}:
        return normalized
    return "auto"


@dataclass(frozen=True)
class ElasticsearchClientStatus:
    mode: str
    enabled: bool
    available: bool
    failure_reason: str | None = None
    disabled_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "enabled": self.enabled,
            "available": self.available,
        }
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        if self.disabled_until is not None:
            payload["disabled_until"] = self.disabled_until.isoformat()
        return payload


class ElasticsearchClientProvider:
    def __init__(
        self,
        *,
        mode: str = settings.search_backend_mode,
        url: str = settings.elasticsearch_url,
        timeout_seconds: float = settings.elasticsearch_timeout_seconds,
        max_retries: int = settings.elasticsearch_max_retries,
        circuit_breaker_seconds: int = settings.elasticsearch_circuit_breaker_seconds,
    ) -> None:
        self.mode = _normalize_mode(mode)
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.circuit_breaker_seconds = circuit_breaker_seconds
        self._client: Any | None = None
        self._disabled_until: datetime | None = None
        self._last_failure_reason: str | None = None

    @property
    def enabled(self) -> bool:
        return self.mode != "postgres"

    def should_attempt(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        checked_at = now or _now()
        return self._disabled_until is None or checked_at >= self._disabled_until

    def get_client(self, now: datetime | None = None) -> Any | None:
        if not self.should_attempt(now):
            return None
        if self._client is not None:
            return self._client
        try:
            from elasticsearch import Elasticsearch

            self._client = Elasticsearch(
                self.url,
                request_timeout=self.timeout_seconds,
                retry_on_timeout=False,
                max_retries=self.max_retries,
            )
        except Exception as exc:
            self.mark_failure(f"elasticsearch client initialization failed: {exc}", now=now)
            return None
        return self._client

    def mark_success(self) -> None:
        self._last_failure_reason = None
        self._disabled_until = None

    def mark_failure(self, reason: str, now: datetime | None = None) -> None:
        checked_at = now or _now()
        self._last_failure_reason = reason
        self._disabled_until = checked_at + timedelta(seconds=self.circuit_breaker_seconds)

    def status(self, now: datetime | None = None) -> ElasticsearchClientStatus:
        available = self.enabled and self.should_attempt(now)
        return ElasticsearchClientStatus(
            mode=self.mode,
            enabled=self.enabled,
            available=available,
            failure_reason=self._last_failure_reason,
            disabled_until=self._disabled_until,
        )


default_elasticsearch_client_provider = ElasticsearchClientProvider()
