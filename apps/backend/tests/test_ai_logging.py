import json
import logging
from types import SimpleNamespace

from app.core.ai_logging import (
    estimate_ai_cost_breakdown,
    estimate_ai_cost_usd,
    extract_agents_usage,
    extract_agents_usage_breakdown,
    extract_chat_completion_usage_from_body,
    log_ai_call,
)


def test_extract_chat_completion_usage_from_body_normalizes_tokens() -> None:
    usage = extract_chat_completion_usage_from_body(
        json.dumps(
            {
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                }
            }
        )
    )

    assert usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_extract_agents_usage_sums_nested_response_usage() -> None:
    result = SimpleNamespace(
        raw_responses=[
            SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)),
            SimpleNamespace(usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}),
        ]
    )

    assert extract_agents_usage(result) == {
        "input_tokens": 13,
        "output_tokens": 7,
        "total_tokens": 20,
    }


def test_extract_agents_usage_breakdown_keeps_cached_and_reasoning_tokens() -> None:
    result = SimpleNamespace(
        raw_responses=[
            SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    input_tokens_details=SimpleNamespace(cached_tokens=40),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=7),
                )
            )
        ]
    )

    assert extract_agents_usage_breakdown(result) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "cached_input_tokens": 40,
        "reasoning_tokens": 7,
    }


def test_log_ai_call_emits_no_prompt_or_response_body() -> None:
    logs = _capture_performance_logs()
    try:
        log_ai_call(
            "agent_chat",
            model="gpt-test",
            duration_ms=12.3,
            request_id="req_ai_log",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            metadata={
                "tool_name": "find_similar_products",
                "prompt": "raw prompt must not be logged",
                "response": "raw response must not be logged",
                "message": "user message must not be logged",
            },
        )
    finally:
        logs.close()

    payload = logs.json_lines[-1]
    assert payload["event"] == "ai_call_completed"
    assert payload["operation"] == "agent_chat"
    assert payload["model"] == "gpt-test"
    assert payload["request_id"] == "req_ai_log"
    assert payload["input_tokens"] == 10
    assert payload["output_tokens"] == 5
    assert payload["total_tokens"] == 15
    assert payload["cost_usd"] is None
    assert "prompt" not in payload
    assert "response" not in payload
    assert "message" not in payload


def test_estimate_ai_cost_uses_model_prefix_and_token_usage() -> None:
    assert estimate_ai_cost_usd(
        "gpt-5.5",
        {"input_tokens": 10, "output_tokens": 5},
    ) == 0.0002
    assert estimate_ai_cost_usd(
        "private-model-alias",
        {"input_tokens": 10, "output_tokens": 5},
    ) is None


def test_cost_breakdown_exposes_local_estimate_assumptions() -> None:
    breakdown = estimate_ai_cost_breakdown(
        "gpt-5.5",
        {
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 4},
        },
    )

    assert breakdown["estimate_status"] == "estimated_with_cache_detail"
    assert breakdown["usage"] == {
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
        "cached_input_tokens": 40,
        "reasoning_tokens": 4,
        "uncached_input_tokens": 60,
    }
    assert breakdown["estimated_cost_usd"] == 0.00062
    assert breakdown["rates_usd_per_1m_tokens"] == {
        "input": 5.0,
        "cached_input": 0.5,
        "output": 30.0,
    }


def test_cost_breakdown_supports_gpt_54_nano_snapshot() -> None:
    breakdown = estimate_ai_cost_breakdown(
        "gpt-5.4-nano-2026-03-17",
        {"input_tokens": 1_000, "output_tokens": 100, "total_tokens": 1_100},
    )

    assert breakdown["estimate_status"] == "estimated_without_cache_detail"
    assert breakdown["estimated_cost_usd"] == 0.000325
    assert breakdown["rates_usd_per_1m_tokens"] == {
        "input": 0.2,
        "cached_input": 0.02,
        "output": 1.25,
    }


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    logger.setLevel(logging.INFO)
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler
