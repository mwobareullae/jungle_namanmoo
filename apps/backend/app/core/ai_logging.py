import json
import logging
from collections.abc import Mapping
from typing import Any

from app.core.performance_logging import get_current_request_id, log_performance_event


TOKEN_USAGE_KEYS = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "total_tokens": ("total_tokens",),
}
TOKEN_USAGE_DETAIL_PATHS = {
    "cached_input_tokens": (
        ("input_tokens_details", "cached_tokens"),
        ("prompt_tokens_details", "cached_tokens"),
        ("cached_input_tokens",),
        ("cache_read_input_tokens",),
    ),
    "reasoning_tokens": (
        ("output_tokens_details", "reasoning_tokens"),
        ("completion_tokens_details", "reasoning_tokens"),
        ("reasoning_tokens",),
    ),
}
# Standard text-token rates in USD per one million tokens. Keep this table
# intentionally small and return null for unknown/private model aliases rather
# than logging a misleading estimate.
MODEL_TOKEN_PRICES = {
    "gpt-5.5": {"input": 5.0, "cached_input": 0.5, "output": 30.0},
    "gpt-5.4-nano": {"input": 0.2, "cached_input": 0.02, "output": 1.25},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.5},
    "gpt-5.4": {"input": 2.5, "cached_input": 0.25, "output": 15.0},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "text-embedding-3-small": {"input": 0.02, "cached_input": 0.0, "output": 0.0},
}
_BLOCKED_METADATA_KEYS = {
    "prompt",
    "raw_prompt",
    "response",
    "raw_response",
    "messages",
    "message",
    "user_message",
    "user_input",
    "input_text",
    "output_text",
    "final_output",
}


def log_ai_call(
    operation: str,
    *,
    model: str | None,
    duration_ms: float,
    request_id: str | None = None,
    provider: str = "openai",
    usage: Mapping[str, Any] | None = None,
    success: bool = True,
    error: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    token_usage = normalize_token_usage_breakdown(usage)
    cost_estimate = estimate_ai_cost_breakdown(model, token_usage)
    log_performance_event(
        "ai_call_completed" if success else "ai_call_failed",
        request_id=request_id or get_current_request_id(),
        duration_ms=duration_ms,
        metadata={
            "provider": provider,
            "operation": operation,
            "model": model,
            "success": success,
            "error": error,
            "input_tokens": token_usage["input_tokens"],
            "cached_input_tokens": token_usage["cached_input_tokens"],
            "output_tokens": token_usage["output_tokens"],
            "reasoning_tokens": token_usage["reasoning_tokens"],
            "total_tokens": token_usage["total_tokens"],
            "cost_usd": cost_estimate["estimated_cost_usd"],
            "cost_estimate_status": cost_estimate["estimate_status"],
            **_safe_metadata(metadata),
        },
        level=logging.INFO if success else logging.WARNING,
    )


def estimate_ai_cost_usd(
    model: str | None,
    usage: Mapping[str, Any] | None,
) -> float | None:
    """Estimate text-token cost without logging prompts or responses."""
    return estimate_ai_cost_breakdown(model, usage)["estimated_cost_usd"]


def estimate_ai_cost_breakdown(
    model: str | None,
    usage: Any | None,
) -> dict[str, Any]:
    """Return a local diagnostic cost estimate with its pricing assumptions.

    The value is an estimate, not a billing-system total.  Reasoning tokens are
    already included in output tokens and are exposed only as a diagnostic
    breakdown, never charged a second time.
    """
    normalized_usage = normalize_token_usage_breakdown(usage)
    normalized_model = model.strip().lower() if model and model.strip() else None
    detail: dict[str, Any] = {
        "model": normalized_model,
        "currency": "USD",
        "pricing_basis": "standard_text_per_1m_tokens",
        "usage": normalized_usage,
        "rates_usd_per_1m_tokens": None,
        "estimated_cost_usd": None,
        "estimate_status": "usage_unavailable",
        "cache_detail_available": normalized_usage["cached_input_tokens"] is not None,
    }
    if normalized_model is None:
        detail["estimate_status"] = "model_unavailable"
        return detail

    rates = _resolve_model_token_prices(normalized_model)
    if rates is None:
        detail["estimate_status"] = "unknown_model_pricing"
        return detail
    detail["rates_usd_per_1m_tokens"] = dict(rates)

    input_tokens = normalized_usage["input_tokens"]
    output_tokens = normalized_usage["output_tokens"]
    if input_tokens is None or output_tokens is None:
        return detail

    cached_input_tokens = min(
        normalized_usage["cached_input_tokens"] or 0,
        input_tokens,
    )
    uncached_input_tokens = input_tokens - cached_input_tokens
    estimated = (
        uncached_input_tokens * rates["input"]
        + cached_input_tokens * rates["cached_input"]
        + output_tokens * rates["output"]
    ) / 1_000_000
    detail["usage"]["uncached_input_tokens"] = uncached_input_tokens
    detail["estimated_cost_usd"] = round(estimated, 8)
    detail["estimate_status"] = (
        "estimated_with_cache_detail"
        if normalized_usage["cached_input_tokens"] is not None
        else "estimated_without_cache_detail"
    )
    return detail


def normalize_token_usage(usage: Mapping[str, Any] | None) -> dict[str, int | None]:
    return {
        output_key: _first_int(usage, input_keys)
        for output_key, input_keys in TOKEN_USAGE_KEYS.items()
    }


def normalize_token_usage_breakdown(usage: Any | None) -> dict[str, int | None]:
    """Normalize standard, cached-input, and reasoning token counters."""
    mapping = _usage_to_mapping(usage)
    normalized = normalize_token_usage(mapping)
    for output_key, paths in TOKEN_USAGE_DETAIL_PATHS.items():
        normalized[output_key] = _first_int_path(mapping, paths)
    if (
        normalized["total_tokens"] is None
        and normalized["input_tokens"] is not None
        and normalized["output_tokens"] is not None
    ):
        normalized["total_tokens"] = normalized["input_tokens"] + normalized["output_tokens"]
    return normalized


def extract_chat_completion_usage_from_body(body: str | bytes | None) -> dict[str, int | None]:
    if body is None:
        return normalize_token_usage(None)
    try:
        decoded = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return normalize_token_usage(None)
    usage = decoded.get("usage") if isinstance(decoded, dict) else None
    return normalize_token_usage(usage if isinstance(usage, Mapping) else None)


def extract_agents_usage(result: Any) -> dict[str, int | None]:
    breakdown = extract_agents_usage_breakdown(result)
    return {
        "input_tokens": breakdown["input_tokens"],
        "output_tokens": breakdown["output_tokens"],
        "total_tokens": breakdown["total_tokens"],
    }


def extract_agents_usage_breakdown(result: Any) -> dict[str, int | None]:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
    }
    found_keys = {key: False for key in totals}

    for usage in _iter_usage_objects(result):
        normalized = normalize_token_usage_breakdown(usage)
        for key, value in normalized.items():
            if value is not None:
                totals[key] += value
                found_keys[key] = True

    return {
        key: totals[key] if found_keys[key] else None
        for key in totals
    }


def _iter_usage_objects(value: Any) -> list[Any]:
    usage_objects: list[Any] = []
    seen: set[int] = set()

    def visit(item: Any, depth: int = 0) -> None:
        if item is None or depth > 4:
            return
        item_id = id(item)
        if item_id in seen:
            return
        seen.add(item_id)

        usage = getattr(item, "usage", None)
        if usage is not None:
            usage_objects.append(usage)

        if isinstance(item, Mapping):
            if "usage" in item:
                usage_objects.append(item["usage"])
            for key in ("raw_responses", "responses", "model_responses", "items", "new_items"):
                child = item.get(key)
                if child is not None:
                    visit(child, depth + 1)
            return

        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child, depth + 1)
            return

        for attr in ("raw_responses", "responses", "model_responses", "items", "new_items"):
            child = getattr(item, attr, None)
            if child is not None:
                visit(child, depth + 1)

    visit(value)
    return usage_objects


def _usage_to_mapping(usage: Any) -> Mapping[str, Any] | None:
    if isinstance(usage, Mapping):
        return usage
    values = {
        key: getattr(usage, key, None)
        for keys in TOKEN_USAGE_KEYS.values()
        for key in keys
        if hasattr(usage, key)
    }
    for detail_key in (
        "input_tokens_details",
        "prompt_tokens_details",
        "output_tokens_details",
        "completion_tokens_details",
    ):
        detail_value = getattr(usage, detail_key, None)
        if detail_value is not None:
            values[detail_key] = detail_value
    return values or None


def _first_int(usage: Mapping[str, Any] | None, keys: tuple[str, ...]) -> int | None:
    if usage is None:
        return None
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _first_int_path(
    usage: Mapping[str, Any] | None,
    paths: tuple[tuple[str, ...], ...],
) -> int | None:
    for path in paths:
        current: Any = usage
        for key in path:
            if isinstance(current, Mapping):
                current = current.get(key)
            else:
                current = getattr(current, key, None)
            if current is None:
                break
        value = _coerce_int(current)
        if value is not None:
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _resolve_model_token_prices(model: str) -> dict[str, float] | None:
    for model_prefix in sorted(MODEL_TOKEN_PRICES, key=len, reverse=True):
        if model.startswith(model_prefix):
            return MODEL_TOKEN_PRICES[model_prefix]
    return None


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(metadata or {}).items()
        if str(key).lower() not in _BLOCKED_METADATA_KEYS
    }
