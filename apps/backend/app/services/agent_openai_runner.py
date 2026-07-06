from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.auth import User
from app.schemas.agent import AgentChatRequest, AgentChatResponse, AgentUiAction
from app.schemas.common import ApiError, dump_model
from app.services.agent_order_tools import CANCEL_RECENT_ORDER_TOOL, ORDER_STATUS_LOOKUP_TOOL
from app.services.agent_product_tools import (
    COMPARE_PRODUCTS_TOOL,
    FIND_SIMILAR_PRODUCTS_TOOL,
    REFINE_PRODUCT_RESULTS_TOOL,
)
from app.services.agent_tool_dispatcher import execute_agent_tool


AGENT_INSTRUCTIONS = """
You are the action agent for the Korean cosmetics commerce service "mwobareullae".

Your job is to choose and call the correct tool for user actions. The backend will
return the exact UI action payload, so do not invent product IDs, order codes, prices,
or stock information.

Use tools this way:
- If the user asks for similar or alternative products and current_product_id exists,
  call find_similar_products with that product ID.
- If the user asks to compare products, use selected_product_ids first. If that is
  empty, use visible_product_ids only when at least two products are visible.
- If the user asks to narrow existing results by price, skin type, sensitivity,
  category, or effect, call refine_product_results with visible_product_ids.
- If the user asks about order status or delivery status, call order_status_lookup.
- If the user asks to cancel a recent order or the current order, call
  cancel_recent_order. This tool only prepares a confirmation step; it does not
  execute cancellation by itself.

If required context is missing, ask for the missing information in one short Korean
sentence. If no tool is needed, answer briefly in Korean.

Skin type argument mapping:
- dry -> dry
- oily -> oily
- combination -> combination
- normal -> normal
- dehydrated oily -> dehydrated_oily
- sensitive skin -> sensitivity=sensitive

Prefer one tool call per user turn unless the user explicitly asks for multiple
actions. Keep the final answer short and suitable for a chat bubble.
""".strip()


@dataclass
class CommerceAgentContext:
    session: Session
    user: User | None
    conversation_id: str | None
    request_id: str | None
    session_id: str | None
    anonymous_user_id: str | None
    last_tool_response: AgentChatResponse | None = None


async def run_openai_agent_chat(
    session: Session,
    request: AgentChatRequest,
    *,
    user: User | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    anonymous_user_id: str | None = None,
) -> AgentChatResponse:
    if not settings.openai_api_key:
        raise ApiError(503, "AGENT_OPENAI_NOT_CONFIGURED", "OPENAI_API_KEY is required for agent chat.")
    if not settings.openai_agent_model:
        raise ApiError(503, "AGENT_OPENAI_MODEL_NOT_CONFIGURED", "OPENAI_AGENT_MODEL is required for agent chat.")

    try:
        from agents import Agent, ModelSettings, Runner
    except ImportError as exc:
        raise ApiError(503, "AGENT_SDK_NOT_INSTALLED", "OpenAI Agents SDK is not installed.") from exc

    context = CommerceAgentContext(
        session=session,
        user=user,
        conversation_id=request.conversation_id,
        request_id=request_id,
        session_id=session_id,
        anonymous_user_id=anonymous_user_id,
    )
    agent = Agent[CommerceAgentContext](
        name="mwobareullae_action_agent",
        instructions=AGENT_INSTRUCTIONS,
        model=settings.openai_agent_model,
        model_settings=ModelSettings(tool_choice="auto"),
        tools=[
            find_similar_products,
            compare_products,
            refine_product_results,
            order_status_lookup,
            cancel_recent_order,
        ],
    )

    result = await Runner.run(
        agent,
        input=_build_agent_input(request),
        context=context,
        max_turns=4,
    )

    if context.last_tool_response is not None:
        return _with_agent_message(context.last_tool_response, result.final_output)

    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(request.conversation_id),
        message=_normalize_agent_text(result.final_output) or "I could not find an action to run.",
        ui_action=AgentUiAction(),
        items=[],
    )


def _build_agent_input(request: AgentChatRequest) -> str:
    return json.dumps(
        {
            "message": request.message,
            "context": dump_model(request.context),
        },
        ensure_ascii=False,
    )


def _with_agent_message(response: AgentChatResponse, final_output: Any) -> AgentChatResponse:
    message = _normalize_agent_text(final_output)
    if not message:
        return response
    return response.model_copy(update={"message": message})


def _normalize_agent_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    else:
        text = str(value).strip()
    if not text:
        return ""
    return text[:2000]


def _resolve_conversation_id(conversation_id: str | None) -> str:
    if conversation_id and conversation_id.strip():
        return conversation_id.strip()
    return "conv_agent_openai"


def _execute_tool(
    ctx: Any,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    runtime_context: CommerceAgentContext = ctx.context
    response = execute_agent_tool(
        runtime_context.session,
        tool_name=tool_name,
        arguments=arguments,
        user=runtime_context.user,
        conversation_id=runtime_context.conversation_id,
        request_id=runtime_context.request_id,
        session_id=runtime_context.session_id,
        anonymous_user_id=runtime_context.anonymous_user_id,
    )
    runtime_context.last_tool_response = response
    return json.dumps(dump_model(response), ensure_ascii=False)


try:
    from agents import RunContextWrapper, function_tool
except ImportError:
    RunContextWrapper = Any  # type: ignore[misc,assignment]

    def function_tool(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        def decorator(func: Any) -> Any:
            return func

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return decorator


@function_tool(name_override=FIND_SIMILAR_PRODUCTS_TOOL)
async def find_similar_products(
    ctx: RunContextWrapper[CommerceAgentContext],
    product_id: str,
    limit: int = 10,
    min_price: int | None = None,
    max_price: int | None = None,
) -> str:
    """Find purchasable products similar to one source product."""
    return _execute_tool(
        ctx,
        tool_name=FIND_SIMILAR_PRODUCTS_TOOL,
        arguments={
            "product_id": product_id,
            "limit": limit,
            "min_price": min_price,
            "max_price": max_price,
        },
    )


@function_tool(name_override=COMPARE_PRODUCTS_TOOL)
async def compare_products(
    ctx: RunContextWrapper[CommerceAgentContext],
    product_ids: list[str],
) -> str:
    """Compare two to five products and return a UI comparison payload."""
    return _execute_tool(
        ctx,
        tool_name=COMPARE_PRODUCTS_TOOL,
        arguments={"product_ids": product_ids},
    )


@function_tool(name_override=REFINE_PRODUCT_RESULTS_TOOL)
async def refine_product_results(
    ctx: RunContextWrapper[CommerceAgentContext],
    base_product_ids: list[str],
    limit: int = 10,
    min_price: int | None = None,
    max_price: int | None = None,
    category_code: str | None = None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    effect_keywords: list[str] | None = None,
) -> str:
    """Filter the currently visible product candidates by user constraints."""
    return _execute_tool(
        ctx,
        tool_name=REFINE_PRODUCT_RESULTS_TOOL,
        arguments={
            "base_product_ids": base_product_ids,
            "limit": limit,
            "min_price": min_price,
            "max_price": max_price,
            "category_code": category_code,
            "skin_type": skin_type,
            "sensitivity": sensitivity,
            "effect_keywords": effect_keywords,
        },
    )


@function_tool(name_override=ORDER_STATUS_LOOKUP_TOOL)
async def order_status_lookup(
    ctx: RunContextWrapper[CommerceAgentContext],
    order_code: str | None = None,
) -> str:
    """Look up the current user's recent order or one specific order."""
    return _execute_tool(
        ctx,
        tool_name=ORDER_STATUS_LOOKUP_TOOL,
        arguments={"order_code": order_code},
    )


@function_tool(name_override=CANCEL_RECENT_ORDER_TOOL)
async def cancel_recent_order(
    ctx: RunContextWrapper[CommerceAgentContext],
    order_code: str | None = None,
) -> str:
    """Prepare a confirmation modal for canceling a recent cancelable order."""
    return _execute_tool(
        ctx,
        tool_name=CANCEL_RECENT_ORDER_TOOL,
        arguments={"order_code": order_code},
    )
