from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.agent import AgentRequestExecution
from app.schemas.agent import AgentChatRequest, AgentChatResponse
from app.schemas.common import ApiError, dump_model


IDEMPOTENCY_KEY_MAX_LENGTH = 128
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")


def claim_agent_request_execution(
    session: Session,
    *,
    idempotency_key: str | None,
    request: AgentChatRequest,
    user_id: int | None,
    anonymous_cart_id: str | None,
) -> tuple[AgentRequestExecution | None, AgentChatResponse | None]:
    """Claim an agent request or replay its completed response for the same actor."""
    normalized_key = _normalize_idempotency_key(idempotency_key)
    if normalized_key is None:
        return None, None

    principal_key = _principal_key(user_id=user_id, anonymous_cart_id=anonymous_cart_id)
    fingerprint = _request_fingerprint(request)
    existing = session.execute(
        select(AgentRequestExecution).where(
            AgentRequestExecution.principal_key == principal_key,
            AgentRequestExecution.idempotency_key == normalized_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _handle_existing_execution(session, existing, fingerprint)

    execution = AgentRequestExecution(
        principal_key=principal_key,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
        status="PENDING",
    )
    session.add(execution)
    try:
        session.flush()
    except IntegrityError:
        # Another request created the same actor/key pair first. Reload it after
        # clearing the failed INSERT transaction, then apply the same policy.
        session.rollback()
        existing = session.execute(
            select(AgentRequestExecution).where(
                AgentRequestExecution.principal_key == principal_key,
                AgentRequestExecution.idempotency_key == normalized_key,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return _handle_existing_execution(session, existing, fingerprint)
    return execution, None


def complete_agent_request_execution(
    execution: AgentRequestExecution | None,
    response: AgentChatResponse,
) -> None:
    if execution is None:
        return
    execution.status = "COMPLETED"
    execution.response_json = dump_model(response)


def fail_agent_request_execution(session: Session, execution_id: int | None) -> None:
    if execution_id is None:
        return
    execution = session.get(AgentRequestExecution, execution_id)
    if execution is None:
        return
    execution.status = "FAILED"
    execution.response_json = {}


def _handle_existing_execution(
    session: Session,
    execution: AgentRequestExecution,
    fingerprint: str,
) -> tuple[AgentRequestExecution, AgentChatResponse | None]:
    if execution.request_fingerprint != fingerprint:
        raise ApiError(
            409,
            "AGENT_IDEMPOTENCY_KEY_REUSED",
            "같은 재시도 키에 다른 요청을 보낼 수 없어요. 다시 시도해주세요.",
        )
    if execution.status == "COMPLETED":
        return execution, AgentChatResponse.model_validate(execution.response_json)
    if execution.status == "PENDING":
        raise ApiError(
            409,
            "AGENT_REQUEST_IN_PROGRESS",
            "같은 요청을 처리하고 있어요. 잠시 후 다시 확인해주세요.",
        )

    # A failed request did not return a completed response, so the user may retry
    # with the same key without duplicating a completed write.
    execution.status = "PENDING"
    execution.response_json = {}
    return execution, None


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > IDEMPOTENCY_KEY_MAX_LENGTH or not _IDEMPOTENCY_KEY_PATTERN.fullmatch(normalized):
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "요청 재시도 키 형식이 올바르지 않아요.")
    return normalized


def _principal_key(*, user_id: int | None, anonymous_cart_id: str | None) -> str:
    if user_id is not None:
        return f"user:{user_id}"
    if anonymous_cart_id:
        return f"anonymous_cart:{anonymous_cart_id}"
    raise ApiError(400, "AGENT_REQUEST_ACTOR_REQUIRED", "요청 사용자를 확인하지 못했어요. 다시 시도해주세요.")


def _request_fingerprint(request: AgentChatRequest) -> str:
    # Recent chat history naturally changes when the client displays an error and
    # retries the same user request. Use the stable request intent instead, while
    # retaining page/product/recommendation context that changes tool meaning.
    payload = json.dumps(
        {
            "message": request.message,
            "context": dump_model(request.context),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
