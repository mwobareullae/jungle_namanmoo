from collections import Counter

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ApiError, ErrorResponse
from app.schemas.event import EventLogBatchRequest, EventLogBatchResponse, EventLogCreateRequest, EventLogResponse
from app.services.event_service import create_event_log, create_event_logs
from app.services.event_tracking import anonymous_user_id_from_request, session_id_from_request


router = APIRouter(tags=["events"])


@router.post(
    "/events",
    response_model=EventLogResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_event(
    payload: EventLogCreateRequest,
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> EventLogResponse:
    result = create_event_log(
        session,
        payload,
        current_user=current_user,
        fallback_request_id=_extract_request_id(request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(request),
        fallback_session_id=session_id_from_request(request),
    )
    session.commit()
    return result


@router.post(
    "/events/batch",
    response_model=EventLogBatchResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_events_batch(
    payload: EventLogBatchRequest,
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> EventLogBatchResponse:
    started_at = current_time()
    request_id = _extract_request_id(request)
    event_name_counts = _event_name_counts(payload)
    try:
        events = create_event_logs(
            session,
            payload.events,
            current_user=current_user,
            fallback_request_id=request_id,
            fallback_anonymous_user_id=anonymous_user_id_from_request(request),
            fallback_session_id=session_id_from_request(request),
        )
    except ApiError as exc:
        log_performance_event(
            "event_batch_failed",
            request_id=request_id,
            duration_ms=elapsed_ms(started_at),
            metadata={
                "batch_size": len(payload.events),
                "accepted_count": 0,
                "duplicate_count": 0,
                "rejected_count": len(payload.events),
                "event_name_counts": event_name_counts,
                "error_code": exc.code,
                "user_authenticated": current_user is not None,
            },
        )
        raise
    session.commit()
    duplicate_count = sum(1 for event in events if event.duplicate)
    log_performance_event(
        "event_batch_collected",
        request_id=request_id,
        duration_ms=elapsed_ms(started_at),
        metadata={
            "batch_size": len(payload.events),
            "accepted_count": len(events),
            "duplicate_count": duplicate_count,
            "rejected_count": max(len(payload.events) - len(events), 0),
            "event_name_counts": event_name_counts,
            "user_authenticated": current_user is not None,
        },
    )
    return EventLogBatchResponse(
        accepted_count=len(events),
        duplicate_count=duplicate_count,
        events=events,
    )


def _extract_request_id(request: Request) -> str | None:
    return (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or getattr(request.state, "request_id", None)
    )


def _event_name_counts(payload: EventLogBatchRequest) -> dict[str, int]:
    return dict(sorted(Counter(event.event_name for event in payload.events).items()))
