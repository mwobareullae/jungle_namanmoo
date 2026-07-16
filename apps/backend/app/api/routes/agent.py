import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Request, Response
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
from app.services.agent_safety import reject_sensitive_agent_input
from app.services.cart_service import ANONYMOUS_CART_COOKIE_NAME, ANONYMOUS_CART_TTL_DAYS


router = APIRouter(tags=["agent"])


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def post_agent_chat(
    body: AgentChatRequest,
    request: Request,
    http_response: Response,
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
    agent_response = await run_openai_agent_chat(
        session,
        body,
        user=current_user,
        request_id=getattr(request.state, "request_id", None),
        session_id=None,
        anonymous_user_id=None,
        anonymous_cart_id=anonymous_cart_id,
    )
    session.commit()
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
