import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.agent import AgentChatRequest, AgentChatResponse, AgentContext, AgentUiAction
from app.services.agent_orchestration import (
    RouteDecision,
    build_router_input,
    select_specialist_tool_names,
    validate_route_decision,
)
from app.services.agent_openai_runner import (
    _OpenAICircuitBreaker,
    _OpenAIConcurrencyLimiter,
    _specialist_fallback_reason,
    run_openai_agent_chat,
)


def test_router_input_keeps_auth_boolean_and_excludes_identifier_context() -> None:
    request = AgentChatRequest(
        message="피지가 많고 모공이 넓어 고민이야",
        context=AgentContext(
            page="product_detail",
            route="/product-detail?id=prod_private#details",
            current_product_id="prod_private",
            visible_product_ids=["prod_visible"],
            selected_product_ids=["prod_selected"],
            recommendation_id="rec_private",
            cart_item_ids=[10],
            address_id=3,
        ),
    )

    payload = json.loads(build_router_input(request, user=None))

    assert payload["authenticated"] is False
    assert payload["route"] == "/product-detail"
    assert payload["has_current_product"] is True
    assert payload["has_visible_products"] is True
    assert "current_product_id" not in payload
    assert "prod_private" not in json.dumps(payload, ensure_ascii=False)
    assert "rec_private" not in json.dumps(payload, ensure_ascii=False)


def test_route_validation_blocks_missing_reference_and_guest_bulk_wishlist() -> None:
    refinement = RouteDecision(route="recommendation_refinement", confidence="high")
    bulk = RouteDecision(route="bulk_wishlist", confidence="high")
    request = AgentChatRequest(message="3만원 이하 세럼만 보여줘")

    assert validate_route_decision(
        refinement,
        request=request,
        user=None,
        allowed_tool_names=("refine_product_results",),
    ) == "추천 결과를 먼저 확인한 뒤 원하는 조건을 말씀해 주세요."
    assert validate_route_decision(
        bulk,
        request=request,
        user=None,
        allowed_tool_names=("bulk_wishlist_by_popular_ingredient",),
    ) == "로그인이 필요한 기능이에요. 로그인 후 다시 요청해 주세요."


def test_specialist_tool_selection_exposes_only_operation_tools() -> None:
    product_request = AgentChatRequest(
        message="비슷한 상품 2개 보여줘",
        context=AgentContext(page="product_detail", current_product_id="prod_001"),
    )
    order_request = AgentChatRequest(
        message="배송 상태 알려줘",
        context=AgentContext(page="order_detail"),
    )

    assert select_specialist_tool_names(
        RouteDecision(route="product_reference", confidence="high"),
        request=product_request,
        allowed_tool_names=(
            "find_similar_products",
            "compare_products",
            "add_to_cart",
        ),
    ) == ("find_similar_products",)
    assert select_specialist_tool_names(
        RouteDecision(route="order_after_sales", confidence="high"),
        request=order_request,
        allowed_tool_names=("order_status_lookup", "filter_order_history"),
    ) == ("order_status_lookup",)


@pytest.mark.anyio
async def test_router_specialist_runs_tool_free_router_then_narrow_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agents
    from agents import Runner

    calls: list[dict[str, object]] = []

    @contextmanager
    def fake_trace(*_args, **_kwargs):
        yield SimpleNamespace()

    async def fake_run(agent, *, input, context, **_kwargs):
        tool_names = tuple(getattr(tool, "name", None) for tool in agent.tools)
        calls.append({"name": agent.name, "tools": tool_names, "input": input, "model": agent.model})
        if len(calls) == 1:
            assert tool_names == ()
            return SimpleNamespace(final_output=RouteDecision(route="recommendation", confidence="high"))
        context.last_tool_response = AgentChatResponse(
            conversation_id="conv_router_test",
            message="추천 결과를 준비했어요.",
            tool_name="create_recommendation",
            ui_action=AgentUiAction(type="show_products", target="product_list"),
        )
        return SimpleNamespace(final_output="unused")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_execution_mode", "router_specialist")
    monkeypatch.setattr(settings, "openai_agent_router_model", "router-nano")
    monkeypatch.setattr(settings, "openai_agent_specialist_model", "specialist-nano")
    monkeypatch.setattr(settings, "openai_agent_specialist_fallback_enabled", False)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(agents, "trace", fake_trace)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=2, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )

    response = await run_openai_agent_chat(
        SimpleNamespace(),
        AgentChatRequest(message="피지가 많고 모공이 넓어 고민이야"),
    )

    assert response.tool_name == "create_recommendation"
    assert [call["name"] for call in calls] == [
        "mwobarellae_action_router",
        "mwobarellae_recommendation_specialist",
    ]
    assert calls[1]["tools"] == ("create_recommendation",)
    assert calls[1]["model"] == "specialist-nano"


@pytest.mark.anyio
async def test_router_specialist_fast_path_runs_before_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_execute_agent_tool(*_args, **_kwargs) -> AgentChatResponse:
        return AgentChatResponse(
            conversation_id="conv_fast_path",
            message="조건에 맞는 상품을 찾았어요.",
            tool_name="refine_product_results",
            ui_action=AgentUiAction(type="show_products", target="product_list"),
        )

    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_agent_execution_mode", "router_specialist")
    monkeypatch.setattr(
        "app.services.agent_openai_runner.execute_agent_tool",
        fake_execute_agent_tool,
    )

    response = await run_openai_agent_chat(
        SimpleNamespace(),
        AgentChatRequest(
            message="3만원 이하 세럼만 보여줘",
            context=AgentContext(page="search_results", recommendation_id="rec_001"),
        ),
    )

    assert calls == 0
    assert response.tool_name == "refine_product_results"


@pytest.mark.anyio
async def test_specialist_fallback_is_once_and_keeps_same_tool_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agents
    from agents import Runner

    calls: list[dict[str, object]] = []

    @contextmanager
    def fake_trace(*_args, **_kwargs):
        yield SimpleNamespace()

    async def fake_run(agent, *, input, context, **_kwargs):
        tool_names = tuple(getattr(tool, "name", None) for tool in agent.tools)
        calls.append({"name": agent.name, "tools": tool_names, "input": input, "model": agent.model})
        if len(calls) == 1:
            return SimpleNamespace(final_output=RouteDecision(route="recommendation", confidence="high"))
        if len(calls) == 3:
            context.last_tool_response = AgentChatResponse(
                conversation_id="conv_fallback_test",
                message="추천 결과를 준비했어요.",
                tool_name="create_recommendation",
                ui_action=AgentUiAction(type="show_products", target="product_list"),
            )
        return SimpleNamespace(final_output="모델이 도구를 호출하지 않았어요.")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_execution_mode", "router_specialist")
    monkeypatch.setattr(settings, "openai_agent_router_model", "router-nano")
    monkeypatch.setattr(settings, "openai_agent_specialist_model", "specialist-nano")
    monkeypatch.setattr(settings, "openai_agent_specialist_fallback_enabled", True)
    monkeypatch.setattr(settings, "openai_agent_specialist_fallback_model", "gpt-5.5")
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(agents, "trace", fake_trace)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=2, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )

    response = await run_openai_agent_chat(
        SimpleNamespace(),
        AgentChatRequest(message="피지가 많고 모공이 넓어 고민이야"),
    )

    assert response.tool_name == "create_recommendation"
    assert [call["name"] for call in calls] == [
        "mwobarellae_action_router",
        "mwobarellae_recommendation_specialist",
        "mwobarellae_recommendation_specialist_fallback",
    ]
    assert calls[1]["tools"] == calls[2]["tools"] == ("create_recommendation",)
    assert calls[2]["model"] == "gpt-5.5"


def test_specialist_fallback_does_not_run_after_deadline() -> None:
    decision = RouteDecision(route="recommendation", confidence="high")
    assert _specialist_fallback_reason(
        enabled=True,
        decision=decision,
        context=SimpleNamespace(last_tool_response=None),
        specialist_result=SimpleNamespace(final_output="no tool"),
        specialist_error=None,
        deadline=time.monotonic() - 0.1,
    ) is None
