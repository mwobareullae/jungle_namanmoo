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
# Standard text-token rates in USD per one million tokens. Keep this table
# intentionally small and return null for unknown/private model aliases rather
# than logging a misleading estimate.
MODEL_TOKEN_PRICES = {
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.4-mini": (0.75, 4.5),
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.0),
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
    token_usage = normalize_token_usage(usage)
    estimated_cost = estimate_ai_cost_usd(model, token_usage)
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
            "output_tokens": token_usage["output_tokens"],
            "total_tokens": token_usage["total_tokens"],
            "cost_usd": estimated_cost,
            **_safe_metadata(metadata),
        },
        level=logging.INFO if success else logging.WARNING,
    )


def estimate_ai_cost_usd(
    model: str | None,
    usage: Mapping[str, Any] | None,
) -> float | None:
    """Estimate text-token cost without logging prompts or responses."""
    if not model or usage is None:
        return None
    normalized_model = model.lower()
    price = next(
        (rates for model_prefix, rates in MODEL_TOKEN_PRICES.items() if normalized_model.startswith(model_prefix)),
        None,
    )
    normalized_usage = normalize_token_usage(usage)
    if price is None or normalized_usage["input_tokens"] is None or normalized_usage["output_tokens"] is None:
        return None
    input_price, output_price = price
    estimated = (
        normalized_usage["input_tokens"] * input_price
        + normalized_usage["output_tokens"] * output_price
    ) / 1_000_000
    return round(estimated, 8)


def normalize_token_usage(usage: Mapping[str, Any] | None) -> dict[str, int | None]:
    return {
        output_key: _first_int(usage, input_keys)
        for output_key, input_keys in TOKEN_USAGE_KEYS.items()
    }


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
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    found_usage = False

    for usage in _iter_usage_objects(result):
        normalized = normalize_token_usage(_usage_to_mapping(usage))
        if any(value is not None for value in normalized.values()):
            found_usage = True
        for key, value in normalized.items():
            if value is not None:
                totals[key] += value

    if not found_usage:
        return normalize_token_usage(None)
    return totals


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


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in dict(metadata or {}).items()
        if str(key).lower() not in _BLOCKED_METADATA_KEYS
    }
