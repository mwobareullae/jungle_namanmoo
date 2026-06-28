import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response


REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"

logger = logging.getLogger("mwobareullae.request")


async def request_logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = _elapsed_ms(started_at)
        logger.exception(
            "request_failed method=%s path=%s duration_ms=%.2f request_id=%s",
            request.method,
            request.url.path,
            duration_ms,
            request_id,
        )
        raise

    duration_ms = _elapsed_ms(started_at)
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[PROCESS_TIME_HEADER] = f"{duration_ms:.2f}"
    logger.info(
        "request_finished method=%s path=%s status_code=%s duration_ms=%.2f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000
