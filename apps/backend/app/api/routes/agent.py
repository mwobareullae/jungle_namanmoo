import secrets
from datetime import UTC, datetime, timedelta

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
from app.schemas.common import ErrorResponse
from app.core.config import settings
from app.services.agent_order_tools import confirm_agent_tool_call
from app.services.agent_openai_runner import run_openai_agent_chat
from app.services.agent_idempotency import (
    claim_agent_request_execution,
    complete_agent_request_execution,
    fail_agent_request_execution,
)
from app.services.agent_safety import reject_sensitive_agent_input
from app.services.cart_service import ANONYMOUS_CART_COOKIE_NAME, ANONYMOUS_CART_TTL_DAYS
from app.services.event_tracking import session_id_from_request


router = APIRouter(tags=["agent"])


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
    reject_sensitive_agent_input(
        body.message,
        *(message.content for message in body.recent_messages if message.role == "user"),
    )
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
    execution, replay_response = claim_agent_request_execution(
        session,
        idempotency_key=idempotency_key,
        request=body,
        user_id=current_user.id if current_user is not None else None,
        anonymous_cart_id=anonymous_cart_id,
    )
    if replay_response is not None:
        return replay_response
    if execution is not None:
        # Persist PENDING before the LLM call so a browser retry cannot begin
        # another write-capable tool execution while this request is running.
        session.commit()

    try:
        agent_response = await run_openai_agent_chat(
            session,
            body,
            user=current_user,
            request_id=getattr(request.state, "request_id", None),
            session_id=session_id_from_request(request),
            anonymous_user_id=None,
            anonymous_cart_id=anonymous_cart_id,
        )
        complete_agent_request_execution(execution, agent_response)
        session.commit()
    except Exception:
        session.rollback()
        if execution is not None:
            fail_agent_request_execution(session, execution.id)
            session.commit()
        raise
    return agent_response


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
