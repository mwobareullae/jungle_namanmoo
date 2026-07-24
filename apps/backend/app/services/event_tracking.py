import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.schemas.event import EventLogCreateRequest
from app.services.event_service import create_event_log


ANONYMOUS_USER_ID_HEADER = "X-MWBL-Anonymous-User-Id"
SESSION_ID_HEADER = "X-MWBL-Session-Id"


def record_event_log_best_effort(
    session: Session,
    request: EventLogCreateRequest,
    *,
    current_user: User | None = None,
    fallback_request_id: str | None = None,
    fallback_anonymous_user_id: str | None = None,
    fallback_session_id: str | None = None,
    logger: logging.Logger | None = None,
    failure_message: str = "failed_to_record_event_log",
) -> None:
    try:
        create_event_log(
            session,
            request,
            current_user=current_user,
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        if logger is not None:
            logger.exception(failure_message, extra={"event_name": request.event_name})


def request_id_from_request(request: Request) -> str | None:
    state_request_id = getattr(request.state, "request_id", None)
    if state_request_id:
        return str(state_request_id)
    return request.headers.get("x-request-id")


def anonymous_user_id_from_request(request: Request) -> str | None:
    return _clean_header_value(request.headers.get(ANONYMOUS_USER_ID_HEADER))


def session_id_from_request(request: Request) -> str | None:
    return _clean_header_value(request.headers.get(SESSION_ID_HEADER))


def _clean_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
