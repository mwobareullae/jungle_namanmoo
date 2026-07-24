import json
import logging
import time
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.core.logging import PERFORMANCE_LOGGER_NAME


SERVICE_NAME = "commerce-backend"
_RESERVED_KEYS = {"timestamp", "service", "event", "request_id", "duration_ms"}
_request_id_context: ContextVar[str | None] = ContextVar("mwobareullae_request_id", default=None)

logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)


def current_time() -> float:
    return time.perf_counter()


def elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def set_current_request_id(request_id: str | None) -> Token[str | None]:
    return _request_id_context.set(request_id)


def reset_current_request_id(token: Token[str | None]) -> None:
    _request_id_context.reset(token)


def get_current_request_id() -> str | None:
    return _request_id_context.get()


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
        "request_id": request_id or get_current_request_id(),
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 2)

    for key, value in (metadata or {}).items():
        if key in _RESERVED_KEYS:
            continue
        payload[key] = _json_safe(value)

    logger.log(level, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def log_error_event(
    event: str,
    *,
    started_at: float,
    metadata: Mapping[str, Any],
    exc: Exception,
) -> None:
    # "예외를 error_type 메타데이터와 함께 ERROR 레벨로 남긴다" 는 admin 라우트들의 실패 핸들러와
    # payment_expiry_service 의 주문별 실패 로깅에 각각 따로 구현돼 있던 것을 하나로 모았다.
    # rollback 여부·raise/continue 여부는 호출부마다 달라 이 함수의 관심사가 아니다.
    log_performance_event(
        event,
        duration_ms=elapsed_ms(started_at),
        metadata={**metadata, "error_type": type(exc).__name__},
        level=logging.ERROR,
    )


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
