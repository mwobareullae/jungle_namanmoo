from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.agent import AgentToolConfirmRequest, AgentToolConfirmResponse
from app.schemas.common import ErrorResponse
from app.services.agent_order_tools import confirm_agent_tool_call


router = APIRouter(tags=["agent"])


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
