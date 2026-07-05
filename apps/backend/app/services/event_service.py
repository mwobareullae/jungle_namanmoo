from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.events import EventLog
from app.schemas.common import ApiError
from app.schemas.event import EventLogCreateRequest, EventLogResponse, OFFICIAL_EVENT_NAMES


MAX_METADATA_BYTES = 16 * 1024

SENSITIVE_METADATA_KEYS = {
    "access_token",
    "address",
    "address1",
    "address2",
    "authorization",
    "card_number",
    "email",
    "g_csrf_token",
    "id_token",
    "llm_prompt",
    "llm_response",
    "name",
    "password",
    "phone",
    "phone_number",
    "prompt",
    "raw_prompt",
    "raw_response",
    "recipient_name",
    "refresh_token",
    "response",
    "token",
    "user_email",
    "user_name",
}


def create_event_log(
    session: Session,
    request: EventLogCreateRequest,
    *,
    current_user: User | None = None,
    fallback_request_id: str | None = None,
) -> EventLogResponse:
    event_id = _normalize_optional_text(request.event_id) or str(uuid4())
    existing = _load_event_by_event_id(session, event_id)
    if existing is not None:
        return _to_response(existing, duplicate=True)

    now = datetime.now(UTC)
    metadata_json = _validate_metadata(request.metadata)
    event_log = EventLog(
        event_id=event_id,
        event_name=request.event_name.strip(),
        occurred_at=request.occurred_at or now,
        user_id=current_user.id if current_user is not None else None,
        anonymous_user_id=_normalize_optional_text(request.anonymous_user_id),
        session_id=_normalize_optional_text(request.session_id),
        request_id=_normalize_optional_text(request.request_id) or _normalize_optional_text(fallback_request_id),
        recommendation_id=_normalize_optional_text(request.recommendation_id),
        product_id=_normalize_optional_text(request.product_id),
        rank=request.rank,
        source=_normalize_optional_text(request.source),
        page=_normalize_optional_text(request.page),
        cart_id=request.cart_id,
        order_id=request.order_id,
        metadata_json=metadata_json,
        created_at=now,
    )
    session.add(event_log)
    session.flush()
    return _to_response(event_log)


def create_event_logs(
    session: Session,
    requests: list[EventLogCreateRequest],
    *,
    current_user: User | None = None,
    fallback_request_id: str | None = None,
) -> list[EventLogResponse]:
    return [
        create_event_log(
            session,
            request,
            current_user=current_user,
            fallback_request_id=fallback_request_id,
        )
        for request in requests
    ]


def _load_event_by_event_id(session: Session, event_id: str) -> EventLog | None:
    return session.execute(select(EventLog).where(EventLog.event_id == event_id)).scalar_one_or_none()


def _validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sensitive_path = _find_sensitive_metadata_path(metadata)
    if sensitive_path is not None:
        raise ApiError(
            400,
            "EVENT_METADATA_CONTAINS_SENSITIVE_DATA",
            f"Event metadata contains sensitive field: {sensitive_path}",
        )
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "EVENT_METADATA_NOT_JSON_SERIALIZABLE", "Event metadata must be JSON serializable.") from exc
    if len(encoded) > MAX_METADATA_BYTES:
        raise ApiError(400, "EVENT_METADATA_TOO_LARGE", "Event metadata is too large.")
    return metadata


def _find_sensitive_metadata_path(value: Any, path: str = "metadata") -> str | None:
    if isinstance(value, dict):
        for key, child_value in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            child_path = f"{path}.{key}"
            if normalized_key in SENSITIVE_METADATA_KEYS:
                return child_path
            nested_path = _find_sensitive_metadata_path(child_value, child_path)
            if nested_path is not None:
                return nested_path
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested_path = _find_sensitive_metadata_path(item, f"{path}[{index}]")
            if nested_path is not None:
                return nested_path
    return None


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _to_response(event_log: EventLog, *, duplicate: bool = False) -> EventLogResponse:
    return EventLogResponse(
        id=event_log.id,
        event_id=event_log.event_id,
        event_name=event_log.event_name,
        occurred_at=event_log.occurred_at,
        created_at=event_log.created_at,
        official_event=event_log.event_name in OFFICIAL_EVENT_NAMES,
        duplicate=duplicate,
    )
