"""Local-only raw execution traces for the OpenAI action agent.

This module intentionally writes complete request and response values only when a
developer explicitly enables it in a local environment.  It never emits those
values through the application's normal logs or OpenAI trace metadata.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app.core.config import settings


_TRACE_VERSION = 2
_MAX_SERIALIZATION_DEPTH = 12


def create_agent_local_trace(
    *,
    request_id: str | None,
    route: str,
    request_payload: Any,
    authenticated: bool,
) -> AgentLocalTrace | None:
    """Create a raw trace only for an explicitly enabled local run."""
    if not _is_enabled():
        return None

    try:
        return AgentLocalTrace(
            request_id=request_id,
            route=route,
            request_payload=request_payload,
            authenticated=authenticated,
        )
    except OSError:
        # Local diagnosis must never make the API unavailable when the trace
        # directory cannot be created or written.
        return None


def _is_enabled() -> bool:
    return (
        settings.app_env.strip().lower() == "local"
        and settings.openai_agent_local_trace_enabled
    )


class AgentLocalTrace:
    """Accumulates one local Agent request into a host-visible JSON document."""

    def __init__(
        self,
        *,
        request_id: str | None,
        route: str,
        request_payload: Any,
        authenticated: bool,
    ) -> None:
        self.trace_id = uuid4().hex
        self._started_at = time.perf_counter()
        self._completed = False
        captured_at = datetime.now(UTC)
        timestamp = captured_at.strftime("%Y%m%dT%H%M%S.%fZ")
        trace_dir = Path(settings.openai_agent_local_trace_dir)
        self.path = trace_dir / f"agent-{timestamp}-{self.trace_id}.json"
        self._payload: dict[str, Any] = {
            "trace_version": _TRACE_VERSION,
            "trace_id": self.trace_id,
            "capture_mode": "local_raw",
            "captured_at": captured_at.isoformat(),
            "timestamps": {"started_at": captured_at.isoformat(), "completed_at": None},
            "request": _json_safe(request_payload),
            "route": {
                "path": route,
                "request_id": request_id,
                "authenticated": authenticated,
                "app_env": settings.app_env,
            },
            "agent": {},
            "tool_calls": [],
            "timings_ms": {},
            "final_response": None,
            "error": None,
        }

    def set_timing(self, name: str, duration_ms: float) -> None:
        self._payload["timings_ms"][name] = round(max(float(duration_ms), 0.0), 2)

    def set_route_value(self, name: str, value: Any) -> None:
        self._payload["route"][name] = _json_safe(value)

    def capture_agent_configuration(
        self,
        *,
        model: str,
        configured_model: str | None = None,
        model_source: str = "configured_default",
        instructions: str,
        model_settings: Mapping[str, Any],
        tool_use_behavior: str,
        selected_tools: Sequence[Any],
        agent_input: str,
    ) -> None:
        tool_entries = [_serialize_tool(tool) for tool in selected_tools]
        self._payload["agent"] = {
            "name": "mwobarellae_action_agent",
            "model": model,
            "configured_model": configured_model or model,
            "model_source": model_source,
            "instructions": instructions,
            "instructions_bytes": _utf8_size(instructions),
            "model_settings": _json_safe(model_settings),
            "tool_use_behavior": tool_use_behavior,
            "selected_tool_count": len(tool_entries),
            "selected_tools": tool_entries,
            "selected_tool_schema_bytes": sum(
                entry.get("schema_bytes", 0) for entry in tool_entries
            ),
            "input": agent_input,
            "input_bytes": _utf8_size(agent_input),
        }

    def capture_short_circuit(
        self,
        *,
        reason: str,
        configured_model: str | None,
    ) -> None:
        """Record that a deterministic clarification completed without a model call."""
        zero_usage = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
        self._payload["agent"] = {
            "name": "mwobarellae_action_agent",
            "model": None,
            "configured_model": configured_model,
            "model_source": "not_called",
            "execution_mode": "short_circuit",
            "short_circuit_reason": reason,
            "runner_result": {
                "usage": zero_usage,
                "usage_breakdown": zero_usage,
                "cost_estimate": {
                    "currency": "USD",
                    "estimated_cost_usd": 0.0,
                    "estimate_status": "not_called",
                },
            },
        }

    def record_runner_attempt(
        self,
        *,
        attempt: int,
        duration_ms: float,
        model: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: Exception | None = None,
    ) -> None:
        attempts = self._payload["agent"].setdefault("runner_attempts", [])
        entry: dict[str, Any] = {
            "attempt": attempt,
            "duration_ms": round(max(float(duration_ms), 0.0), 2),
            "outcome": "error" if error is not None else "succeeded",
            "model": model,
            "started_at": started_at.isoformat() if started_at is not None else None,
            "completed_at": completed_at.isoformat() if completed_at is not None else None,
        }
        if error is not None:
            entry["exception_type"] = type(error).__name__
            entry["message"] = str(error)
        attempts.append(entry)

    def capture_runner_result(
        self,
        result: Any,
        *,
        usage: Any,
        usage_breakdown: Any | None = None,
        cost_estimate: Any | None = None,
    ) -> None:
        self._payload["agent"]["runner_result"] = {
            "type": type(result).__name__,
            "final_output": _json_safe(getattr(result, "final_output", None)),
            "new_items": _json_safe(getattr(result, "new_items", None)),
            "raw_responses": _json_safe(getattr(result, "raw_responses", None)),
            "input_guardrail_results": _json_safe(
                getattr(result, "input_guardrail_results", None)
            ),
            "output_guardrail_results": _json_safe(
                getattr(result, "output_guardrail_results", None)
            ),
            "usage": _json_safe(usage),
            "usage_breakdown": _json_safe(usage_breakdown),
            "cost_estimate": _json_safe(cost_estimate),
        }

    def record_tool_call(
        self,
        *,
        tool_name: str,
        model_arguments: Mapping[str, Any],
        resolved_arguments: Mapping[str, Any],
        response: Any,
        sdk_return_value: str,
        reference_resolve_ms: float,
        dispatch_ms: float,
        response_serialize_ms: float,
        total_ms: float,
    ) -> None:
        self._payload["tool_calls"].append(
            {
                "tool_name": tool_name,
                "model_arguments": _json_safe(model_arguments),
                "resolved_arguments": _json_safe(resolved_arguments),
                "response": _json_safe(response),
                "sdk_return_value": sdk_return_value,
                "sdk_return_bytes": _utf8_size(sdk_return_value),
                "timings_ms": {
                    "reference_resolve_ms": round(max(reference_resolve_ms, 0.0), 2),
                    "dispatch_ms": round(max(dispatch_ms, 0.0), 2),
                    "response_serialize_ms": round(max(response_serialize_ms, 0.0), 2),
                    "total_ms": round(max(total_ms, 0.0), 2),
                },
            }
        )

    def capture_final_response(self, response: Any, *, model_dump_ms: float, json_encode_ms: float) -> None:
        payload = _json_safe(response)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._payload["final_response"] = {
            "payload": payload,
            "bytes": _utf8_size(encoded),
        }
        self.set_timing("final_response_model_dump_ms", model_dump_ms)
        self.set_timing("final_response_json_encode_ms", json_encode_ms)

    def capture_error(self, exc: Exception, *, traceback_text: str | None = None) -> None:
        error: dict[str, Any] = {
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        if traceback_text:
            error["traceback"] = traceback_text
        self._payload["error"] = error

    def finish(self, *, outcome: str) -> Path | None:
        if self._completed:
            return self.path if self.path.exists() else None
        self._completed = True
        self._payload["route"]["outcome"] = outcome
        completed_at = datetime.now(UTC).isoformat()
        self._payload["completed_at"] = completed_at
        self._payload["timestamps"]["completed_at"] = completed_at
        self.set_timing("route_total_ms", (time.perf_counter() - self._started_at) * 1000)
        self._payload["summary"] = _build_summary(self._payload)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(self._payload, ensure_ascii=False, indent=2, default=str)
            temporary_path = self.path.with_suffix(".tmp")
            temporary_path.write_text(encoded, encoding="utf-8")
            temporary_path.replace(self.path)
        except OSError:
            return None
        return self.path


def _serialize_tool(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "params_json_schema", None)
    if schema is None:
        schema = getattr(tool, "parameters", None)
    schema_payload = _json_safe(schema)
    schema_encoded = json.dumps(schema_payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "name": getattr(tool, "name", None),
        "description": getattr(tool, "description", None),
        "parameters": schema_payload,
        "schema_bytes": _utf8_size(schema_encoded),
    }


def _build_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    agent = payload.get("agent")
    route = payload.get("route")
    runner_result = agent.get("runner_result", {}) if isinstance(agent, Mapping) else {}
    return {
        "question": request.get("message") if isinstance(request, Mapping) else None,
        "model": agent.get("model") if isinstance(agent, Mapping) else None,
        "model_source": agent.get("model_source") if isinstance(agent, Mapping) else None,
        "outcome": route.get("outcome") if isinstance(route, Mapping) else None,
        "tokens": runner_result.get("usage_breakdown")
        if isinstance(runner_result, Mapping)
        else None,
        "estimated_cost": runner_result.get("cost_estimate")
        if isinstance(runner_result, Mapping)
        else None,
        "timings_ms": payload.get("timings_ms", {}),
        "tool_call_count": len(payload.get("tool_calls", [])),
    }


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _json_safe(value: Any, *, _depth: int = 0, _seen: set[int] | None = None) -> Any:
    """Convert SDK and Pydantic values without letting trace capture fail a request."""
    if _depth > _MAX_SERIALIZATION_DEPTH:
        return "<max_serialization_depth>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value, _depth=_depth + 1, _seen=_seen)

    seen = _seen if _seen is not None else set()
    value_id = id(value)
    if value_id in seen:
        return "<cycle>"
    seen.add(value_id)
    try:
        if hasattr(value, "model_dump"):
            return _json_safe(value.model_dump(mode="json"), _depth=_depth + 1, _seen=seen)
        if is_dataclass(value) and not isinstance(value, type):
            return _json_safe(asdict(value), _depth=_depth + 1, _seen=seen)
        if isinstance(value, Mapping):
            return {
                str(key): _json_safe(item, _depth=_depth + 1, _seen=seen)
                for key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [_json_safe(item, _depth=_depth + 1, _seen=seen) for item in value]
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return _json_safe(to_dict(), _depth=_depth + 1, _seen=seen)
        if hasattr(value, "__dict__"):
            return _json_safe(vars(value), _depth=_depth + 1, _seen=seen)
        return repr(value)
    except Exception as exc:  # pragma: no cover - defensive local diagnostics only
        return f"<unserializable {type(value).__name__}: {type(exc).__name__}>"
    finally:
        seen.discard(value_id)
