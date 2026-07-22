"""Small, code-owned routing contracts for the OpenAI action Agent.

The legacy single-Agent path keeps its original large prompt.  The
``router_specialist`` path deliberately starts from these new, narrow prompts
instead of trimming or copying the legacy instructions.  Route validation and
tool authorization remain server-owned.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.db.models.auth import User
from app.schemas.agent import AgentChatRequest, AgentToolName
from app.services.agent_address_tools import REGISTER_SHIPPING_ADDRESS_TOOL
from app.services.agent_bulk_wishlist import BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL
from app.services.agent_cart_composer import COMPOSE_CART_TOOL
from app.services.agent_claim_tools import PREPARE_CLAIM_DRAFT_TOOL
from app.services.agent_commerce_tools import (
    ADD_TO_CART_TOOL,
    GET_CART_TOOL,
    PREPARE_CHECKOUT_TOOL,
    PREPARE_ORDER_TOOL,
    PREPARE_PRODUCT_CHECKOUT_TOOL,
)
from app.services.agent_order_tools import (
    CANCEL_RECENT_ORDER_TOOL,
    FILTER_ORDER_HISTORY_TOOL,
    ORDER_STATUS_LOOKUP_TOOL,
)
from app.services.agent_product_tools import (
    COMPARE_PRODUCTS_TOOL,
    FIND_SIMILAR_PRODUCTS_TOOL,
    REFINE_PRODUCT_RESULTS_TOOL,
)
from app.services.agent_recommendation_tools import CREATE_RECOMMENDATION_TOOL
from app.services.agent_review_tools import PREPARE_REVIEW_DRAFT_TOOL


AgentExecutionMode = Literal["single", "router_specialist"]
AgentRouteName = Literal[
    "recommendation",
    "recommendation_refinement",
    "product_reference",
    "cart_checkout",
    "order_after_sales",
    "bulk_wishlist",
    "clarification",
]


class RouteDecision(BaseModel):
    """Structured output produced by the tool-free Router Agent."""

    model_config = ConfigDict(extra="forbid")

    route: AgentRouteName
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class SpecialistProfile:
    name: AgentRouteName
    instructions: str
    tool_names: tuple[AgentToolName, ...]


ROUTER_INSTRUCTIONS = """
You classify one Korean commerce request for the 뭐바를래 service.
Return only the structured route and confidence. You have no tools.

Routes:
- recommendation: new skin concern or product discovery.
- recommendation_refinement: filter an existing recommendation/search result.
- product_reference: similar, compare, or act on a visible/current/recent product.
- cart_checkout: cart, checkout, order preparation, delivery-address input, or routine composition.
- order_after_sales: order history, delivery status, cancellation, review, return, exchange, or refund.
- bulk_wishlist: preview a popular-rank based wishlist batch.
- clarification: only when the requested action itself is genuinely ambiguous.

Do not create product IDs, ingredient IDs, order IDs, shipping fields, tool arguments,
or any user-facing answer. Missing skin type or sensitivity is not an ambiguity for
recommendations. Prefer the most specific supported route when the user gives a
natural-language request.
""".strip()


_RECOMMENDATION_INSTRUCTIONS = """
Handle only a new Korean cosmetics recommendation request.
Call create_recommendation exactly once for a concrete skin concern or product search.
Use the user's original wording as concern_text. Extract only representable structured
constraints: skin type, sensitivity, avoid ingredients, required ingredients, category,
and price range. Omit unknown fields rather than inventing values or IDs.

Do not ask for skin type or sensitivity when absent: leave them null so the backend can
resolve a saved profile or its default. Do not claim medical outcomes. If the request is
truly empty or contradictory, reply with one short Korean clarification question.
""".strip()

_REFINEMENT_INSTRUCTIONS = """
Handle only a filter/refinement request for an existing product or recommendation result.
Call refine_product_results exactly once when a result reference is available. Extract
category, price, ingredient, skin type, and sensitivity filters from the request. Use
only context identifiers supplied by the server; never invent IDs. Ask one brief Korean
clarification only when there is no saved or visible result to filter.
""".strip()

_PRODUCT_REFERENCE_INSTRUCTIONS = """
Handle only a request about the current, visible, or immediately previous product result.
Use find_similar_products for similar/alternative products, compare_products for an
explicit comparison, add_to_cart for a cart action, and prepare_product_checkout for an
order intent. Use server-provided references or reference_source/reference_rank fields;
never invent a product ID, rank, price, or stock fact. A purchase tool only prepares the
next confirmation/checkout step and must not claim that payment was completed.
""".strip()

_CART_CHECKOUT_INSTRUCTIONS = """
Handle only cart, checkout, natural delivery-address input, or multi-category routine
composition. Use the available tool that matches the request. For a natural address,
extract recipient, phone, postal code, address1, optional address2, and optional memo
from any order or label style. Call register_shipping_address when required fields are
present; otherwise ask only for the missing required field. Never repeat a full address
or phone in the chat response, never invent cart IDs, and never state that payment or an
order has completed before the server returns it.
""".strip()

_ORDER_AFTER_SALES_INSTRUCTIONS = """
Handle only authenticated order-history, delivery, cancellation, review, return,
exchange, or refund requests. Choose exactly one relevant tool. Use an order reference
only when it is supplied by the server or user; never invent one. Cancellation and order
creation remain confirmation-gated by the backend. For reviews and claims, preserve the
user's factual experience and ask for only the missing factual field.
""".strip()

_BULK_WISHLIST_INSTRUCTIONS = """
Handle only a popular-rank based bulk wishlist request. Call
bulk_wishlist_by_popular_ingredient exactly once when the request has a usable rank
range and conditions. Extract rank_limit from 1 through 50, one or more named
ingredients, explicit all/any semantics when stated, category, and min/max price when
stated. Do not silently shrink the requested rank. The server resolves real popularity,
ingredient relations, products, and confirmation; never invent IDs or perform the
wishlist write yourself. Ask a clarification only when the requested condition is
actually unsupported or missing.

Preserve every explicit supported condition in the tool arguments. When a product type
is named, always set category to that exact Korean product type: 세럼, 토너, 크림, or
로션. Keep category even when the request also has ingredient, rank, or price
conditions. Put every named ingredient in ingredient_names. Use all by default; use
any only when the user says 또는, 하나라도, or an equivalent alternative. Do not put a
Korean postposition on an ingredient name when ingredient_names is available.
""".strip()


SPECIALIST_PROFILES: dict[AgentRouteName, SpecialistProfile] = {
    "recommendation": SpecialistProfile(
        name="recommendation",
        instructions=_RECOMMENDATION_INSTRUCTIONS,
        tool_names=(CREATE_RECOMMENDATION_TOOL,),
    ),
    "recommendation_refinement": SpecialistProfile(
        name="recommendation_refinement",
        instructions=_REFINEMENT_INSTRUCTIONS,
        tool_names=(REFINE_PRODUCT_RESULTS_TOOL,),
    ),
    "product_reference": SpecialistProfile(
        name="product_reference",
        instructions=_PRODUCT_REFERENCE_INSTRUCTIONS,
        tool_names=(
            FIND_SIMILAR_PRODUCTS_TOOL,
            COMPARE_PRODUCTS_TOOL,
            ADD_TO_CART_TOOL,
            PREPARE_PRODUCT_CHECKOUT_TOOL,
        ),
    ),
    "cart_checkout": SpecialistProfile(
        name="cart_checkout",
        instructions=_CART_CHECKOUT_INSTRUCTIONS,
        tool_names=(
            GET_CART_TOOL,
            ADD_TO_CART_TOOL,
            PREPARE_PRODUCT_CHECKOUT_TOOL,
            COMPOSE_CART_TOOL,
            PREPARE_CHECKOUT_TOOL,
            REGISTER_SHIPPING_ADDRESS_TOOL,
            PREPARE_ORDER_TOOL,
        ),
    ),
    "order_after_sales": SpecialistProfile(
        name="order_after_sales",
        instructions=_ORDER_AFTER_SALES_INSTRUCTIONS,
        tool_names=(
            FILTER_ORDER_HISTORY_TOOL,
            ORDER_STATUS_LOOKUP_TOOL,
            CANCEL_RECENT_ORDER_TOOL,
            PREPARE_REVIEW_DRAFT_TOOL,
            PREPARE_CLAIM_DRAFT_TOOL,
        ),
    ),
    "bulk_wishlist": SpecialistProfile(
        name="bulk_wishlist",
        instructions=_BULK_WISHLIST_INSTRUCTIONS,
        tool_names=(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,),
    ),
    "clarification": SpecialistProfile(
        name="clarification",
        instructions="",
        tool_names=(),
    ),
}


def build_router_input(request: AgentChatRequest, *, user: User | None) -> str:
    """Build the Router payload without identifiers, tool schemas, or sensitive fields."""

    context = request.context
    payload = {
        "message": request.message,
        "page": context.page,
        "route": _safe_route_path(context.route),
        "authenticated": user is not None,
        "has_current_product": context.current_product_id is not None,
        "has_visible_products": bool(context.visible_product_ids),
        "has_selected_products": bool(context.selected_product_ids),
        "has_recommendation_reference": context.recommendation_id is not None,
        "has_recent_result": request.last_tool_result is not None,
        "has_cart_selection": bool(context.cart_item_ids),
        "has_shipping_address_reference": context.address_id is not None,
    }
    # ``authenticated=false`` is decision-critical Router input.  Do not use a
    # generic compacting helper here because it would erase every false boolean
    # and make guests indistinguishable from an omitted state.
    return json.dumps(
        {key: value for key, value in payload.items() if value not in (None, "")},
        ensure_ascii=False,
    )


def build_specialist_input(request: AgentChatRequest, decision: RouteDecision) -> str:
    """Give the selected specialist only the bounded context needed to use its tools."""

    context = request.context
    payload = {
        "message": request.message,
        "route": decision.route,
        "page": context.page,
        "context": {
            "current_product_id": context.current_product_id,
            "visible_product_ids": context.visible_product_ids,
            "selected_product_ids": context.selected_product_ids,
            "recommendation_id": context.recommendation_id,
            "filters": context.filters,
            "order_code": context.order_code,
            "cart_item_ids": context.cart_item_ids,
            "address_id": context.address_id,
        },
        "recent_messages": [message.model_dump(mode="json") for message in request.recent_messages],
        "last_tool_result": request.last_tool_result.model_dump(mode="json") if request.last_tool_result else None,
    }
    return json.dumps(_omit_empty(payload), ensure_ascii=False)


def select_specialist_tool_names(
    decision: RouteDecision,
    *,
    request: AgentChatRequest,
    allowed_tool_names: tuple[AgentToolName, ...],
) -> tuple[AgentToolName, ...]:
    """Select the smallest safe tool subset for the selected route.

    A route can still contain several operations (for example, ``cart_checkout``),
    but the Specialist should not have to choose among the entire route registry.
    These cues only narrow tool exposure; dispatcher validation remains the final
    source of truth for all references, authorization, and confirmation.
    """

    profile = SPECIALIST_PROFILES[decision.route]
    allowed = set(allowed_tool_names)
    candidates = _select_route_operation_tools(decision.route, request.message)
    return tuple(
        name
        for name in candidates
        if name in profile.tool_names and name in allowed
    )


def validate_route_decision(
    decision: RouteDecision,
    *,
    request: AgentChatRequest,
    user: User | None,
    allowed_tool_names: tuple[AgentToolName, ...],
) -> str | None:
    """Return a safe clarification reason when a route cannot execute here."""

    if decision.route == "clarification":
        return None

    if decision.route == "recommendation_refinement" and not (
        request.context.recommendation_id or request.context.visible_product_ids
    ):
        return "추천 결과를 먼저 확인한 뒤 원하는 조건을 말씀해 주세요."

    if decision.route == "product_reference" and not (
        request.context.current_product_id
        or request.context.visible_product_ids
        or request.context.selected_product_ids
        or request.last_tool_result
    ):
        return "기준이 될 상품이나 상품 목록을 먼저 확인해 주세요."

    if decision.route in {"order_after_sales", "bulk_wishlist"} and user is None:
        return "로그인이 필요한 기능이에요. 로그인 후 다시 요청해 주세요."

    selected = select_specialist_tool_names(
        decision,
        request=request,
        allowed_tool_names=allowed_tool_names,
    )
    if not selected:
        return "현재 화면에서는 이 요청을 처리할 수 없어요. 필요한 상품이나 화면을 먼저 확인해 주세요."
    return None


def _omit_empty(value: object) -> object:
    if isinstance(value, dict):
        compacted = {key: _omit_empty(item) for key, item in value.items()}
        return {key: item for key, item in compacted.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_omit_empty(item) for item in value]
    return value


def _select_route_operation_tools(
    route: AgentRouteName,
    message: str,
) -> tuple[AgentToolName, ...]:
    """Return one operation-focused tool subset before page/auth filtering."""

    normalized = re.sub(r"\s+", " ", message).strip().lower()
    if route == "recommendation":
        return (CREATE_RECOMMENDATION_TOOL,)
    if route == "recommendation_refinement":
        return (REFINE_PRODUCT_RESULTS_TOOL,)
    if route == "bulk_wishlist":
        return (BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,)
    if route == "product_reference":
        if _contains_any(normalized, ("비교", "차이", "vs")):
            return (COMPARE_PRODUCTS_TOOL,)
        if _contains_any(normalized, ("비슷", "유사", "대체")):
            return (FIND_SIMILAR_PRODUCTS_TOOL,)
        if _contains_any(normalized, ("장바구니", "담아", "카트")):
            return (ADD_TO_CART_TOOL,)
        if _contains_any(normalized, ("주문", "구매", "결제")):
            return (PREPARE_PRODUCT_CHECKOUT_TOOL,)
        return ()
    if route == "cart_checkout":
        if _contains_any(normalized, ("배송", "주소", "우편번호", "받는 분", "수령")):
            return (REGISTER_SHIPPING_ADDRESS_TOOL,)
        if _contains_any(normalized, ("루틴", "구성", "토너", "세럼", "크림")):
            return (COMPOSE_CART_TOOL,)
        if _contains_any(normalized, ("장바구니", "카트")):
            return (GET_CART_TOOL,)
        if _contains_any(normalized, ("주문", "구매", "결제", "주문서")):
            return (PREPARE_CHECKOUT_TOOL, PREPARE_ORDER_TOOL)
        return ()
    if route == "order_after_sales":
        if _contains_any(normalized, ("취소",)):
            return (CANCEL_RECENT_ORDER_TOOL,)
        if _contains_any(normalized, ("배송", "도착", "상태")):
            return (ORDER_STATUS_LOOKUP_TOOL,)
        if _contains_any(normalized, ("주문 내역", "구매 내역", "주문 목록")):
            return (FILTER_ORDER_HISTORY_TOOL,)
        if _contains_any(normalized, ("리뷰", "후기")):
            return (PREPARE_REVIEW_DRAFT_TOOL,)
        if _contains_any(normalized, ("반품", "교환", "환불", "클레임")):
            return (PREPARE_CLAIM_DRAFT_TOOL,)
        return ()
    return ()


def _contains_any(message: str, tokens: tuple[str, ...]) -> bool:
    return any(token in message for token in tokens)


def _safe_route_path(value: str | None) -> str | None:
    """Keep routing information while excluding query-string identifiers."""

    if value is None:
        return None
    return value.split("?", 1)[0].split("#", 1)[0] or None
