from typing import get_args

import pytest

from app.schemas.agent import AgentContext, AgentToolName, AgentUiAction
from app.schemas.common import ApiError
from app.services.agent_policy import (
    AGENT_TOOL_POLICIES,
    validate_result_item_count,
    validate_tool_access,
    validate_tool_confirmation,
    validate_tool_ui_action,
    validate_ui_action,
)


def test_agent_tool_policies_cover_schema_tool_names() -> None:
    assert set(AGENT_TOOL_POLICIES) == set(get_args(AgentToolName))


def test_agent_context_accepts_filtered_recommendation_route() -> None:
    route = "/search?keyword=" + "%EB%AF%BC%EA%B0%90" * 40

    context = AgentContext(route=route)

    assert context.route == route


def test_order_tools_require_login() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_tool_access("order_status_lookup", user_id=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AGENT_AUTH_REQUIRED"

    policy = validate_tool_access("order_status_lookup", user_id=1)
    assert policy.requires_auth is True
    assert policy.requires_confirmation is False

    history_policy = validate_tool_access("filter_order_history", user_id=1)
    assert history_policy.risk_level == "READ"
    assert history_policy.allowed_ui_actions == frozenset({"navigate"})


def test_cancel_recent_order_requires_confirmation() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_tool_confirmation("cancel_recent_order", confirmed=False)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "AGENT_CONFIRMATION_REQUIRED"

    policy = validate_tool_confirmation("cancel_recent_order", confirmed=True)
    assert policy.risk_level == "DESTRUCTIVE"
    assert policy.requires_confirmation is True


def test_bulk_popular_ingredient_wishlist_requires_auth_and_confirmation() -> None:
    policy = AGENT_TOOL_POLICIES["bulk_wishlist_by_popular_ingredient"]
    assert policy.risk_level == "WRITE"
    assert policy.requires_auth is True
    assert policy.requires_confirmation is True
    assert policy.max_result_items == 50


def test_product_read_tools_allow_anonymous_access() -> None:
    policy = validate_tool_access("find_similar_products", user_id=None)

    assert policy.requires_auth is False
    assert policy.risk_level == "READ"

    recommendation_policy = validate_tool_access("create_recommendation", user_id=None)
    assert recommendation_policy.requires_auth is False
    assert recommendation_policy.allowed_ui_actions == frozenset({"show_products"})


def test_shipping_address_tool_is_authenticated_reversible_write() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_tool_access("register_shipping_address", user_id=None)

    assert exc_info.value.code == "AGENT_AUTH_REQUIRED"
    policy = validate_tool_access("register_shipping_address", user_id=1)
    assert policy.risk_level == "WRITE"
    assert policy.requires_confirmation is False
    assert policy.allowed_ui_actions == frozenset({"noop", "show_checkout_preview"})


def test_product_checkout_tool_stops_at_checkout_preview() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_tool_access("prepare_product_checkout", user_id=None)

    assert exc_info.value.code == "AGENT_AUTH_REQUIRED"
    policy = validate_tool_access("prepare_product_checkout", user_id=1)
    assert policy.risk_level == "WRITE"
    assert policy.requires_confirmation is False
    assert policy.allowed_ui_actions == frozenset({"noop", "show_checkout_preview"})


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_tool_access("delete_everything", user_id=1)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "UNKNOWN_AGENT_TOOL"


def test_ui_action_target_allowlist_is_enforced() -> None:
    valid = AgentUiAction(type="open_modal", target="order_cancel_confirm")
    assert validate_ui_action(valid) == valid

    with pytest.raises(ApiError) as exc_info:
        validate_ui_action(AgentUiAction(type="open_modal", target="raw_browser_script"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_UI_TARGET_NOT_ALLOWED"


def test_noop_ui_action_cannot_have_target() -> None:
    with pytest.raises(ApiError) as exc_info:
        validate_ui_action(AgentUiAction(type="noop", target="home"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_UI_TARGET_NOT_ALLOWED"


def test_tool_ui_action_must_match_policy() -> None:
    validate_tool_ui_action(
        "cancel_recent_order",
        AgentUiAction(type="open_modal", target="order_cancel_confirm"),
    )

    with pytest.raises(ApiError) as exc_info:
        validate_tool_ui_action(
            "cancel_recent_order",
            AgentUiAction(type="show_products", target="similar_products"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_TOOL_UI_ACTION_MISMATCH"


def test_result_item_count_is_limited_per_tool() -> None:
    validate_result_item_count("find_similar_products", 2)

    with pytest.raises(ApiError) as exc_info:
        validate_result_item_count("find_similar_products", 3)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_RESULT_LIMIT_EXCEEDED"
