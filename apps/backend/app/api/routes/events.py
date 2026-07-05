from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogBatchRequest, EventLogBatchResponse, EventLogCreateRequest, EventLogResponse
from app.services.event_service import create_event_log, create_event_logs


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
    events = create_event_logs(
        session,
        payload.events,
        current_user=current_user,
        fallback_request_id=_extract_request_id(request),
    )
    session.commit()
    duplicate_count = sum(1 for event in events if event.duplicate)
    return EventLogBatchResponse(
        accepted_count=len(events),
        duplicate_count=duplicate_count,
        events=events,
    )


def _extract_request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
