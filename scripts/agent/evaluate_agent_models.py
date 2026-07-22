"""Evaluate the current local OpenAI action Agent across fixed scenarios.

The runner intentionally uses the existing local-only raw trace mechanism.
It does not change prompts, tool schemas, models in .env, or any Agent
behavior.  A model is selected per request only through the local trace-only
``X-Agent-Local-Model`` header.

Raw request/response values remain in apps/backend/.local/agent-traces.  The
generated CSV and Markdown reports contain only metric and validation summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import json
import math
import os
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = REPO_ROOT / "docs" / "agent-evals" / "fixtures" / "single-agent-baseline-v1.json"
DEFAULT_TRACE_ROOT = REPO_ROOT / "apps" / "backend" / ".local" / "agent-traces"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "docs" / "agent-evals" / "results"
SUPPORTED_CONTEXT_MODES = {"home", "search_results", "product_detail", "similar_result", "cart"}
SUPPORTED_AUTH_MODES = {"guest", "authenticated"}


@dataclass(frozen=True)
class HttpJsonResponse:
    status_code: int | None
    body: Any
    headers: Mapping[str, str]
    elapsed_ms: float
    error: str | None = None


class JsonHttpClient:
    """Cookie-preserving JSON client built only from Python's standard library."""

    def __init__(self, *, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.cookie_jar = http.cookiejar.CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self.cookie_jar))

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpJsonResponse:
        request_headers = {
            "Accept": "application/json",
            **dict(headers or {}),
        }
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(url, data=data, headers=request_headers, method=method.upper())
        started_at = time.perf_counter()
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
                return HttpJsonResponse(
                    status_code=response.status,
                    body=_decode_json_or_text(raw_body),
                    headers={str(key): str(value) for key, value in response.headers.items()},
                    elapsed_ms=_elapsed_ms(started_at),
                )
        except HTTPError as error:
            raw_body = error.read().decode("utf-8", errors="replace")
            return HttpJsonResponse(
                status_code=error.code,
                body=_decode_json_or_text(raw_body),
                headers={str(key): str(value) for key, value in error.headers.items()},
                elapsed_ms=_elapsed_ms(started_at),
                error=f"HTTP {error.code}",
            )
        except URLError as error:
            return HttpJsonResponse(
                status_code=None,
                body=None,
                headers={},
                elapsed_ms=_elapsed_ms(started_at),
                error=f"network_error: {error.reason}",
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fixed local Agent scenarios against one or more OpenAI models."
    )
    parser.add_argument("--base-url", default="http://localhost:8000/api")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--models",
        nargs="+",
        default=["gpt-5.5", "gpt-5.4-nano-2026-03-17"],
        help="Models sent through the local-only X-Agent-Local-Model header.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--trace-root", type=Path, default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--trace-wait-seconds", type=float, default=5.0)
    parser.add_argument(
        "--allow-missing-trace",
        action="store_true",
        help="Continue when a local trace is missing. Intended only for trace troubleshooting.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--guest-min-interval-seconds", type=float, default=3.1)
    parser.add_argument("--auth-min-interval-seconds", type=float, default=2.1)
    parser.add_argument("--auth-email", default=os.environ.get("AGENT_EVAL_USER_EMAIL"))
    parser.add_argument("--auth-password", default=os.environ.get("AGENT_EVAL_USER_PASSWORD"))
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--allow-write-previews",
        action="store_true",
        help="Include safe preview-only checkout/wishlist cases. The runner never confirms them.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    return parser.parse_args(argv)


def load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Fixture must be an object: {path}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Fixture must contain a non-empty cases array.")
    seen_ids: set[str] = set()
    for case in cases:
        validate_case(case, seen_ids)
    return payload


def validate_case(case: Any, seen_ids: set[str] | None = None) -> None:
    if not isinstance(case, dict):
        raise ValueError("Each fixture case must be an object.")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("Each fixture case requires a non-empty id.")
    if seen_ids is not None:
        if case_id in seen_ids:
            raise ValueError(f"Duplicate fixture case id: {case_id}")
        seen_ids.add(case_id)
    if not isinstance(case.get("message"), str) or not case["message"].strip():
        raise ValueError(f"Fixture case {case_id} requires a message.")
    if case.get("auth_mode") not in SUPPORTED_AUTH_MODES:
        raise ValueError(f"Fixture case {case_id} has unsupported auth_mode.")
    if case.get("context_mode") not in SUPPORTED_CONTEXT_MODES:
        raise ValueError(f"Fixture case {case_id} has unsupported context_mode.")
    if not isinstance(case.get("expect"), dict):
        raise ValueError(f"Fixture case {case_id} requires an expect object.")


def build_execution_plan(
    cases: Iterable[Mapping[str, Any]],
    models: list[str],
    repeat: int,
) -> list[dict[str, Any]]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    normalized_models = [model.strip() for model in models if model.strip()]
    if not normalized_models:
        raise ValueError("At least one non-empty model is required.")
    plan: list[dict[str, Any]] = []
    cases_list = list(cases)
    for repeat_index in range(1, repeat + 1):
        for case_index, case in enumerate(cases_list):
            ordered_models = (
                normalized_models
                if (repeat_index + case_index) % 2
                else list(reversed(normalized_models))
            )
            for model in ordered_models:
                plan.append(
                    {
                        "case_id": str(case["id"]),
                        "model": model,
                        "repeat": repeat_index,
                    }
                )
    return plan


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = load_fixture(args.cases)
    cases = _select_cases(fixture["cases"], args.only)
    if args.list_cases:
        for case in cases:
            print(f"{case['id']}\t{case['group']}\t{case['auth_mode']}\t{case['message']}")
        return 0
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1.")
    if args.timeout_seconds <= 0 or args.trace_wait_seconds < 0:
        raise SystemExit("Timeout values must be non-negative, and request timeout must be positive.")

    run_id = args.run_id or _default_run_id(fixture["name"])
    output_dir = args.output or DEFAULT_RESULTS_ROOT / run_id
    plan = build_execution_plan(cases, args.models, args.repeat)
    skipped_write_preview_count = sum(
        1
        for item in plan
        if _case_by_id(cases, item["case_id"]).get("requires_write_preview")
        and not args.allow_write_previews
    )
    print(f"run_id={run_id}")
    print(f"case_count={len(cases)}")
    print(f"planned_samples={len(plan)}")
    print(f"skipped_write_preview_samples={skipped_write_preview_count}")
    print(f"output={output_dir}")
    if args.dry_run:
        _print_dry_run(plan, cases, args)
        return 0

    if output_dir.exists() and not args.resume:
        raise SystemExit(f"Output already exists; choose a new --run-id or use --resume: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_rows = _load_existing_rows(output_dir / "samples.jsonl") if args.resume else []
    if args.retry_failed:
        existing_rows = [
            row for row in existing_rows if row.get("validation_status") != "failed"
        ]
        _rewrite_jsonl(output_dir / "samples.jsonl", existing_rows)
    completed_keys = _completed_sample_keys(existing_rows, retry_failed=args.retry_failed)
    cases_by_id = {str(case["id"]): case for case in cases}
    fixture_sha256 = _sha256_file(args.cases)
    manifest = _initial_manifest(
        run_id=run_id,
        fixture=fixture,
        fixture_path=args.cases,
        fixture_sha256=fixture_sha256,
        args=args,
        planned_samples=len(plan),
    )
    _write_json(output_dir / "manifest.json", manifest)

    clients = {
        "guest": JsonHttpClient(timeout_seconds=args.timeout_seconds),
        "authenticated": JsonHttpClient(timeout_seconds=args.timeout_seconds),
    }
    api_base_url = args.base_url.rstrip("/")
    health = _health_check(clients["guest"], api_base_url)
    manifest["health_check"] = _http_summary(health)
    if health.status_code not in {200, 204}:
        _write_json(output_dir / "manifest.json", manifest)
        raise SystemExit(
            f"Local backend health check failed ({health.status_code}): {health.error or health.body}"
        )

    active_cases = [
        case
        for case in cases
        if args.allow_write_previews or not case.get("requires_write_preview")
    ]
    requires_auth = any(case["auth_mode"] == "authenticated" for case in active_cases)
    if requires_auth:
        _login_authenticated_client(clients["authenticated"], api_base_url, args)
    bootstrap_by_auth = _bootstrap_contexts(
        clients=clients,
        api_base_url=api_base_url,
        bootstrap_request=fixture.get("bootstrap_request", {}),
        auth_modes={str(case["auth_mode"]) for case in active_cases},
    )
    manifest["bootstrap"] = {
        auth_mode: context["summary"] for auth_mode, context in bootstrap_by_auth.items()
    }
    _write_json(output_dir / "manifest.json", manifest)

    last_request_started_at: dict[str, float] = {}
    all_rows = list(existing_rows)
    jsonl_path = output_dir / "samples.jsonl"
    for position, plan_item in enumerate(plan, start=1):
        case = cases_by_id[plan_item["case_id"]]
        sample_key = _sample_key(plan_item["case_id"], plan_item["model"], plan_item["repeat"])
        if sample_key in completed_keys:
            print(f"[{position}/{len(plan)}] resume_skip={sample_key}")
            continue
        if case.get("requires_write_preview") and not args.allow_write_previews:
            row = _skipped_preview_row(case, plan_item, sample_key)
            _append_jsonl(jsonl_path, row)
            all_rows.append(row)
            print(f"[{position}/{len(plan)}] skipped_write_preview={sample_key}")
            continue

        auth_mode = str(case["auth_mode"])
        _wait_for_actor_interval(
            last_request_started_at,
            auth_mode,
            guest_min_interval=args.guest_min_interval_seconds,
            auth_min_interval=args.auth_min_interval_seconds,
        )
        last_request_started_at[auth_mode] = time.monotonic()
        row = _run_sample(
            case=case,
            plan_item=plan_item,
            sample_key=sample_key,
            client=clients[auth_mode],
            api_base_url=api_base_url,
            bootstrap=bootstrap_by_auth[auth_mode],
            trace_root=args.trace_root,
            trace_wait_seconds=args.trace_wait_seconds,
        )
        _append_jsonl(jsonl_path, row)
        all_rows.append(row)
        print(_progress_line(position, len(plan), row))
        if _missing_trace_is_fatal(row, allow_missing_trace=args.allow_missing_trace):
            _write_reports(output_dir=output_dir, rows=all_rows, manifest=manifest)
            raise SystemExit(
                "Local Agent trace was not captured. Verify APP_ENV=local, "
                "OPENAI_AGENT_LOCAL_TRACE_ENABLED=true, and --trace-root before retrying."
            )

    _write_reports(output_dir=output_dir, rows=all_rows, manifest=manifest)
    print(f"samples={output_dir / 'scenario-results.csv'}")
    print(f"summary={output_dir / 'model-summary.csv'}")
    print(f"report={output_dir / 'report.md'}")
    return 0


def _select_cases(cases: list[dict[str, Any]], only_ids: list[str]) -> list[dict[str, Any]]:
    if not only_ids:
        return list(cases)
    wanted = set(only_ids)
    available = {str(case["id"]) for case in cases}
    unknown = sorted(wanted - available)
    if unknown:
        raise SystemExit(f"Unknown --only case ids: {', '.join(unknown)}")
    return [case for case in cases if str(case["id"]) in wanted]


def _case_by_id(cases: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    for case in cases:
        if case["id"] == case_id:
            return case
    raise KeyError(case_id)


def _default_run_id(fixture_name: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{fixture_name}-{timestamp}"


def _initial_manifest(
    *,
    run_id: str,
    fixture: Mapping[str, Any],
    fixture_path: Path,
    fixture_sha256: str,
    args: argparse.Namespace,
    planned_samples: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "fixture": {
            "name": fixture.get("name"),
            "version": fixture.get("version"),
            "path": _display_path(fixture_path),
            "sha256": fixture_sha256,
        },
        "configuration": {
            "base_url": args.base_url.rstrip("/"),
            "models": list(args.models),
            "repeat": args.repeat,
            "planned_samples": planned_samples,
            "trace_root": _display_path(args.trace_root),
            "allow_missing_trace": args.allow_missing_trace,
            "allow_write_previews": args.allow_write_previews,
            "guest_min_interval_seconds": args.guest_min_interval_seconds,
            "auth_min_interval_seconds": args.auth_min_interval_seconds,
        },
        "safety": {
            "raw_trace_copied_to_results": False,
            "confirmation_endpoint_called": False,
            "credentials_written": False,
        },
    }


def _health_check(client: JsonHttpClient, api_base_url: str) -> HttpJsonResponse:
    return client.request("GET", _api_url(api_base_url, "/health"))


def _login_authenticated_client(
    client: JsonHttpClient,
    api_base_url: str,
    args: argparse.Namespace,
) -> None:
    if not args.auth_email or not args.auth_password:
        raise SystemExit(
            "Authenticated cases need --auth-email/--auth-password or "
            "AGENT_EVAL_USER_EMAIL/AGENT_EVAL_USER_PASSWORD."
        )
    response = client.request(
        "POST",
        _api_url(api_base_url, "/auth/login"),
        payload={"email": args.auth_email, "password": args.auth_password},
    )
    if response.status_code != 200:
        raise SystemExit(f"Test-user login failed ({response.status_code}): {_safe_error_message(response.body)}")


def _bootstrap_contexts(
    *,
    clients: Mapping[str, JsonHttpClient],
    api_base_url: str,
    bootstrap_request: Any,
    auth_modes: set[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(bootstrap_request, dict):
        raise SystemExit("Fixture bootstrap_request must be an object.")
    contexts: dict[str, dict[str, Any]] = {}
    for auth_mode in sorted(auth_modes):
        response = clients[auth_mode].request(
            "POST",
            _api_url(api_base_url, "/recommendations?page=1&page_size=10"),
            payload=bootstrap_request,
        )
        if response.status_code != 200 or not isinstance(response.body, dict):
            raise SystemExit(
                f"Bootstrap recommendation failed for {auth_mode} ({response.status_code}): "
                f"{_safe_error_message(response.body)}"
            )
        products = response.body.get("products")
        if not isinstance(products, list) or len(products) < 2:
            raise SystemExit(
                f"Bootstrap recommendation needs at least two products for {auth_mode}."
            )
        product_items = [
            {
                "id": str(product.get("product_id")),
                "title": str(product.get("name") or product.get("product_id")),
            }
            for product in products
            if isinstance(product, dict) and product.get("product_id")
        ]
        if len(product_items) < 2:
            raise SystemExit(f"Bootstrap recommendation returned invalid product IDs for {auth_mode}.")
        contexts[auth_mode] = {
            "recommendation_id": str(response.body.get("recommendation_id") or ""),
            "product_items": product_items,
            "summary": {
                "status_code": response.status_code,
                "elapsed_ms": round(response.elapsed_ms, 2),
                "product_count": len(product_items),
                "recommendation_id_present": bool(response.body.get("recommendation_id")),
            },
        }
    return contexts


def _run_sample(
    *,
    case: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    sample_key: str,
    client: JsonHttpClient,
    api_base_url: str,
    bootstrap: Mapping[str, Any],
    trace_root: Path,
    trace_wait_seconds: float,
) -> dict[str, Any]:
    conversation_id = f"agent-eval-{sample_key}-{uuid.uuid4().hex[:8]}"
    payload = {
        "message": case["message"],
        "conversation_id": conversation_id,
        **_build_case_context(case, bootstrap),
    }
    response = client.request(
        "POST",
        _api_url(api_base_url, "/agent/chat"),
        payload=payload,
        headers={
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Agent-Local-Model": str(plan_item["model"]),
        },
    )
    trace_id = _header_value(response.headers, "X-Agent-Local-Trace-Id")
    trace_path = _wait_for_trace(trace_root, trace_id, trace_wait_seconds) if trace_id else None
    trace = _load_trace(trace_path)
    metrics = extract_trace_metrics(trace)
    response_body = response.body if isinstance(response.body, dict) else {}
    validation = evaluate_case_response(case, response=response_body, trace=trace, status_code=response.status_code)
    error_code = _response_error_code(response_body)
    return {
        "sample_key": sample_key,
        "scenario_id": case["id"],
        "group": case.get("group", "ungrouped"),
        "auth_mode": case["auth_mode"],
        "context_mode": case["context_mode"],
        "requested_model": plan_item["model"],
        "repeat": plan_item["repeat"],
        "http_status": response.status_code,
        "client_roundtrip_ms": round(response.elapsed_ms, 2),
        "http_error": response.error,
        "error_code": error_code,
        "trace_id": trace_id,
        "trace_file": _display_path(trace_path) if trace_path else None,
        "trace_available": trace is not None,
        "actual_model": metrics["actual_model"],
        "model_source": metrics["model_source"],
        "model_called": metrics["model_called"],
        "short_circuit_reason": metrics["short_circuit_reason"],
        "tool_name": response_body.get("tool_name"),
        "tool_call_count": metrics["tool_call_count"],
        "requires_confirmation": response_body.get("requires_confirmation"),
        "ui_action_type": _nested_value(response_body, "ui_action", "type"),
        "ui_action_target": _nested_value(response_body, "ui_action", "target"),
        "item_count": len(response_body.get("items", [])) if isinstance(response_body.get("items"), list) else 0,
        "validation_status": validation["status"],
        "structural_pass": validation["structural_pass"],
        "constraint_pass": validation["constraint_pass"],
        "validation_errors": validation["errors"],
        "manual_review_required": bool(case.get("expect", {}).get("manual_review")),
        **metrics,
    }


def _build_case_context(case: Mapping[str, Any], bootstrap: Mapping[str, Any]) -> dict[str, Any]:
    product_items = list(bootstrap["product_items"])
    product_ids = [item["id"] for item in product_items]
    recommendation_id = str(bootstrap["recommendation_id"])
    context_mode = str(case["context_mode"])
    if context_mode == "home":
        return {"context": {"page": "home", "route": "/"}}
    if context_mode == "search_results":
        return {
            "context": {
                "page": "search_results",
                "route": "/search",
                "recommendation_id": recommendation_id,
                "visible_product_ids": product_ids[:10],
                "filters": {"page_size": 10, "skin_type": "수부지", "sensitivity": "보통"},
            }
        }
    if context_mode == "product_detail":
        return {
            "context": {
                "page": "product_detail",
                "route": f"/product-detail?id={product_ids[0]}",
                "recommendation_id": recommendation_id,
                "current_product_id": product_ids[0],
                "visible_product_ids": product_ids[:2],
            }
        }
    if context_mode == "similar_result":
        return {
            "context": {
                "page": "product_detail",
                "route": f"/product-detail?id={product_ids[0]}",
                "recommendation_id": recommendation_id,
                "current_product_id": product_ids[0],
                "visible_product_ids": product_ids[:2],
            },
            "last_tool_result": {
                "action_type": "show_products",
                "target": "similar_products",
                "items": [
                    {"item_type": "product", "id": item["id"], "title": item["title"]}
                    for item in product_items[:2]
                ],
            },
        }
    if context_mode == "cart":
        return {"context": {"page": "cart", "route": "/cart"}}
    raise ValueError(f"Unsupported context mode: {context_mode}")


def evaluate_case_response(
    case: Mapping[str, Any],
    *,
    response: Mapping[str, Any],
    trace: Mapping[str, Any] | None,
    status_code: int | None,
) -> dict[str, Any]:
    expect = case["expect"]
    structural_errors: list[str] = []
    constraint_errors: list[str] = []
    if status_code != 200:
        structural_errors.append(f"expected HTTP 200, got {status_code}")
    expected_tool = expect.get("tool_name")
    actual_tool = response.get("tool_name")
    if expected_tool and actual_tool != expected_tool:
        structural_errors.append(f"tool_name expected={expected_tool}, actual={actual_tool}")
    if "requires_confirmation" in expect and response.get("requires_confirmation") != expect["requires_confirmation"]:
        structural_errors.append(
            "requires_confirmation "
            f"expected={expect['requires_confirmation']}, actual={response.get('requires_confirmation')}"
        )
    expected_ui_type = expect.get("ui_action_type")
    actual_ui_type = _nested_value(response, "ui_action", "type")
    if expected_ui_type and actual_ui_type != expected_ui_type:
        structural_errors.append(f"ui_action.type expected={expected_ui_type}, actual={actual_ui_type}")
    expected_ui_target = expect.get("ui_action_target")
    actual_ui_target = _nested_value(response, "ui_action", "target")
    if expected_ui_target and actual_ui_target != expected_ui_target:
        structural_errors.append(
            f"ui_action.target expected={expected_ui_target}, actual={actual_ui_target}"
        )
    minimum_items = expect.get("min_items")
    actual_items = response.get("items")
    if minimum_items is not None and (not isinstance(actual_items, list) or len(actual_items) < minimum_items):
        structural_errors.append(f"item_count expected>={minimum_items}, actual={len(actual_items or [])}")

    arguments = _tool_arguments(trace, expected_tool) or _response_tool_arguments(
        response,
        expected_tool,
    )
    for field, expected_value in dict(expect.get("argument_equals", {})).items():
        actual_value = arguments.get(field)
        if actual_value != expected_value:
            constraint_errors.append(f"{field} expected={expected_value!r}, actual={actual_value!r}")
    for field, expected_values in dict(expect.get("argument_includes", {})).items():
        actual_values = arguments.get(field)
        if not isinstance(actual_values, list) or not set(expected_values).issubset(set(actual_values)):
            constraint_errors.append(f"{field} must include {expected_values!r}, actual={actual_values!r}")

    structural_pass = not structural_errors
    constraint_pass = not constraint_errors
    if not structural_pass or not constraint_pass:
        status = "failed"
    elif expect.get("manual_review"):
        status = "needs_manual_review"
    else:
        status = "passed"
    return {
        "status": status,
        "structural_pass": structural_pass,
        "constraint_pass": constraint_pass,
        "errors": " | ".join([*structural_errors, *constraint_errors]),
    }


def extract_trace_metrics(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "actual_model": None,
        "model_source": None,
        "model_called": None,
        "short_circuit_reason": None,
        "instructions_bytes": None,
        "selected_tool_count": None,
        "selected_tool_schema_bytes": None,
        "agent_input_bytes": None,
        "route_total_ms": None,
        "agent_workflow_ms": None,
        "agent_runner_ms": None,
        "agent_model_and_orchestration_ms": None,
        "agent_tool_execution_ms": None,
        "agent_tool_reference_resolve_ms": None,
        "agent_tool_dispatch_ms": None,
        "agent_tool_response_serialize_ms": None,
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "cost_estimate_status": None,
        "tool_call_count": 0,
    }
    if not isinstance(trace, Mapping):
        return metrics
    agent = trace.get("agent") if isinstance(trace.get("agent"), Mapping) else {}
    route = trace.get("route") if isinstance(trace.get("route"), Mapping) else {}
    timing = trace.get("timings_ms") if isinstance(trace.get("timings_ms"), Mapping) else {}
    runner_result = agent.get("runner_result") if isinstance(agent.get("runner_result"), Mapping) else {}
    usage = runner_result.get("usage_breakdown") or runner_result.get("usage")
    cost = runner_result.get("cost_estimate")
    metrics.update(
        {
            "actual_model": agent.get("model"),
            "model_source": agent.get("model_source")
            or ("not_called" if not agent and route.get("outcome") == "succeeded" else None),
            "model_called": bool(agent.get("model")),
            "short_circuit_reason": agent.get("short_circuit_reason"),
            "instructions_bytes": agent.get("instructions_bytes"),
            "selected_tool_count": agent.get("selected_tool_count"),
            "selected_tool_schema_bytes": agent.get("selected_tool_schema_bytes"),
            "agent_input_bytes": agent.get("input_bytes"),
            "route_total_ms": timing.get("route_total_ms"),
            "agent_workflow_ms": timing.get("agent_workflow_ms"),
            "agent_runner_ms": timing.get("agent_runner_ms"),
            "agent_model_and_orchestration_ms": timing.get("agent_model_and_orchestration_ms"),
            "agent_tool_execution_ms": timing.get("tool_execution_ms"),
            "agent_tool_reference_resolve_ms": timing.get("tool_reference_resolve_ms"),
            "agent_tool_dispatch_ms": timing.get("tool_dispatch_ms"),
            "agent_tool_response_serialize_ms": timing.get("tool_response_serialize_ms"),
            "tool_call_count": len(trace.get("tool_calls", [])) if isinstance(trace.get("tool_calls"), list) else 0,
        }
    )
    if isinstance(usage, Mapping):
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
            metrics[key] = usage.get(key)
    if isinstance(cost, Mapping):
        metrics["estimated_cost_usd"] = cost.get("estimated_cost_usd")
        metrics["cost_estimate_status"] = cost.get("estimate_status")
    return metrics


def _tool_arguments(trace: Mapping[str, Any] | None, expected_tool_name: Any) -> dict[str, Any]:
    if not isinstance(trace, Mapping):
        return {}
    tool_calls = trace.get("tool_calls")
    if not isinstance(tool_calls, list):
        return {}
    for tool_call in reversed(tool_calls):
        if not isinstance(tool_call, Mapping):
            continue
        if expected_tool_name and tool_call.get("tool_name") != expected_tool_name:
            continue
        arguments = tool_call.get("resolved_arguments") or tool_call.get("model_arguments")
        if isinstance(arguments, Mapping):
            return dict(arguments)
    return {}


def _response_tool_arguments(
    response: Mapping[str, Any],
    expected_tool_name: Any,
) -> dict[str, Any]:
    """Read server-resolved filters for deterministic paths without an LLM tool call."""
    if expected_tool_name != "refine_product_results":
        return {}
    if response.get("tool_name") != expected_tool_name:
        return {}
    ui_action = response.get("ui_action")
    if not isinstance(ui_action, Mapping):
        return {}
    payload = ui_action.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    filters = payload.get("filters")
    return dict(filters) if isinstance(filters, Mapping) else {}


def _wait_for_trace(trace_root: Path, trace_id: str | None, wait_seconds: float) -> Path | None:
    if not trace_id:
        return None
    deadline = time.monotonic() + wait_seconds
    while True:
        matches = sorted(trace_root.glob(f"agent-*-{trace_id}.json"))
        if matches:
            return matches[-1]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)


def _load_trace(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _wait_for_actor_interval(
    last_request_started_at: dict[str, float],
    actor_type: str,
    *,
    guest_min_interval: float,
    auth_min_interval: float,
) -> None:
    interval = guest_min_interval if actor_type == "guest" else auth_min_interval
    previous = last_request_started_at.get(actor_type)
    if previous is None or interval <= 0:
        return
    remaining = interval - (time.monotonic() - previous)
    if remaining > 0:
        time.sleep(remaining)


def _skipped_preview_row(
    case: Mapping[str, Any],
    plan_item: Mapping[str, Any],
    sample_key: str,
) -> dict[str, Any]:
    return {
        "sample_key": sample_key,
        "scenario_id": case["id"],
        "group": case.get("group", "ungrouped"),
        "auth_mode": case["auth_mode"],
        "context_mode": case["context_mode"],
        "requested_model": plan_item["model"],
        "repeat": plan_item["repeat"],
        "http_status": None,
        "validation_status": "skipped_write_preview",
        "structural_pass": None,
        "constraint_pass": None,
        "validation_errors": "Requires --allow-write-previews; confirmation endpoint is never called.",
    }


def _missing_trace_is_fatal(
    row: Mapping[str, Any],
    *,
    allow_missing_trace: bool,
) -> bool:
    if allow_missing_trace or row.get("trace_available"):
        return False

    status_code = row.get("http_status")
    return isinstance(status_code, int) and 200 <= status_code < 300


def _write_reports(*, output_dir: Path, rows: list[dict[str, Any]], manifest: Mapping[str, Any]) -> None:
    scenario_rows = [_flatten_for_csv(row) for row in rows]
    _write_csv(output_dir / "scenario-results.csv", scenario_rows, SCENARIO_CSV_FIELDS)
    summary_rows = summarize_rows(rows)
    _write_csv(output_dir / "model-summary.csv", summary_rows, SUMMARY_CSV_FIELDS)
    manual_rows = [
        {
            "sample_key": row.get("sample_key"),
            "scenario_id": row.get("scenario_id"),
            "requested_model": row.get("requested_model"),
            "repeat": row.get("repeat"),
            "validation_status": row.get("validation_status"),
            "tool_name": row.get("tool_name"),
            "trace_file": row.get("trace_file"),
            "reviewer_result": "",
            "reviewer_notes": "",
        }
        for row in rows
        if row.get("manual_review_required")
    ]
    _write_csv(
        output_dir / "manual-review.csv",
        manual_rows,
        ["sample_key", "scenario_id", "requested_model", "repeat", "validation_status", "tool_name", "trace_file", "reviewer_result", "reviewer_notes"],
    )
    (output_dir / "report.md").write_text(
        render_report(rows=rows, summaries=summary_rows, manifest=manifest),
        encoding="utf-8",
    )


SCENARIO_CSV_FIELDS = [
    "sample_key", "scenario_id", "group", "auth_mode", "context_mode", "requested_model", "repeat",
    "http_status", "client_roundtrip_ms", "http_error", "error_code", "trace_id", "trace_file", "trace_available",
    "actual_model", "model_source", "model_called", "short_circuit_reason", "tool_name", "tool_call_count",
    "requires_confirmation", "ui_action_type", "ui_action_target", "item_count", "validation_status",
    "structural_pass", "constraint_pass", "validation_errors", "manual_review_required", "instructions_bytes",
    "selected_tool_count", "selected_tool_schema_bytes", "agent_input_bytes", "route_total_ms", "agent_workflow_ms",
    "agent_runner_ms", "agent_model_and_orchestration_ms", "agent_tool_execution_ms",
    "agent_tool_reference_resolve_ms", "agent_tool_dispatch_ms", "agent_tool_response_serialize_ms",
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
    "estimated_cost_usd", "cost_estimate_status",
]

SUMMARY_CSV_FIELDS = [
    "requested_model", "group", "sample_count", "http_success_count", "model_called_count", "short_circuit_count",
    "structural_pass_rate", "constraint_pass_rate", "client_roundtrip_p50_ms", "client_roundtrip_p95_ms",
    "route_total_p50_ms", "route_total_p95_ms", "model_phase_p50_ms", "model_phase_p95_ms",
    "tool_execution_p50_ms", "tool_execution_p95_ms", "mean_input_tokens", "mean_output_tokens",
    "mean_total_tokens", "total_estimated_cost_usd", "mean_estimated_cost_usd",
]


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        model = row.get("requested_model")
        group = row.get("group")
        if model and group and row.get("validation_status") != "skipped_write_preview":
            grouped[(str(model), str(group))].append(row)
    summary: list[dict[str, Any]] = []
    for (model, group), sample_rows in sorted(grouped.items()):
        successful = [row for row in sample_rows if row.get("http_status") == 200]
        model_called = [row for row in successful if row.get("model_called") is True]
        summary.append(
            {
                "requested_model": model,
                "group": group,
                "sample_count": len(sample_rows),
                "http_success_count": len(successful),
                "model_called_count": len(model_called),
                "short_circuit_count": sum(row.get("model_called") is False for row in successful),
                "structural_pass_rate": _rate(successful, "structural_pass"),
                "constraint_pass_rate": _rate(successful, "constraint_pass"),
                "client_roundtrip_p50_ms": _percentile(_numeric(successful, "client_roundtrip_ms"), 50),
                "client_roundtrip_p95_ms": _percentile(_numeric(successful, "client_roundtrip_ms"), 95),
                "route_total_p50_ms": _percentile(_numeric(successful, "route_total_ms"), 50),
                "route_total_p95_ms": _percentile(_numeric(successful, "route_total_ms"), 95),
                "model_phase_p50_ms": _percentile(_numeric(model_called, "agent_model_and_orchestration_ms"), 50),
                "model_phase_p95_ms": _percentile(_numeric(model_called, "agent_model_and_orchestration_ms"), 95),
                "tool_execution_p50_ms": _percentile(_numeric(successful, "agent_tool_execution_ms"), 50),
                "tool_execution_p95_ms": _percentile(_numeric(successful, "agent_tool_execution_ms"), 95),
                "mean_input_tokens": _mean(_numeric(model_called, "input_tokens")),
                "mean_output_tokens": _mean(_numeric(model_called, "output_tokens")),
                "mean_total_tokens": _mean(_numeric(model_called, "total_tokens")),
                "total_estimated_cost_usd": _sum(_numeric(model_called, "estimated_cost_usd")),
                "mean_estimated_cost_usd": _mean(_numeric(model_called, "estimated_cost_usd")),
            }
        )
    return summary


def render_report(
    *,
    rows: list[Mapping[str, Any]],
    summaries: list[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> str:
    completed = [row for row in rows if row.get("validation_status") != "skipped_write_preview"]
    failed = [row for row in completed if row.get("validation_status") == "failed"]
    short_circuits = [row for row in completed if row.get("model_source") == "not_called"]
    lines = [
        f"# Agent 모델 비교: {manifest['run_id']}",
        "",
        "## 실행 범위",
        "",
        f"- 고정 시나리오: {len({row.get('scenario_id') for row in completed})}개",
        f"- 완료 샘플: {len(completed)}개",
        f"- 실패 샘플: {len(failed)}개",
        f"- 모델 미호출 fast path: {len(short_circuits)}개",
        f"- 모델: {', '.join(manifest['configuration']['models'])}",
        f"- 반복: 시나리오·모델 조합당 {manifest['configuration']['repeat']}회",
        "",
        "## 모델 요약",
        "",
        "| 모델 | 그룹 | HTTP 성공 | 모델 호출 | p50/p95 응답(ms) | p50/p95 모델 단계(ms) | 평균 토큰 | 추정 비용(USD) | 구조 검증 | 제약 검증 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            "| {requested_model} | {group} | {http_success_count}/{sample_count} | "
            "{model_called_count} | {client_roundtrip_p50_ms}/{client_roundtrip_p95_ms} | "
            "{model_phase_p50_ms}/{model_phase_p95_ms} | {mean_total_tokens} | "
            "{total_estimated_cost_usd} | {structural_pass_rate} | {constraint_pass_rate} |".format(**summary)
        )
    lines.extend(
        [
            "",
            "## 해석 규칙",
            "",
            "- `agent_model_and_orchestration_ms`는 모델 호출이 실제 발생한 샘플만 집계한다.",
            "- deterministic fast path는 `model_source=not_called`로 별도 집계한다. 모델 성능 평균과 섞지 않는다.",
            "- 추정 비용은 로컬 토큰 단가표 기반이며 OpenAI Usage 청구 총액과 다를 수 있다.",
            "- `manual-review.csv`에서 추천 품질과 자연어 해석 품질을 별도 판정한다.",
            "- 전체 raw request/response와 tool arguments는 결과 폴더가 아니라 로컬 Agent trace 파일에만 보관한다.",
            "",
            "## 산출물",
            "",
            "- `scenario-results.csv`: 샘플별 시간·토큰·도구·검증 결과",
            "- `model-summary.csv`: 모델/그룹별 그래프용 집계",
            "- `manual-review.csv`: 사람이 품질 판정을 덧붙일 표",
            "- `samples.jsonl`: 재개 가능한 샘플 원장",
        ]
    )
    if failed:
        lines.extend(["", "## 실패 샘플", ""])
        for row in failed:
            lines.append(
                f"- `{row.get('sample_key')}`: {row.get('validation_errors') or row.get('error_code') or row.get('http_error')}"
            )
    return "\n".join(lines) + "\n"


def _flatten_for_csv(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in SCENARIO_CSV_FIELDS}


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _rewrite_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"Invalid JSONL at {path}:{line_number}: {error}") from error
        if isinstance(decoded, dict):
            rows.append(decoded)
    return rows


def _completed_sample_keys(rows: Iterable[Mapping[str, Any]], *, retry_failed: bool) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        key = row.get("sample_key")
        if not isinstance(key, str):
            continue
        if retry_failed and row.get("validation_status") == "failed":
            continue
        keys.add(key)
    return keys


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _http_summary(response: HttpJsonResponse) -> dict[str, Any]:
    return {"status_code": response.status_code, "elapsed_ms": round(response.elapsed_ms, 2), "error": response.error}


def _api_url(api_base_url: str, path: str) -> str:
    return f"{api_base_url.rstrip('/')}/{path.lstrip('/')}"


def _decode_json_or_text(raw_body: str) -> Any:
    if not raw_body:
        return None
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


def _elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return None


def _response_error_code(response: Mapping[str, Any]) -> str | None:
    error = response.get("error")
    return error.get("code") if isinstance(error, Mapping) else None


def _nested_value(payload: Mapping[str, Any], parent: str, child: str) -> Any:
    value = payload.get(parent)
    return value.get(child) if isinstance(value, Mapping) else None


def _safe_error_message(body: Any) -> str:
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            return str(error.get("code") or error.get("message") or "unknown_error")
    return "unexpected_response"


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric(rows: Iterable[Mapping[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(float(value))
    return values


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _sum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values), 8)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * percentile / 100) - 1)
    return round(sorted(values)[index], 2)


def _rate(rows: Iterable[Mapping[str, Any]], field: str) -> float | None:
    rows_list = list(rows)
    if not rows_list:
        return None
    return round(sum(row.get(field) is True for row in rows_list) / len(rows_list) * 100, 1)


def _sample_key(case_id: str, model: str, repeat: int) -> str:
    sanitized_model = "".join(character if character.isalnum() else "-" for character in model).strip("-")
    return f"{case_id}__{sanitized_model}__r{repeat:02d}"


def _progress_line(position: int, total: int, row: Mapping[str, Any]) -> str:
    return (
        f"[{position}/{total}] {row['scenario_id']} model={row['requested_model']} "
        f"http={row.get('http_status')} route_ms={row.get('route_total_ms')} "
        f"model_ms={row.get('agent_model_and_orchestration_ms')} "
        f"validation={row.get('validation_status')}"
    )


def _print_dry_run(plan: list[Mapping[str, Any]], cases: list[Mapping[str, Any]], args: argparse.Namespace) -> None:
    cases_by_id = {str(case["id"]): case for case in cases}
    for position, item in enumerate(plan, start=1):
        case = cases_by_id[str(item["case_id"])]
        suffix = " [requires --allow-write-previews]" if case.get("requires_write_preview") else ""
        print(
            f"[{position}/{len(plan)}] case={item['case_id']} model={item['model']} "
            f"repeat={item['repeat']} auth={case['auth_mode']} context={case['context_mode']}{suffix}"
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Agent evaluation interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
