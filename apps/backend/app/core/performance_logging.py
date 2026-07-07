import json
import logging
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.logging import PERFORMANCE_LOGGER_NAME


SERVICE_NAME = "commerce-backend"
_RESERVED_KEYS = {"timestamp", "service", "event", "request_id", "duration_ms"}

logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)


def current_time() -> float:
    return time.perf_counter()


def elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def log_performance_event(
    event: str,
    *,
    duration_ms: float | None = None,
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    level: int = logging.INFO,
) -> None:
    if not settings.enable_performance_logging:
        return

    payload: dict[str, Any] = {
        "timestamp": _utc_timestamp(),
        "service": SERVICE_NAME,
        "event": event,
        "request_id": request_id,
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 2)

    for key, value in (metadata or {}).items():
        if key in _RESERVED_KEYS:
            continue
        payload[key] = _json_safe(value)

    logger.log(level, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(inner_value) for key, inner_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
