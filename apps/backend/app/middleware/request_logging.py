import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Request, Response

from app.core.performance_logging import reset_current_request_id, set_current_request_id


REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"
SERVICE_NAME = "commerce-backend"

logger = logging.getLogger("mwobareullae.request")


async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    request.state.request_id = request_id
    request_id_token = set_current_request_id(request_id)
    started_at = time.perf_counter()

    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = _elapsed_ms(started_at)
            logger.error(
                _json_log_line(
                    _build_log_payload(
                        request=request,
                        request_id=request_id,
                        status_code=500,
                        response_time_ms=duration_ms,
                        error=type(exc).__name__,
                    )
                )
            )
            raise

        duration_ms = _elapsed_ms(started_at)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[PROCESS_TIME_HEADER] = f"{duration_ms:.2f}"
        logger.info(
            _json_log_line(
                _build_log_payload(
                    request=request,
                    request_id=request_id,
                    status_code=response.status_code,
                    response_time_ms=duration_ms,
                    error=None,
                )
            )
        )
        return response
    finally:
        reset_current_request_id(request_id_token)


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def _build_log_payload(
    *,
    request: Request,
    request_id: str,
    status_code: int,
    response_time_ms: float,
    error: str | None,
) -> dict:
    return {
        "timestamp": _utc_timestamp(),
        "service": SERVICE_NAME,
        "request_id": request_id,
        "method": request.method,
        "endpoint": _route_template(request),
        "status_code": status_code,
        "response_time_ms": round(response_time_ms, 2),
        "user_id": _user_id(request),
        "error": error,
    }


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _user_id(request: Request) -> str | None:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return None
    return str(user_id)


def _json_log_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
