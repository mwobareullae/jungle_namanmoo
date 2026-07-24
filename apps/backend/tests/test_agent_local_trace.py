from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.agent import AgentChatRequest, AgentChatResponse, AgentContext, AgentUiAction
from app.services.agent_local_trace import create_agent_local_trace


class _FakeTool:
    name = "create_recommendation"
    description = "Create a recommendation from a structured product need."
    params_json_schema = {
        "type": "object",
        "properties": {
            "concern_text": {"type": "string"},
            "page_size": {"type": "integer", "default": 10},
        },
        "required": ["concern_text"],
    }


def _enable_local_trace(monkeypatch: pytest.MonkeyPatch, trace_dir) -> None:
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "openai_agent_local_trace_enabled", True)
    monkeypatch.setattr(settings, "openai_agent_local_trace_dir", str(trace_dir))


def test_local_agent_trace_keeps_raw_request_tool_and_response_values(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local_trace(monkeypatch, tmp_path)
    request = AgentChatRequest(
        message="민감한 수부지 피부에 보습 세럼 추천해줘",
        conversation_id="conv-local-trace",
        context=AgentContext(page="home", filters={"skin_type": "수부지"}),
    )
    trace = create_agent_local_trace(
        request_id="req-local-trace",
        route="/api/agent/chat",
        request_payload=request,
        authenticated=False,
    )

    assert trace is not None
    trace.capture_agent_configuration(
        model="gpt-5.4-mini",
        configured_model="gpt-5.5",
        model_source="local_header_override",
        instructions="Use exactly one tool.",
        model_settings={"tool_choice": "auto"},
        tool_use_behavior="stop_on_first_tool",
        selected_tools=[_FakeTool()],
        agent_input='{"message":"민감한 수부지 피부에 보습 세럼 추천해줘"}',
    )
    trace.record_runner_attempt(
        attempt=1,
        duration_ms=123.4,
        model="gpt-5.4-mini",
    )
    trace.capture_runner_result(
        SimpleNamespace(
            final_output="Raw model output.",
            new_items=[],
            raw_responses=[],
            input_guardrail_results=[],
            output_guardrail_results=[],
        ),
        usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        usage_breakdown={
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 10,
            "reasoning_tokens": 4,
            "total_tokens": 110,
        },
        cost_estimate={"currency": "USD", "estimated_cost_usd": 0.00062},
    )
    response = AgentChatResponse(
        conversation_id="conv-local-trace",
        message="추천 결과를 준비했어요.",
        tool_name="create_recommendation",
        ui_action=AgentUiAction(
            type="show_products",
            target="product_results",
            payload={"recommendation_id": "rec_001"},
        ),
    )
    trace.record_tool_call(
        tool_name="create_recommendation",
        model_arguments={"concern_text": "민감한 수부지 피부에 보습 세럼 추천해줘"},
        resolved_arguments={"concern_text": "민감한 수부지 피부에 보습 세럼 추천해줘"},
        response=response,
        sdk_return_value='{"recommendation_id":"rec_001"}',
        reference_resolve_ms=1.2,
        dispatch_ms=44.5,
        response_serialize_ms=0.8,
        total_ms=46.5,
    )
    response_payload = response.model_dump(mode="json")
    trace.capture_final_response(response_payload, model_dump_ms=0.4, json_encode_ms=0.2)
    trace.set_timing("agent_runner_ms", 123.4)
    written_path = trace.finish(outcome="succeeded")

    assert written_path is not None
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["capture_mode"] == "local_raw"
    assert payload["request"]["message"] == "민감한 수부지 피부에 보습 세럼 추천해줘"
    assert payload["agent"]["selected_tools"][0]["parameters"]["required"] == ["concern_text"]
    assert payload["tool_calls"][0]["model_arguments"]["concern_text"] == request.message
    assert payload["tool_calls"][0]["response"]["ui_action"]["payload"]["recommendation_id"] == "rec_001"
    assert payload["final_response"]["payload"]["tool_name"] == "create_recommendation"
    assert payload["timings_ms"]["agent_runner_ms"] == 123.4
    assert payload["agent"]["configured_model"] == "gpt-5.5"
    assert payload["agent"]["model"] == "gpt-5.4-mini"
    assert payload["agent"]["model_source"] == "local_header_override"
    assert payload["summary"]["question"] == request.message
    assert payload["summary"]["tokens"]["cached_input_tokens"] == 40
    assert payload["summary"]["estimated_cost"]["estimated_cost_usd"] == 0.00062


def test_local_agent_trace_is_disabled_outside_explicit_local_mode(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "openai_agent_local_trace_enabled", True)
    monkeypatch.setattr(settings, "openai_agent_local_trace_dir", str(tmp_path))

    trace = create_agent_local_trace(
        request_id="req-disabled",
        route="/api/agent/chat",
        request_payload=AgentChatRequest(message="보습 세럼 추천해줘"),
        authenticated=False,
    )

    assert trace is None
    assert list(tmp_path.iterdir()) == []
