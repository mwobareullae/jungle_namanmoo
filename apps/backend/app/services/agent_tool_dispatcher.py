from datetime import UTC, datetime
import secrets
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.schemas.agent import AgentChatResponse, AgentToolName
from app.schemas.common import ApiError, dump_model
from app.services.agent_order_tools import (
    CANCEL_RECENT_ORDER_TOOL,
    ORDER_STATUS_LOOKUP_TOOL,
    lookup_order_status,
    prepare_recent_order_cancel,
)
from app.services.agent_policy import get_tool_policy, validate_tool_access
from app.services.agent_product_tools import (
    COMPARE_PRODUCTS_TOOL,
    FIND_SIMILAR_PRODUCTS_TOOL,
    REFINE_PRODUCT_RESULTS_TOOL,
    compare_products,
    find_similar_products,
    refine_product_results,
)


class OrderStatusLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)


class CancelRecentOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_code: str | None = Field(default=None, max_length=40)


class FindSimilarProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., min_length=1, max_length=128)
    limit: int = Field(default=10, ge=1, le=10)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)


class CompareProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(..., min_length=2, max_length=5)


class RefineProductResultsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_product_ids: list[str] = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=10)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    category_code: str | None = Field(default=None, max_length=80)
    skin_type: str | None = Field(default=None, max_length=40)
    sensitivity: str | None = Field(default=None, max_length=40)
    effect_keywords: list[str] | None = Field(default=None, max_length=20)


ToolArgs = (
    OrderStatusLookupArgs
    | CancelRecentOrderArgs
    | FindSimilarProductsArgs
    | CompareProductsArgs
    | RefineProductResultsArgs
)
TOOL_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    ORDER_STATUS_LOOKUP_TOOL: OrderStatusLookupArgs,
    CANCEL_RECENT_ORDER_TOOL: CancelRecentOrderArgs,
    FIND_SIMILAR_PRODUCTS_TOOL: FindSimilarProductsArgs,
    COMPARE_PRODUCTS_TOOL: CompareProductsArgs,
    REFINE_PRODUCT_RESULTS_TOOL: RefineProductResultsArgs,
}


def execute_agent_tool(
    session: Session,
    *,
    tool_name: str,
    arguments: dict[str, Any] | None,
    user: User | None = None,
    conversation_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    anonymous_user_id: str | None = None,
) -> AgentChatResponse:
    started_at = time.perf_counter()
    policy = get_tool_policy(tool_name)
    validate_tool_access(tool_name, user_id=user.id if user is not None else None)
    parsed_arguments = _parse_tool_arguments(tool_name, arguments or {})

    try:
        response = _execute_parsed_tool(
            session,
            tool_name=tool_name,
            arguments=parsed_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )
    except ApiError as exc:
        _record_failed_tool_call(
            session,
            tool_name=tool_name,
            arguments=parsed_arguments,
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            error=exc,
            latency_ms=_elapsed_ms(started_at),
        )
        raise

    if not policy.requires_confirmation:
        _record_executed_tool_call(
            session,
            response=response,
            arguments=parsed_arguments,
            user=user,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
            latency_ms=_elapsed_ms(started_at),
        )
    return response


def list_agent_tool_names() -> list[AgentToolName]:
    return list(TOOL_ARGUMENT_MODELS.keys())  # type: ignore[return-value]


def _parse_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> ToolArgs:
    model = TOOL_ARGUMENT_MODELS.get(tool_name)
    if model is None:
        raise ApiError(400, "UNKNOWN_AGENT_TOOL", "Unknown agent tool.")
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise ApiError(400, "AGENT_TOOL_ARGUMENT_INVALID", "Agent tool arguments are invalid.") from exc


def _execute_parsed_tool(
    session: Session,
    *,
    tool_name: str,
    arguments: ToolArgs,
    user: User | None,
    conversation_id: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    if tool_name == ORDER_STATUS_LOOKUP_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "Login is required for this agent tool.")
        args = _require_args(arguments, OrderStatusLookupArgs)
        return lookup_order_status(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
        )

    if tool_name == CANCEL_RECENT_ORDER_TOOL:
        if user is None:
            raise ApiError(401, "AGENT_AUTH_REQUIRED", "Login is required for this agent tool.")
        args = _require_args(arguments, CancelRecentOrderArgs)
        return prepare_recent_order_cancel(
            session,
            user,
            conversation_id=conversation_id,
            order_code=args.order_code,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    if tool_name == FIND_SIMILAR_PRODUCTS_TOOL:
        args = _require_args(arguments, FindSimilarProductsArgs)
        return find_similar_products(
            session,
            product_id=args.product_id,
            conversation_id=conversation_id,
            limit=args.limit,
            min_price=args.min_price,
            max_price=args.max_price,
        )

    if tool_name == COMPARE_PRODUCTS_TOOL:
        args = _require_args(arguments, CompareProductsArgs)
        return compare_products(
            session,
            product_ids=args.product_ids,
            conversation_id=conversation_id,
        )

    if tool_name == REFINE_PRODUCT_RESULTS_TOOL:
        args = _require_args(arguments, RefineProductResultsArgs)
        return refine_product_results(
            session,
            base_product_ids=args.base_product_ids,
            conversation_id=conversation_id,
            limit=args.limit,
            min_price=args.min_price,
            max_price=args.max_price,
            category_code=args.category_code,
            skin_type=args.skin_type,
            sensitivity=args.sensitivity,
            effect_keywords=args.effect_keywords,
        )

    raise ApiError(400, "UNKNOWN_AGENT_TOOL", "Unknown agent tool.")


def _require_args(arguments: ToolArgs, model: type[BaseModel]) -> Any:
    if not isinstance(arguments, model):
        raise ApiError(400, "AGENT_TOOL_ARGUMENT_INVALID", "Agent tool arguments are invalid.")
    return arguments


def _record_executed_tool_call(
    session: Session,
    *,
    response: AgentChatResponse,
    arguments: ToolArgs,
    user: User | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    latency_ms: int,
) -> None:
    now = datetime.now(UTC)
    tool_call = AgentToolCall(
        tool_call_id=_generate_tool_call_id(),
        conversation_id=response.conversation_id,
        user_id=user.id if user is not None else None,
        anonymous_user_id=anonymous_user_id,
        session_id=session_id,
        request_id=request_id,
        tool_name=response.tool_name or "",
        status="EXECUTED",
        confirmation_required=False,
        executed_at=now,
        input_json=dump_model(arguments),
        output_json=dump_model(response),
        latency_ms=latency_ms,
        created_at=now,
        updated_at=now,
    )
    session.add(tool_call)
    session.flush()


def _record_failed_tool_call(
    session: Session,
    *,
    tool_name: str,
    arguments: ToolArgs,
    user: User | None,
    conversation_id: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
    error: ApiError,
    latency_ms: int,
) -> None:
    now = datetime.now(UTC)
    tool_call = AgentToolCall(
        tool_call_id=_generate_tool_call_id(),
        conversation_id=conversation_id,
        user_id=user.id if user is not None else None,
        anonymous_user_id=anonymous_user_id,
        session_id=session_id,
        request_id=request_id,
        tool_name=tool_name,
        status="FAILED",
        confirmation_required=False,
        input_json=dump_model(arguments),
        output_json={},
        error_code=error.code,
        error_message=error.message,
        latency_ms=latency_ms,
        created_at=now,
        updated_at=now,
    )
    session.add(tool_call)
    session.flush()


def _generate_tool_call_id() -> str:
    return f"tool_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def _elapsed_ms(started_at: float) -> int:
    return max(int((time.perf_counter() - started_at) * 1000), 0)
