import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_optional_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentToolConfirmRequest,
    AgentToolConfirmResponse,
)
from app.schemas.common import ApiError, ErrorResponse
from app.core.config import settings
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.services.agent_order_tools import confirm_agent_tool_call
from app.services.agent_openai_runner import AgentWorkflowTiming, run_openai_agent_chat
from app.services.agent_idempotency import (
    claim_agent_request_execution,
    complete_agent_request_execution,
    fail_agent_request_execution,
)
from app.services.agent_safety import reject_sensitive_agent_input
from app.services.agent_runtime_control import get_default_agent_runtime_control
from app.services.cart_service import ANONYMOUS_CART_COOKIE_NAME, ANONYMOUS_CART_TTL_DAYS
from app.services.event_tracking import session_id_from_request


router = APIRouter(tags=["agent"])


@dataclass
class _AgentRequestTelemetry:
    started_at: float = field(default_factory=current_time)
    idempotency_ms: float = 0.0
    rate_limit_ms: float = 0.0
    global_slot_wait_ms: float = 0.0
    global_slot_acquire_ms: float = 0.0
    llm_workflow_ms: float = 0.0
    tool_execution_ms: float = 0.0
    response_persist_ms: float = 0.0
    outcome: str = "failed"
    rate_limited: bool = False
    global_slot_acquired: bool = False
    global_slot_rejected: bool = False

    def metadata(self) -> dict[str, float | str | bool]:
        return {
            "agent_total_ms": round(elapsed_ms(self.started_at), 2),
            "agent_idempotency_ms": round(self.idempotency_ms, 2),
            "agent_rate_limit_ms": round(self.rate_limit_ms, 2),
            "agent_global_slot_wait_ms": round(self.global_slot_wait_ms, 2),
            "agent_global_slot_acquire_ms": round(self.global_slot_acquire_ms, 2),
            "agent_llm_workflow_ms": round(self.llm_workflow_ms, 2),
            "agent_tool_execution_ms": round(self.tool_execution_ms, 2),
            "agent_response_persist_ms": round(self.response_persist_ms, 2),
            "agent_outcome": self.outcome,
            "agent_rate_limited": self.rate_limited,
            "agent_global_slot_acquired": self.global_slot_acquired,
            "agent_global_slot_rejected": self.global_slot_rejected,
        }


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def post_agent_chat(
    body: AgentChatRequest,
    request: Request,
    http_response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> AgentChatResponse:
    telemetry = _AgentRequestTelemetry()
    request_id = getattr(request.state, "request_id", None)
    execution = None
    workflow_timing = AgentWorkflowTiming()
    idempotency_started_at: float | None = None
    rate_limit_started_at: float | None = None
    if current_user is None and not anonymous_cart_id:
        anonymous_cart_id = secrets.token_urlsafe(32)
        http_response.set_cookie(
            key=ANONYMOUS_CART_COOKIE_NAME,
            value=anonymous_cart_id,
            max_age=ANONYMOUS_CART_TTL_DAYS * 24 * 60 * 60,
            expires=datetime.now(UTC) + timedelta(days=ANONYMOUS_CART_TTL_DAYS),
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            path="/",
    )
    try:
        reject_sensitive_agent_input(
            body.message,
            *(message.content for message in body.recent_messages if message.role == "user"),
        )
        idempotency_started_at = current_time()
        execution, replay_response = claim_agent_request_execution(
            session,
            idempotency_key=idempotency_key,
            request=body,
            user_id=current_user.id if current_user is not None else None,
            anonymous_cart_id=anonymous_cart_id,
        )
        if execution is not None:
            # Persist PENDING before the LLM call so a browser retry cannot begin
            # another write-capable tool execution while this request is running.
            session.commit()
        telemetry.idempotency_ms = elapsed_ms(idempotency_started_at)
        if replay_response is not None:
            telemetry.outcome = "idempotency_replay"
            return replay_response

        runtime_control = get_default_agent_runtime_control()
        rate_limit_started_at = current_time()
        actor_type: Literal["authenticated", "anonymous"] = (
            "authenticated" if current_user is not None else "anonymous"
        )
        actor_id = current_user.id if current_user is not None else anonymous_cart_id
        runtime_control.check_rate_limit(
            actor_type=actor_type,
            actor_id=actor_id or "anonymous-cart-unavailable",
        )
        telemetry.rate_limit_ms = elapsed_ms(rate_limit_started_at)

        agent_response = await run_openai_agent_chat(
            session,
            body,
            user=current_user,
            request_id=request_id,
            session_id=session_id_from_request(request),
            anonymous_user_id=None,
            anonymous_cart_id=anonymous_cart_id,
            runtime_control=runtime_control,
            workflow_timing=workflow_timing,
            trace_metadata=_build_trace_metadata(
                request_id=request_id,
                conversation_id=body.conversation_id,
                route=request.url.path,
                authenticated=current_user is not None,
            ),
        )
        persist_started_at = current_time()
        complete_agent_request_execution(execution, agent_response)
        session.commit()
        telemetry.response_persist_ms = elapsed_ms(persist_started_at)
        telemetry.outcome = "succeeded"
    except Exception as exc:
        if isinstance(exc, ApiError):
            if exc.code == "AGENT_RATE_LIMITED":
                telemetry.rate_limited = True
                telemetry.outcome = "rate_limited"
            elif exc.code == "AGENT_OPENAI_BUSY":
                telemetry.global_slot_rejected = True
                telemetry.outcome = "global_slot_rejected"
            elif exc.code == "AGENT_CAPACITY_UNAVAILABLE":
                telemetry.outcome = "capacity_unavailable"
            elif exc.code == "AGENT_SENSITIVE_INPUT":
                telemetry.outcome = "rejected_input"
        session.rollback()
        if execution is not None:
            fail_agent_request_execution(session, execution.id)
            session.commit()
        raise
    finally:
        if idempotency_started_at is not None and telemetry.idempotency_ms == 0:
            telemetry.idempotency_ms = elapsed_ms(idempotency_started_at)
        if rate_limit_started_at is not None and telemetry.rate_limit_ms == 0:
            telemetry.rate_limit_ms = elapsed_ms(rate_limit_started_at)
        telemetry.global_slot_wait_ms = workflow_timing.global_slot_wait_ms
        telemetry.global_slot_acquire_ms = workflow_timing.global_slot_acquire_ms
        telemetry.llm_workflow_ms = workflow_timing.llm_workflow_ms
        telemetry.tool_execution_ms = workflow_timing.tool_execution_ms
        telemetry.global_slot_acquired = workflow_timing.global_slot_acquired
        telemetry.global_slot_rejected = (
            telemetry.global_slot_rejected or workflow_timing.global_slot_rejected
        )
        log_performance_event(
            "agent_request_completed",
            request_id=request_id,
            duration_ms=elapsed_ms(telemetry.started_at),
            metadata=telemetry.metadata(),
        )
    return agent_response


def _build_trace_metadata(
    *,
    request_id: str | None,
    conversation_id: str | None,
    route: str,
    authenticated: bool,
) -> dict[str, str | bool]:
    """Return only correlation metadata that is safe for OpenAI trace export."""

    return {
        "request_id": request_id or "request-unknown",
        "conversation_id": conversation_id or "conversation-new",
        "environment": settings.app_env,
        "route": route,
        "authenticated": authenticated,
        "agent_release": settings.agent_release,
    }


@router.post(
    "/agent/tool-calls/{tool_call_id}/confirm",
    response_model=AgentToolConfirmResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_agent_tool_call_confirm(
    tool_call_id: str,
    request: AgentToolConfirmRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> AgentToolConfirmResponse:
    response = confirm_agent_tool_call(
        session,
        current_user,
        tool_call_id=tool_call_id,
        action=request.action,
    )
    session.commit()
    return response
