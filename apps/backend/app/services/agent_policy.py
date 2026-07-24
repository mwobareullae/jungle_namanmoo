from dataclasses import dataclass
from typing import Literal, get_args

from app.schemas.agent import AgentToolName, AgentUiAction, AgentUiActionType
from app.schemas.common import ApiError


AgentToolRiskLevel = Literal["READ", "WRITE", "DESTRUCTIVE"]


@dataclass(frozen=True)
class AgentToolPolicy:
    tool_name: AgentToolName
    risk_level: AgentToolRiskLevel
    requires_auth: bool
    requires_confirmation: bool
    allowed_ui_actions: frozenset[AgentUiActionType]
    max_result_items: int
    timeout_ms: int


ALLOWED_UI_ACTION_TARGETS: dict[AgentUiActionType, frozenset[str]] = {
    "noop": frozenset(),
    "navigate": frozenset({"home", "login", "product_detail", "order_detail", "order_history", "checkout", "review_write", "claim_request"}),
    "open_modal": frozenset({"agent_confirmation", "order_cancel_confirm", "order_create_confirm"}),
    "show_products": frozenset({"product_results", "similar_products", "refined_products", "popular_wishlist"}),
    "show_product_comparison": frozenset({"product_comparison"}),
    "show_order_status": frozenset({"order_status"}),
    "show_cart": frozenset({"cart"}),
    "show_checkout_preview": frozenset({"checkout_preview"}),
    "open_payment": frozenset({"toss_payment"}),
}

AGENT_TOOL_POLICIES: dict[AgentToolName, AgentToolPolicy] = {
    "create_recommendation": AgentToolPolicy(
        tool_name="create_recommendation",
        risk_level="READ",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"show_products"}),
        max_result_items=20,
        timeout_ms=15_000,
    ),
    "filter_order_history": AgentToolPolicy(
        tool_name="filter_order_history",
        risk_level="READ",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"navigate"}),
        max_result_items=0,
        timeout_ms=1500,
    ),
    "order_status_lookup": AgentToolPolicy(
        tool_name="order_status_lookup",
        risk_level="READ",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "navigate", "show_order_status"}),
        max_result_items=5,
        timeout_ms=1500,
    ),
    "cancel_recent_order": AgentToolPolicy(
        tool_name="cancel_recent_order",
        risk_level="DESTRUCTIVE",
        requires_auth=True,
        requires_confirmation=True,
        allowed_ui_actions=frozenset({"noop", "open_modal", "show_order_status"}),
        max_result_items=1,
        timeout_ms=1500,
    ),
    "find_similar_products": AgentToolPolicy(
        tool_name="find_similar_products",
        risk_level="READ",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "navigate", "show_products"}),
        max_result_items=2,
        timeout_ms=2500,
    ),
    "compare_products": AgentToolPolicy(
        tool_name="compare_products",
        risk_level="READ",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "show_product_comparison"}),
        max_result_items=5,
        timeout_ms=2500,
    ),
    "refine_product_results": AgentToolPolicy(
        tool_name="refine_product_results",
        risk_level="READ",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "show_products"}),
        max_result_items=10,
        timeout_ms=2500,
    ),
    "get_cart": AgentToolPolicy(
        tool_name="get_cart",
        risk_level="READ",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"show_cart"}),
        max_result_items=0,
        timeout_ms=1500,
    ),
    "add_to_cart": AgentToolPolicy(
        tool_name="add_to_cart",
        risk_level="WRITE",
        requires_auth=False,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"show_cart"}),
        max_result_items=0,
        timeout_ms=1500,
    ),
    "prepare_product_checkout": AgentToolPolicy(
        tool_name="prepare_product_checkout",
        risk_level="WRITE",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "show_checkout_preview"}),
        max_result_items=1,
        timeout_ms=2500,
    ),
    "prepare_checkout": AgentToolPolicy(
        tool_name="prepare_checkout",
        risk_level="READ",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "show_checkout_preview", "navigate"}),
        max_result_items=0,
        timeout_ms=2000,
    ),
    "prepare_order": AgentToolPolicy(
        tool_name="prepare_order",
        risk_level="WRITE",
        requires_auth=True,
        requires_confirmation=True,
        allowed_ui_actions=frozenset({"open_modal", "open_payment"}),
        max_result_items=0,
        timeout_ms=2500,
    ),
    "register_shipping_address": AgentToolPolicy(
        tool_name="register_shipping_address",
        risk_level="WRITE",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"noop", "show_checkout_preview"}),
        max_result_items=0,
        timeout_ms=2500,
    ),
    "compose_cart": AgentToolPolicy(
        tool_name="compose_cart",
        risk_level="WRITE",
        requires_auth=True,
        requires_confirmation=True,
        allowed_ui_actions=frozenset({"open_modal", "show_cart"}),
        max_result_items=4,
        timeout_ms=3000,
    ),
    "bulk_wishlist_by_popular_ingredient": AgentToolPolicy(
        tool_name="bulk_wishlist_by_popular_ingredient",
        risk_level="WRITE",
        requires_auth=True,
        requires_confirmation=True,
        allowed_ui_actions=frozenset({"open_modal", "show_products"}),
        max_result_items=50,
        timeout_ms=3000,
    ),
    "prepare_review_draft": AgentToolPolicy(
        tool_name="prepare_review_draft",
        risk_level="READ",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"navigate"}),
        max_result_items=1,
        timeout_ms=2000,
    ),
    "prepare_claim_draft": AgentToolPolicy(
        tool_name="prepare_claim_draft",
        risk_level="READ",
        requires_auth=True,
        requires_confirmation=False,
        allowed_ui_actions=frozenset({"navigate"}),
        max_result_items=1,
        timeout_ms=2000,
    ),
}


def get_tool_policy(tool_name: str) -> AgentToolPolicy:
    policy = AGENT_TOOL_POLICIES.get(tool_name)  # type: ignore[arg-type]
    if policy is None:
        raise ApiError(400, "UNKNOWN_AGENT_TOOL", "지원하지 않는 에이전트 기능이에요.")
    return policy


def validate_tool_access(tool_name: str, *, user_id: int | None) -> AgentToolPolicy:
    policy = get_tool_policy(tool_name)
    if policy.requires_auth and user_id is None:
        raise ApiError(401, "AGENT_AUTH_REQUIRED", "로그인이 필요한 기능이에요.")
    return policy


def validate_tool_confirmation(tool_name: str, *, confirmed: bool) -> AgentToolPolicy:
    policy = get_tool_policy(tool_name)
    if policy.requires_confirmation and not confirmed:
        raise ApiError(409, "AGENT_CONFIRMATION_REQUIRED", "이 기능을 실행하려면 확인이 필요해요.")
    return policy


def validate_ui_action(action: AgentUiAction) -> AgentUiAction:
    allowed_action_types = set(get_args(AgentUiActionType))
    if action.type not in allowed_action_types:
        raise ApiError(400, "AGENT_UI_ACTION_NOT_ALLOWED", "허용되지 않은 화면 동작이에요.")

    allowed_targets = ALLOWED_UI_ACTION_TARGETS[action.type]
    if action.type == "noop":
        if action.target is not None:
            raise ApiError(400, "AGENT_UI_TARGET_NOT_ALLOWED", "실행하지 않는 화면 동작에는 대상을 지정할 수 없어요.")
        return action

    if action.target is None or action.target not in allowed_targets:
        raise ApiError(400, "AGENT_UI_TARGET_NOT_ALLOWED", "허용되지 않은 화면 동작 대상이에요.")
    return action


def validate_tool_ui_action(tool_name: str, action: AgentUiAction) -> AgentUiAction:
    policy = get_tool_policy(tool_name)
    validate_ui_action(action)
    if action.type not in policy.allowed_ui_actions:
        raise ApiError(400, "AGENT_TOOL_UI_ACTION_MISMATCH", "이 기능에서 실행할 수 없는 화면 동작이에요.")
    return action


def validate_result_item_count(tool_name: str, item_count: int) -> AgentToolPolicy:
    policy = get_tool_policy(tool_name)
    if item_count > policy.max_result_items:
        raise ApiError(400, "AGENT_RESULT_LIMIT_EXCEEDED", "한 번에 표시할 수 있는 상품 수를 초과했어요.")
    return policy
