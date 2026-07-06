from fastapi import APIRouter, Depends, Request
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
from app.services.agent_order_tools import confirm_agent_tool_call
from app.services.agent_openai_runner import run_openai_agent_chat


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
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> AgentChatResponse:
    response = await run_openai_agent_chat(
        session,
        body,
        user=current_user,
        request_id=getattr(request.state, "request_id", None),
        session_id=None,
        anonymous_user_id=None,
    )
    session.commit()
    return response


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
