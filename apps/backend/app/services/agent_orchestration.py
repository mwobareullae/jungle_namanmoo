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
AgentRouterAction = AgentToolName | Literal["clarify"]
AgentTargetScope = Literal[
    "none",
    "current_product",
    "selected_products",
    "cart_selection",
    "last_tool_result",
    "recommendation_result",
    "visible_products",
    "ambiguous",
]


class RouteDecision(BaseModel):
    """Structured output produced by the tool-free Router Agent."""

    model_config = ConfigDict(extra="forbid")

    route: AgentRouteName
    action: AgentRouterAction
    target_scope: AgentTargetScope
    reference_position: Literal["last"] | None = None
    reference_rank: int | None = None
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class SpecialistProfile:
    name: AgentRouteName
    instructions: str
    tool_names: tuple[AgentToolName, ...]


ROUTER_INSTRUCTIONS = """
You classify one Korean commerce request for the 뭐바를래 service.
Return only the structured route, action, target_scope, optional reference selector,
and confidence. You have no tools and must not produce a user-facing answer.

Routes:
- recommendation: new skin concern or product discovery.
- recommendation_refinement: filter an existing recommendation/search result.
- product_reference: similar, compare, or act on a visible/current/recent product.
- cart_checkout: cart, checkout, order preparation, delivery-address input, or routine composition.
- order_after_sales: order history, delivery status, cancellation, review, return, exchange, or refund.
- bulk_wishlist: preview a popular-rank based wishlist batch.
- clarification: only when the requested action itself is genuinely ambiguous.

Action must be exactly one tool name that belongs to the selected route, or "clarify".
Target scope is one of: none, current_product, cart_selection, last_tool_result,
recommendation_result, visible_products, ambiguous.
Use current_product for phrases such as "this product" on a product page. On a
product-detail page with a current product, a generic singular product action such as
"order it", "buy it", "add it to cart", or "show similar products" always means the
current product. Do not infer last_tool_result merely because a prior result exists.
Use last_tool_result only for an explicit ordinal reference to the immediately previous
result. Use cart_selection for checkout/order actions that act on selected cart items.
Use ambiguous when no safe target can be determined. Set reference_position to "last"
only when the user explicitly refers to the final item; otherwise use reference_rank
only for an explicit positive ordinal. Never create IDs, ingredient IDs, order IDs,
shipping fields, tool arguments, or a user-facing answer. Missing skin type or
sensitivity is not an ambiguity for recommendations.

Korean reference rules:
- When has_recent_result=true, "마지막 상품 주문해줘", "마지막 거 구매할래", or
  "마지막 상품 담아줘" explicitly refers to the final product in that immediately
  previous result. Set target_scope=last_tool_result and reference_position="last".
- For "마지막 상품 주문해줘", set route=product_reference and
  action=prepare_product_checkout. The request is a purchase preparation, not an
  order-history request, and is not ambiguous.
- Use order_after_sales only for an already-created order's history, status,
  cancellation, review, return, exchange, or refund. Do not use it merely because a
  user says "주문" or "구매" for a product.
- A request such as "인기 상품 중 나이아신아마이드가 들어간 제품을 전부 찜해줘"
  is complete when it names at least one ingredient. If no rank is stated, use the
  standard top-50 range. A stated rank must be from 1 through 50. Set
  route=bulk_wishlist, action=bulk_wishlist_by_popular_ingredient, and
  target_scope=none. It does not refer to a current product, cart item, or prior result,
  and must not be treated as ambiguous merely because the user asks for every match.
- A natural delivery-address entry such as
  "김원우 / 01012345678 / 12345 / 서울특별시 강남구 테헤란로 1" is a complete
  address-registration request when it contains a recipient, phone, postal code, and
  address. Set route=cart_checkout, action=register_shipping_address, and
  target_scope=none. It is independent of the current product and must not be blocked
  by a missing product reference.
- A multi-category routine composition with a total budget, such as
  "내 피부 타입에 맞는 토너, 세럼, 크림을 5만원 이내로 구성해줘", is not a
  product search. Set route=cart_checkout, action=compose_cart, and
  target_scope=none. The stated budget is the total budget for the entire
  composition, never a per-product price filter. Do not select
  create_recommendation or refine_product_results for this request.
""".strip()


_RECOMMENDATION_INSTRUCTIONS = """
Handle only a new Korean cosmetics recommendation request.
Call create_recommendation exactly once for a concrete skin concern or product search.
Use the user's original wording as concern_text. Extract every representable structured
constraint: concern IDs, effect IDs, excluded concerns, priority effects, skin type,
sensitivity, avoid ingredients, required ingredients, category, and price range. The
recommendation backend treats these structured fields as authoritative and does not
re-parse concern_text. Omit a field only when the user did not express a matching
concept; do not invent values outside the controlled vocabulary below.

Controlled Korean concern vocabulary:
- 여드름/뾰루지=concern_acne; 잡티/기미=concern_brightening_spots;
  모공/피지/번들거림=concern_pore; 속건조/당김/화장 들뜸=concern_dry_barrier;
  주름/탄력=concern_wrinkle_elasticity; 홍조/자극=concern_redness_irritation;
  민감/예민=concern_sensitive; 각질/거친 피부결=concern_dead_skin_texture;
  흉터/트러블 자국=concern_blemish_mark; 칙칙함/안색=concern_dull_uneven_tone;
  모낭염=concern_folliculitis; 다크서클=concern_dark_circle.
- Put a negated concern in excluded_concern_ids instead of concern_ids.

Controlled Korean effect vocabulary:
- 여드름/피지/번들거림=effect_acne_sebum; 진정/붉음/열감=effect_calming;
  각질=effect_exfoliation; 미백/톤/색소침착=effect_brightening;
  보습/장벽/속건조=effect_moisture_barrier; 주름/탄력=effect_wrinkle.
- When a stated concern maps to a directly relevant effect, include that effect in
  effect_ids and priority_effect_ids. For example, "피지가 많고 모공이 넓어" must
  include concern_ids=["concern_pore"] and
  effect_ids=priority_effect_ids=["effect_acne_sebum"].

Copy each user-named ingredient into an ingredient field verbatim. Do not translate,
shorten, spell-correct, or substitute an ingredient name. The backend resolves the
catalog term, so preserving the user's original term is safer than guessing a variant.

Do not ask for skin type or sensitivity when absent: leave them null so the backend can
resolve a saved profile or its default. Do not claim medical outcomes. If the request is
truly empty or contradictory, reply with one short Korean clarification question.
""".strip()

_REFINEMENT_INSTRUCTIONS = """
Handle only a filter/refinement request for an existing product or recommendation result.
Call refine_product_results exactly once when a result reference is available. Extract
every stated category, price, ingredient, skin type, and sensitivity filter; never drop
one constraint when another is present. Product type must be sent as category_code using
this exact mapping: 세럼=serum, 크림=cream, 토너=toner, 로션=lotion. For example,
"3만원 이하 세럼만 보여줘" requires both max_price=30000 and category_code="serum".
Use only context identifiers supplied by the server; never invent IDs. Ask one brief
Korean clarification only when there is no saved or visible result to filter.
""".strip()

_PRODUCT_REFERENCE_INSTRUCTIONS = """
Handle only a request about the current, visible, or immediately previous product result.
Use find_similar_products for similar/alternative products, compare_products for an
explicit comparison, add_to_cart for a cart action, and prepare_product_checkout for an
order intent. Use server-provided references or reference_source/reference_rank fields;
never invent a product ID, rank, price, or stock fact. A purchase tool only prepares the
next confirmation/checkout step and must not claim that payment was completed.

When target_scope=last_tool_result and reference_position="last", the user has already
selected the final product in the immediately previous result. Call
prepare_product_checkout directly; do not ask them to name that product again.
""".strip()

_CART_CHECKOUT_INSTRUCTIONS = """
Handle only cart, checkout, natural delivery-address input, or multi-category routine
composition. Use the available tool that matches the request. When the selected action
is compose_cart, call it exactly once. Treat the stated budget as max_budget for the
entire set, not as a per-product price ceiling. Extract each stated product category
using only toner, serum, and cream. If the user requests a routine composition without
listing categories, use toner, serum, and cream. The tool returns a confirmation-gated
proposal, so do not claim that the cart has already changed. For a natural address,
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
bulk_wishlist_by_popular_ingredient exactly once when the request has one or more
supported criteria. Extract one or more named ingredients, explicit all/any semantics
when stated, category, and min/max price when stated. If no rank is stated, use the
standard top-50 range. A stated rank must be from 1 through 50; do not silently shrink
the requested rank. The server resolves real popularity, ingredient relations, products,
and confirmation; never invent IDs or perform the wishlist write yourself. Ask a
clarification only when the requested condition is actually unsupported or missing.

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


_CURRENT_PRODUCT_ACTIONS = frozenset(
    {
        ADD_TO_CART_TOOL,
        FIND_SIMILAR_PRODUCTS_TOOL,
        PREPARE_PRODUCT_CHECKOUT_TOOL,
    }
)
_EXPLICIT_PREVIOUS_RESULT_REFERENCE_RE = re.compile(
    r"(?:\\b(?:last|final|first|second|third)\\b|마지막|최종|끝(?:의)?\\s*(?:상품|제품)?|"
    r"(?:첫|두|세|네|다섯)\\s*번째|\\d+\\s*번째|그\\s*중)"
)
_SELECTED_PRODUCT_ORDINAL_RE = re.compile(
    r"(?:\b(?P<english>first|second|third|fourth|fifth)\b|"
    r"(?P<numeric>[1-9][0-9]?)\s*(?:번째|번)|"
    r"(?P<korean>첫|두|세|네|다섯)\s*(?:번째|째))",
    re.IGNORECASE,
)
_ENGLISH_ORDINAL_RANKS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_KOREAN_ORDINAL_RANKS = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}

_ROUTINE_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("toner", re.compile(r"(?:토너|스킨)")),
    ("serum", re.compile(r"(?:세럼|앰플)")),
    ("cream", re.compile(r"(?:크림|로션)")),
)
_ROUTINE_COMPOSITION_RE = re.compile(r"(?:루틴|구성|세트|조합)")
_TOTAL_BUDGET_RE = re.compile(r"\d[\d,]*(?:\s*만원|\s*만\s*원|\s*원)")


def _is_explicit_routine_composition_request(message: str) -> bool:
    """Recognize an unambiguous total-budget multi-category composition request.

    This is a Router contract safeguard, not a tool-executing natural-language fast
    path. It only corrects a semantically impossible Router decision where a request
    names multiple routine categories, a total budget, and an explicit composition
    intent. The Specialist still extracts the tool arguments and the backend keeps the
    confirmation gate before changing the cart.
    """

    if (
        _ROUTINE_COMPOSITION_RE.search(message) is None
        or _TOTAL_BUDGET_RE.search(message) is None
    ):
        return False
    matched_categories = {
        category_code
        for category_code, pattern in _ROUTINE_CATEGORY_PATTERNS
        if pattern.search(message) is not None
    }
    return len(matched_categories) >= 2


def _selected_product_ordinal_rank(message: str, *, selected_count: int) -> int | None:
    """Return an explicit comparison-card ordinal when it is in range."""

    match = _SELECTED_PRODUCT_ORDINAL_RE.search(message)
    if match is None:
        return None

    if english := match.group("english"):
        rank = _ENGLISH_ORDINAL_RANKS[english.lower()]
    elif numeric := match.group("numeric"):
        rank = int(numeric)
    else:
        rank = _KOREAN_ORDINAL_RANKS[match.group("korean")]
    return rank if rank <= selected_count else None


def normalize_route_decision(
    decision: RouteDecision,
    *,
    request: AgentChatRequest,
) -> RouteDecision:
    """Apply narrow server-owned constraints to a Router decision.

    These checks do not execute tools or replace general natural-language routing. They
    only preserve unambiguous contracts that would otherwise be unsafe or impossible to
    recover in the Specialist because it sees just the Router-selected tool.
    """

    if _is_explicit_routine_composition_request(request.message):
        return decision.model_copy(
            update={
                "route": "cart_checkout",
                "action": COMPOSE_CART_TOOL,
                "target_scope": "none",
                "reference_position": None,
                "reference_rank": None,
                "confidence": "high",
            }
        )

    selected_rank = _selected_product_ordinal_rank(
        request.message,
        selected_count=len(request.context.selected_product_ids),
    )
    if decision.action in _CURRENT_PRODUCT_ACTIONS and selected_rank is not None:
        return decision.model_copy(
            update={
                "target_scope": "selected_products",
                "reference_position": None,
                "reference_rank": selected_rank,
            }
        )

    if (
        decision.action not in _CURRENT_PRODUCT_ACTIONS
        or decision.target_scope != "last_tool_result"
        or request.context.current_product_id is None
        or _EXPLICIT_PREVIOUS_RESULT_REFERENCE_RE.search(request.message) is not None
    ):
        return decision

    return decision.model_copy(
        update={
            "target_scope": "current_product",
            "reference_position": None,
            "reference_rank": None,
        }
    )


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
        "action": decision.action,
        "target_scope": decision.target_scope,
        "reference_position": decision.reference_position,
        "reference_rank": decision.reference_rank,
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
    """Expose only the Router-selected operation to the Specialist.

    Natural-language interpretation belongs to the Router.  The server only checks
    that the selected action is valid for this route and currently available.
    """

    profile = SPECIALIST_PROFILES[decision.route]
    allowed = set(allowed_tool_names)
    if decision.action == "clarify":
        return ()
    if decision.action in profile.tool_names and decision.action in allowed:
        return (decision.action,)
    return ()


def validate_route_decision(
    decision: RouteDecision,
    *,
    request: AgentChatRequest,
    user: User | None,
    allowed_tool_names: tuple[AgentToolName, ...],
) -> str | None:
    """Return a safe clarification reason when a route cannot execute here."""

    if decision.route == "clarification" or decision.action == "clarify":
        return None

    profile = SPECIALIST_PROFILES[decision.route]
    if decision.action not in profile.tool_names:
        return "요청 작업을 안전하게 결정하지 못했어요. 조금 더 구체적으로 알려주세요."

    if decision.reference_position is not None and decision.reference_rank is not None:
        return "상품 선택 기준을 하나만 알려주세요."

    target_scope = decision.target_scope
    is_target_independent_operation = decision.action in {
        BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        REGISTER_SHIPPING_ADDRESS_TOOL,
    }
    if target_scope == "ambiguous" and not is_target_independent_operation:
        return "어떤 상품이나 항목을 뜻하는지 조금 더 구체적으로 알려주세요."
    if target_scope == "current_product" and request.context.current_product_id is None:
        return "현재 보고 있는 상품을 먼저 확인해주세요."
    if target_scope == "selected_products" and not request.context.selected_product_ids:
        return "비교 상품을 먼저 확인해주세요."
    if target_scope == "selected_products" and (
        decision.reference_rank is None
        or decision.reference_rank < 1
        or decision.reference_rank > len(request.context.selected_product_ids)
    ):
        return "비교 상품 중 몇 번째 상품인지 알려주세요."
    if target_scope == "cart_selection" and not request.context.cart_item_ids:
        return "주문할 장바구니 상품을 먼저 선택해주세요."
    if target_scope == "last_tool_result" and not any(
        item.item_type == "product"
        for item in (request.last_tool_result.items if request.last_tool_result else [])
    ):
        return "직전 결과에서 선택할 상품을 찾지 못했어요."
    if target_scope == "last_tool_result" and (
        decision.reference_position is None and decision.reference_rank is None
    ):
        return "직전 결과 중 몇 번째 상품인지 알려주세요."
    if target_scope == "recommendation_result" and request.context.recommendation_id is None:
        return "추천 결과를 먼저 확인한 뒤 원하는 조건을 말씀해 주세요."
    if (
        target_scope == "recommendation_result"
        and decision.action == PREPARE_PRODUCT_CHECKOUT_TOOL
        and decision.reference_rank is None
    ):
        return "추천 결과 중 몇 번째 상품인지 알려주세요."
    if target_scope == "visible_products" and not request.context.visible_product_ids:
        return "현재 화면의 상품 목록을 먼저 확인해주세요."
    if (
        target_scope == "visible_products"
        and decision.action
        in {ADD_TO_CART_TOOL, FIND_SIMILAR_PRODUCTS_TOOL, PREPARE_PRODUCT_CHECKOUT_TOOL}
        and len(request.context.visible_product_ids) > 1
        and decision.reference_rank is None
    ):
        return "현재 목록 중 몇 번째 상품인지 알려주세요."

    if decision.action == PREPARE_PRODUCT_CHECKOUT_TOOL and target_scope not in {
        "current_product",
        "selected_products",
        "last_tool_result",
        "recommendation_result",
        "visible_products",
    }:
        return "주문할 상품을 먼저 선택해주세요."
    if decision.action in {PREPARE_CHECKOUT_TOOL, PREPARE_ORDER_TOOL} and target_scope != "cart_selection":
        return "주문할 장바구니 상품을 먼저 선택해주세요."

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


def _safe_route_path(value: str | None) -> str | None:
    """Keep routing information while excluding query-string identifiers."""

    if value is None:
        return None
    return value.split("?", 1)[0].split("#", 1)[0] or None
