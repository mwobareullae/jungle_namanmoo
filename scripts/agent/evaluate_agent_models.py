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
ROUTER_SPECIALIST_CASES_PATH = (
    REPO_ROOT / "docs" / "agent-evals" / "fixtures" / "router-specialist-v1.json"
)
DEFAULT_TRACE_ROOT = REPO_ROOT / "apps" / "backend" / ".local" / "agent-traces"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "docs" / "agent-evals" / "results"
SUPPORTED_CONTEXT_MODES = {
    "home",
    "search_results",
    "product_detail",
    "similar_result",
    "cart",
    "checkout",
}
SUPPORTED_AUTH_MODES = {"guest", "authenticated"}


@dataclass(frozen=True)
class AgentEvaluationProfile:
    """A reproducible local-only Agent execution configuration."""

    profile_id: str
    execution_mode: str
    requested_model: str
    router_model: str | None = None
    specialist_model: str | None = None
    specialist_fallback_enabled: bool | None = None
    specialist_fallback_model: str | None = None

    def request_headers(self) -> dict[str, str]:
        headers = {"X-Agent-Local-Execution-Mode": self.execution_mode}
        if self.execution_mode == "single":
            headers["X-Agent-Local-Model"] = self.requested_model
        if self.router_model:
            headers["X-Agent-Local-Router-Model"] = self.router_model
        if self.specialist_model:
            headers["X-Agent-Local-Specialist-Model"] = self.specialist_model
        if self.specialist_fallback_enabled is not None:
            headers["X-Agent-Local-Specialist-Fallback-Enabled"] = str(
                self.specialist_fallback_enabled
            ).lower()
        if self.specialist_fallback_model:
            headers["X-Agent-Local-Specialist-Fallback-Model"] = (
                self.specialist_fallback_model
            )
        return headers


NAMED_EVALUATION_PROFILES: dict[str, AgentEvaluationProfile] = {
    "single-gpt55": AgentEvaluationProfile(
        profile_id="single-gpt55",
        execution_mode="single",
        requested_model="gpt-5.5",
    ),
    "single-nano": AgentEvaluationProfile(
        profile_id="single-nano",
        execution_mode="single",
        requested_model="gpt-5.4-nano-2026-03-17",
    ),
    "router-nano": AgentEvaluationProfile(
        profile_id="router-nano",
        execution_mode="router_specialist",
        requested_model="gpt-5.4-nano-2026-03-17",
        router_model="gpt-5.4-nano-2026-03-17",
        specialist_model="gpt-5.4-nano-2026-03-17",
        specialist_fallback_enabled=False,
    ),
    "router-nano-fallback": AgentEvaluationProfile(
        profile_id="router-nano-fallback",
        execution_mode="router_specialist",
        requested_model="gpt-5.4-nano-2026-03-17",
        router_model="gpt-5.4-nano-2026-03-17",
        specialist_model="gpt-5.4-nano-2026-03-17",
        specialist_fallback_enabled=True,
        specialist_fallback_model="gpt-5.5",
    ),
}


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
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=[],
        help=(
            "Named execution profiles: single-gpt55, single-nano, router-nano, "
            "router-nano-fallback. Overrides --models for this run."
        ),
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
    parser.add_argument("--list-profiles", action="store_true")
    return parser.parse_args(argv)


def load_fixture(path: Path) -> dict[str, Any]:
    """Load a fixture, optionally extending one sibling fixture's cases."""

    return _load_fixture(path.resolve(), ancestors=())


def _load_fixture(path: Path, *, ancestors: tuple[Path, ...]) -> dict[str, Any]:
    if path in ancestors:
        chain = " -> ".join(str(item) for item in (*ancestors, path))
        raise ValueError(f"Fixture extends cycle: {chain}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Fixture must be an object: {path}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Fixture must contain a non-empty cases array.")
    inherited_payload: dict[str, Any] = {}
    inherited_cases: list[Any] = []
    extends = payload.get("extends")
    if extends is not None:
        if not isinstance(extends, str) or not extends.strip():
            raise ValueError("Fixture extends must be a non-empty relative filename.")
        relative_path = Path(extends)
        if relative_path.is_absolute() or relative_path.parent != Path("."):
            raise ValueError("Fixture extends must reference a sibling fixture filename.")
        base_path = (path.parent / relative_path).resolve()
        inherited_payload = _load_fixture(base_path, ancestors=(*ancestors, path))
        inherited_cases = list(inherited_payload["cases"])
    # A derived fixture changes only the scenario delta by default.  Preserve
    # bootstrap and other execution defaults from the base fixture unless the
    # child explicitly replaces them.
    resolved_payload = {**inherited_payload, **payload}
    resolved_payload["cases"] = [*inherited_cases, *cases]
    seen_ids: set[str] = set()
    for case in resolved_payload["cases"]:
        validate_case(case, seen_ids)
    return resolved_payload


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
    expect = case.get("expect")
    if not isinstance(expect, dict):
        raise ValueError(f"Fixture case {case_id} requires an expect object.")
    for field_name in ("route", "tool_name", "error_code", "validation"):
        value = expect.get(field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"Fixture case {case_id} expect.{field_name} must be a non-empty string.")
    for field_name in ("allow_clarification", "requires_confirmation"):
        value = expect.get(field_name)
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"Fixture case {case_id} expect.{field_name} must be boolean.")
    statuses = expect.get("http_statuses")
    if statuses is not None:
        if not isinstance(statuses, list) or not statuses or not all(isinstance(item, int) for item in statuses):
            raise ValueError(f"Fixture case {case_id} expect.http_statuses must be a non-empty int list.")


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


def build_profile_execution_plan(
    cases: Iterable[Mapping[str, Any]],
    profiles: Iterable[AgentEvaluationProfile],
    repeat: int,
) -> list[dict[str, Any]]:
    """Build a balanced plan while preserving the legacy model-plan helper."""

    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    normalized_profiles = list(profiles)
    if not normalized_profiles:
        raise ValueError("At least one Agent evaluation profile is required.")
    plan: list[dict[str, Any]] = []
    cases_list = list(cases)
    for repeat_index in range(1, repeat + 1):
        for case_index, case in enumerate(cases_list):
            ordered_profiles = (
                normalized_profiles
                if (repeat_index + case_index) % 2
                else list(reversed(normalized_profiles))
            )
            for profile in ordered_profiles:
                plan.append(
                    {
                        "case_id": str(case["id"]),
                        "profile_id": profile.profile_id,
                        "model": profile.requested_model,
                        "execution_mode": profile.execution_mode,
                        "headers": profile.request_headers(),
                        "repeat": repeat_index,
                    }
                )
    return plan


def resolve_evaluation_profiles(
    models: Iterable[str],
    profile_ids: Iterable[str],
) -> list[AgentEvaluationProfile]:
    requested_profile_ids = [profile_id.strip() for profile_id in profile_ids if profile_id.strip()]
    if requested_profile_ids:
        unknown = sorted(set(requested_profile_ids) - set(NAMED_EVALUATION_PROFILES))
        if unknown:
            raise ValueError(f"Unknown Agent evaluation profile(s): {', '.join(unknown)}")
        return [NAMED_EVALUATION_PROFILES[profile_id] for profile_id in requested_profile_ids]

    normalized_models = [model.strip() for model in models if model.strip()]
    if not normalized_models:
        raise ValueError("At least one non-empty model is required.")
    return [
        AgentEvaluationProfile(
            profile_id=f"single-{_profile_id_fragment(model)}",
            execution_mode="single",
            requested_model=model,
        )
        for model in normalized_models
    ]


def _profile_id_fragment(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = load_fixture(args.cases)
    cases = _select_cases(fixture["cases"], args.only)
    try:
        profiles = resolve_evaluation_profiles(args.models, args.profiles)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.list_profiles:
        for profile in NAMED_EVALUATION_PROFILES.values():
            fallback = (
                f", fallback={profile.specialist_fallback_model}"
                if profile.specialist_fallback_enabled
                else ", fallback=off"
            )
            print(
                f"{profile.profile_id}\tmode={profile.execution_mode}\t"
                f"model={profile.requested_model}{fallback}"
            )
        return 0
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
    plan = build_profile_execution_plan(cases, profiles, args.repeat)
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
        profiles=profiles,
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
        sample_key = _sample_key(
            plan_item["case_id"],
            str(plan_item.get("profile_id") or plan_item["model"]),
            plan_item["repeat"],
        )
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
    profiles: Iterable[AgentEvaluationProfile],
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
            "profiles": [
                {
                    "id": profile.profile_id,
                    "execution_mode": profile.execution_mode,
                    "requested_model": profile.requested_model,
                    "router_model": profile.router_model,
                    "specialist_model": profile.specialist_model,
                    "specialist_fallback_enabled": profile.specialist_fallback_enabled,
                    "specialist_fallback_model": profile.specialist_fallback_model,
                }
                for profile in profiles
            ],
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
    request_headers = {
        "Idempotency-Key": str(uuid.uuid4()),
        **dict(plan_item.get("headers", {})),
    }
    if (
        plan_item.get("execution_mode", "single") == "single"
        and not request_headers.get("X-Agent-Local-Model")
        and plan_item.get("model")
    ):
        # Legacy plans created by build_execution_plan still exercise the
        # single-Agent model override path without needing profile metadata.
        request_headers["X-Agent-Local-Model"] = str(plan_item["model"])
    response = client.request(
        "POST",
        _api_url(api_base_url, "/agent/chat"),
        payload=payload,
        headers=request_headers,
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
        "requested_profile": plan_item.get("profile_id"),
        "requested_execution_mode": plan_item.get("execution_mode", "single"),
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
        "route_pass": validation["route_pass"],
        "tool_pass": validation["tool_pass"],
        "safety_pass": validation["safety_pass"],
        "clarification_used": validation["clarification_used"],
        "expected_route": validation["expected_route"],
        "actual_route": validation["actual_route"],
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
    if context_mode == "checkout":
        return {
            "context": {
                "page": "checkout",
                "route": "/checkout",
                "cart_item_ids": [1],
                "current_product_id": product_ids[0],
                "visible_product_ids": product_ids[:2],
            }
        }
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
    safety_errors: list[str] = []
    expected_statuses = expect.get("http_statuses", [200])
    if status_code not in expected_statuses:
        structural_errors.append(f"expected HTTP {expected_statuses}, got {status_code}")
    actual_error_code = _response_error_code(response)
    expected_error_code = expect.get("error_code")
    if expected_error_code and actual_error_code != expected_error_code:
        structural_errors.append(
            f"error.code expected={expected_error_code}, actual={actual_error_code}"
        )
    clarification_used = actual_error_code == "AGENT_CLARIFICATION_REQUIRED"
    clarification_allowed = clarification_used and bool(expect.get("allow_clarification"))
    expected_tool = expect.get("tool_name")
    actual_tool = response.get("tool_name")
    expected_route = expect.get("route")
    actual_route = _actual_route(trace, actual_tool)
    route_pass = not expected_route or actual_route == expected_route or clarification_allowed
    tool_pass = not expected_tool or actual_tool == expected_tool or clarification_allowed
    if not route_pass:
        structural_errors.append(f"route expected={expected_route}, actual={actual_route}")
    if not tool_pass:
        structural_errors.append(f"tool_name expected={expected_tool}, actual={actual_tool}")
    if not clarification_allowed:
        if "requires_confirmation" in expect and response.get("requires_confirmation") != expect["requires_confirmation"]:
            safety_errors.append(
                "requires_confirmation "
                f"expected={expect['requires_confirmation']}, actual={response.get('requires_confirmation')}"
            )
    expected_ui_type = expect.get("ui_action_type")
    actual_ui_type = _nested_value(response, "ui_action", "type")
    if expected_ui_type and actual_ui_type != expected_ui_type and not clarification_allowed:
        structural_errors.append(f"ui_action.type expected={expected_ui_type}, actual={actual_ui_type}")
    expected_ui_target = expect.get("ui_action_target")
    actual_ui_target = _nested_value(response, "ui_action", "target")
    if expected_ui_target and actual_ui_target != expected_ui_target and not clarification_allowed:
        structural_errors.append(
            f"ui_action.target expected={expected_ui_target}, actual={actual_ui_target}"
        )
    minimum_items = expect.get("min_items")
    actual_items = response.get("items")
    if (
        minimum_items is not None
        and not clarification_allowed
        and (not isinstance(actual_items, list) or len(actual_items) < minimum_items)
    ):
        structural_errors.append(f"item_count expected>={minimum_items}, actual={len(actual_items or [])}")

    arguments = _tool_arguments(trace, expected_tool) or _response_tool_arguments(
        response,
        expected_tool,
    )
    if not clarification_allowed:
        for field, expected_value in dict(expect.get("argument_equals", {})).items():
            actual_value = arguments.get(field)
            if actual_value != expected_value:
                constraint_errors.append(f"{field} expected={expected_value!r}, actual={actual_value!r}")
        for field, expected_values in dict(expect.get("argument_includes", {})).items():
            actual_values = arguments.get(field)
            if not isinstance(actual_values, list) or not set(expected_values).issubset(set(actual_values)):
                constraint_errors.append(f"{field} must include {expected_values!r}, actual={actual_values!r}")

    safety_pass = not safety_errors
    structural_pass = not structural_errors and safety_pass
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
        "route_pass": route_pass,
        "tool_pass": tool_pass,
        "safety_pass": safety_pass,
        "clarification_used": clarification_used,
        "expected_route": expected_route,
        "actual_route": actual_route,
        "errors": " | ".join([*structural_errors, *safety_errors, *constraint_errors]),
    }


_TOOL_ROUTE_MAP = {
    "create_recommendation": "recommendation",
    "refine_product_results": "recommendation_refinement",
    "find_similar_products": "product_reference",
    "compare_products": "product_reference",
    "add_to_cart": "cart_checkout",
    "get_cart": "cart_checkout",
    "compose_cart": "cart_checkout",
    "prepare_product_checkout": "cart_checkout",
    "prepare_checkout": "cart_checkout",
    "prepare_order": "cart_checkout",
    "register_shipping_address": "cart_checkout",
    "filter_order_history": "order_after_sales",
    "order_status_lookup": "order_after_sales",
    "cancel_recent_order": "order_after_sales",
    "prepare_review_draft": "order_after_sales",
    "prepare_claim_draft": "order_after_sales",
    "bulk_wishlist_by_popular_ingredient": "bulk_wishlist",
}


def _actual_route(trace: Mapping[str, Any] | None, actual_tool: Any) -> str | None:
    if isinstance(trace, Mapping):
        stages = trace.get("agent_stages")
        if isinstance(stages, Mapping):
            router = stages.get("router")
            if isinstance(router, Mapping) and isinstance(router.get("route"), str):
                return str(router["route"])
        route = trace.get("route")
        if isinstance(route, Mapping):
            telemetry = route.get("telemetry")
            if isinstance(telemetry, Mapping) and isinstance(telemetry.get("agent_router_route"), str):
                return str(telemetry["agent_router_route"])
    return _TOOL_ROUTE_MAP.get(str(actual_tool)) if actual_tool else None


def extract_trace_metrics(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "execution_mode": None,
        "actual_model": None,
        "model_source": None,
        "model_called": None,
        "provider_model_call_count": 0,
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
        "router_model": None,
        "router_ms": None,
        "router_route": None,
        "router_confidence": None,
        "router_instructions_bytes": None,
        "router_input_bytes": None,
        "router_input_tokens": None,
        "router_output_tokens": None,
        "router_estimated_cost_usd": None,
        "specialist_name": None,
        "specialist_model": None,
        "specialist_ms": None,
        "specialist_tool_count": None,
        "specialist_instructions_bytes": None,
        "specialist_input_bytes": None,
        "specialist_input_tokens": None,
        "specialist_output_tokens": None,
        "specialist_estimated_cost_usd": None,
        "fallback_enabled": None,
        "fallback_used": False,
        "fallback_reason": None,
        "fallback_model": None,
        "fallback_ms": None,
        "fallback_input_tokens": None,
        "fallback_output_tokens": None,
        "fallback_estimated_cost_usd": None,
        "tool_validation_failed": False,
        "final_response_ms": None,
    }
    if not isinstance(trace, Mapping):
        return metrics
    agent = trace.get("agent") if isinstance(trace.get("agent"), Mapping) else {}
    route = trace.get("route") if isinstance(trace.get("route"), Mapping) else {}
    timing = trace.get("timings_ms") if isinstance(trace.get("timings_ms"), Mapping) else {}
    route_telemetry = route.get("telemetry") if isinstance(route.get("telemetry"), Mapping) else {}
    stages = trace.get("agent_stages") if isinstance(trace.get("agent_stages"), Mapping) else {}
    router = _trace_stage(stages, "router")
    specialist = _trace_stage(stages, "specialist")
    fallback = _trace_stage(stages, "fallback")
    stage_payloads = [stage for stage in (router, specialist, fallback) if stage]
    runner_result = agent.get("runner_result") if isinstance(agent.get("runner_result"), Mapping) else {}
    usage = _aggregate_trace_usage(stage_payloads) if stage_payloads else _trace_usage(agent)
    cost = _aggregate_trace_cost(stage_payloads) if stage_payloads else _trace_cost(agent)
    instructions_bytes = (
        _sum_optional(stage.get("instructions_bytes") for stage in stage_payloads)
        if stage_payloads
        else agent.get("instructions_bytes")
    )
    selected_tool_schema_bytes = (
        _sum_optional(stage.get("selected_tool_schema_bytes") for stage in stage_payloads)
        if stage_payloads
        else agent.get("selected_tool_schema_bytes")
    )
    selected_tool_count = (
        _sum_optional(stage.get("selected_tool_count") for stage in stage_payloads)
        if stage_payloads
        else agent.get("selected_tool_count")
    )
    metrics.update(
        {
            "execution_mode": _first_present(
                route_telemetry.get("agent_execution_mode"),
                route.get("agent_execution_mode"),
                "router_specialist" if router else None,
                "single" if agent else None,
            ),
            "actual_model": agent.get("model"),
            "model_source": agent.get("model_source")
            or ("not_called" if not agent and route.get("outcome") == "succeeded" else None),
            "model_called": bool(
                agent.get("model")
                or router.get("model")
                or specialist.get("model")
                or fallback.get("model")
            ),
            "provider_model_call_count": _provider_model_call_count(
                stages=stage_payloads,
                agent=agent,
            ),
            "short_circuit_reason": agent.get("short_circuit_reason"),
            "instructions_bytes": instructions_bytes,
            "selected_tool_count": selected_tool_count,
            "selected_tool_schema_bytes": selected_tool_schema_bytes,
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
            "router_model": router.get("model"),
            "router_ms": _first_present(
                timing.get("agent_router_ms"),
                route_telemetry.get("agent_router_ms"),
                _stage_duration_ms(router),
            ),
            "router_route": _first_present(
                router.get("route"),
                route_telemetry.get("agent_router_route"),
            ),
            "router_confidence": _first_present(
                router.get("confidence"),
                route_telemetry.get("agent_router_confidence"),
            ),
            "router_instructions_bytes": router.get("instructions_bytes"),
            "router_input_bytes": router.get("input_bytes"),
            "router_input_tokens": _trace_usage(router).get("input_tokens"),
            "router_output_tokens": _trace_usage(router).get("output_tokens"),
            "router_estimated_cost_usd": _trace_cost(router).get("estimated_cost_usd"),
            "specialist_name": _first_present(
                specialist.get("name"),
                route_telemetry.get("agent_specialist_name"),
            ),
            "specialist_model": specialist.get("model"),
            "specialist_ms": _first_present(
                timing.get("agent_specialist_ms"),
                route_telemetry.get("agent_specialist_ms"),
                _stage_duration_ms(specialist),
            ),
            "specialist_tool_count": specialist.get("selected_tool_count"),
            "specialist_instructions_bytes": specialist.get("instructions_bytes"),
            "specialist_input_bytes": specialist.get("input_bytes"),
            "specialist_input_tokens": _trace_usage(specialist).get("input_tokens"),
            "specialist_output_tokens": _trace_usage(specialist).get("output_tokens"),
            "specialist_estimated_cost_usd": _trace_cost(specialist).get("estimated_cost_usd"),
            "fallback_enabled": route_telemetry.get("agent_fallback_enabled"),
            "fallback_used": bool(route_telemetry.get("agent_fallback_used") or fallback),
            "fallback_reason": route_telemetry.get("agent_fallback_reason"),
            "fallback_model": _first_present(
                fallback.get("model"),
                route_telemetry.get("agent_fallback_model"),
            ),
            "fallback_ms": _first_present(
                timing.get("agent_fallback_ms"),
                route_telemetry.get("agent_fallback_ms"),
                _stage_duration_ms(fallback),
            ),
            "fallback_input_tokens": _trace_usage(fallback).get("input_tokens"),
            "fallback_output_tokens": _trace_usage(fallback).get("output_tokens"),
            "fallback_estimated_cost_usd": _trace_cost(fallback).get("estimated_cost_usd"),
            "tool_validation_failed": bool(
                route_telemetry.get("agent_tool_validation_failed")
            ),
            "final_response_ms": _first_present(
                timing.get("agent_final_response_ms"),
                route_telemetry.get("agent_final_response_ms"),
            ),
        }
    )
    if isinstance(usage, Mapping):
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
            metrics[key] = usage.get(key)
    if isinstance(cost, Mapping):
        metrics["estimated_cost_usd"] = cost.get("estimated_cost_usd")
        metrics["cost_estimate_status"] = cost.get("estimate_status")
    return metrics


def _trace_stage(stages: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = stages.get(name)
    return value if isinstance(value, Mapping) else {}


def _trace_usage(stage: Mapping[str, Any]) -> Mapping[str, Any]:
    runner_result = stage.get("runner_result")
    if not isinstance(runner_result, Mapping):
        return {}
    usage = runner_result.get("usage_breakdown") or runner_result.get("usage")
    return usage if isinstance(usage, Mapping) else {}


def _trace_cost(stage: Mapping[str, Any]) -> Mapping[str, Any]:
    runner_result = stage.get("runner_result")
    if not isinstance(runner_result, Mapping):
        return {}
    cost = runner_result.get("cost_estimate")
    return cost if isinstance(cost, Mapping) else {}


def _aggregate_trace_usage(stages: Iterable[Mapping[str, Any]]) -> dict[str, int | None]:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    totals: dict[str, int | None] = {}
    for key in keys:
        values = [usage.get(key) for usage in (_trace_usage(stage) for stage in stages)]
        totals[key] = _sum_optional(values)
    return totals


def _aggregate_trace_cost(stages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    costs = [_trace_cost(stage) for stage in stages]
    estimated_cost_usd = _sum_optional(cost.get("estimated_cost_usd") for cost in costs)
    statuses = {str(cost.get("estimate_status")) for cost in costs if cost.get("estimate_status")}
    return {
        "estimated_cost_usd": estimated_cost_usd,
        "estimate_status": next(iter(statuses)) if len(statuses) == 1 else "mixed",
    }


def _stage_duration_ms(stage: Mapping[str, Any]) -> float | None:
    attempts = stage.get("runner_attempts")
    if not isinstance(attempts, list):
        return None
    return _sum_optional(
        attempt.get("duration_ms")
        for attempt in attempts
        if isinstance(attempt, Mapping)
    )


def _provider_model_call_count(
    *,
    stages: Iterable[Mapping[str, Any]],
    agent: Mapping[str, Any],
) -> int:
    """Count actual runner attempts rather than assuming one call per workflow."""

    stage_list = list(stages)
    targets = stage_list if stage_list else [agent]
    count = sum(_stage_provider_model_call_count(stage) for stage in targets)
    return count


def _stage_provider_model_call_count(stage: Mapping[str, Any]) -> int:
    attempts = stage.get("runner_attempts")
    if isinstance(attempts, list):
        attempt_count = sum(isinstance(item, Mapping) for item in attempts)
        if attempt_count:
            return attempt_count
    return int(bool(stage.get("model")))


def _sum_optional(values: Iterable[Any]) -> int | float | None:
    numeric_values = [value for value in values if isinstance(value, (int, float))]
    if not numeric_values:
        return None
    total = sum(numeric_values)
    return int(total) if all(isinstance(value, int) for value in numeric_values) else total


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


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
        "requested_profile": plan_item.get("profile_id"),
        "requested_execution_mode": plan_item.get("execution_mode", "single"),
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
            "requested_profile": row.get("requested_profile"),
            "requested_execution_mode": row.get("requested_execution_mode"),
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
        [
            "sample_key",
            "scenario_id",
            "requested_profile",
            "requested_execution_mode",
            "requested_model",
            "repeat",
            "validation_status",
            "tool_name",
            "trace_file",
            "reviewer_result",
            "reviewer_notes",
        ],
    )
    (output_dir / "report.md").write_text(
        render_report(rows=rows, summaries=summary_rows, manifest=manifest),
        encoding="utf-8",
    )


SCENARIO_CSV_FIELDS = [
    "sample_key", "scenario_id", "group", "auth_mode", "context_mode", "requested_profile",
    "requested_execution_mode", "requested_model", "repeat",
    "http_status", "client_roundtrip_ms", "http_error", "error_code", "trace_id", "trace_file", "trace_available",
    "execution_mode", "actual_model", "model_source", "model_called", "provider_model_call_count", "short_circuit_reason", "tool_name", "tool_call_count",
    "requires_confirmation", "ui_action_type", "ui_action_target", "item_count", "validation_status",
    "structural_pass", "constraint_pass", "route_pass", "tool_pass", "safety_pass", "clarification_used",
    "expected_route", "actual_route", "validation_errors", "manual_review_required", "instructions_bytes",
    "selected_tool_count", "selected_tool_schema_bytes", "agent_input_bytes", "route_total_ms", "agent_workflow_ms",
    "agent_runner_ms", "agent_model_and_orchestration_ms", "agent_tool_execution_ms",
    "agent_tool_reference_resolve_ms", "agent_tool_dispatch_ms", "agent_tool_response_serialize_ms",
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
    "estimated_cost_usd", "cost_estimate_status",
    "router_model", "router_ms", "router_route", "router_confidence", "router_instructions_bytes",
    "router_input_bytes", "router_input_tokens", "router_output_tokens", "router_estimated_cost_usd",
    "specialist_name", "specialist_model", "specialist_ms", "specialist_tool_count",
    "specialist_instructions_bytes", "specialist_input_bytes", "specialist_input_tokens",
    "specialist_output_tokens", "specialist_estimated_cost_usd", "fallback_enabled", "fallback_used",
    "fallback_reason", "fallback_model", "fallback_ms", "fallback_input_tokens",
    "fallback_output_tokens", "fallback_estimated_cost_usd", "tool_validation_failed", "final_response_ms",
]

SUMMARY_CSV_FIELDS = [
    "requested_profile", "requested_execution_mode", "requested_model", "group", "sample_count",
    "http_success_count", "model_called_count", "provider_model_call_count", "short_circuit_count", "fallback_used_count",
    "structural_pass_rate", "constraint_pass_rate", "route_pass_rate", "tool_pass_rate", "safety_pass_rate", "fallback_success_rate",
    "client_roundtrip_p50_ms", "client_roundtrip_p95_ms",
    "route_total_p50_ms", "route_total_p95_ms", "model_phase_p50_ms", "model_phase_p95_ms",
    "router_p50_ms", "router_p95_ms", "specialist_p50_ms", "specialist_p95_ms",
    "fallback_p50_ms", "fallback_p95_ms", "tool_execution_p50_ms", "tool_execution_p95_ms",
    "mean_input_tokens", "mean_output_tokens", "mean_total_tokens", "total_estimated_cost_usd",
    "mean_estimated_cost_usd",
]


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        profile = row.get("requested_profile") or row.get("requested_model")
        group = row.get("group")
        if profile and group and row.get("validation_status") != "skipped_write_preview":
            grouped[(str(profile), str(group))].append(row)
    summary: list[dict[str, Any]] = []
    for (profile, group), sample_rows in sorted(grouped.items()):
        successful = [row for row in sample_rows if row.get("http_status") == 200]
        model_called = [row for row in successful if row.get("model_called") is True]
        fallback_rows = [row for row in sample_rows if row.get("fallback_used") is True]
        representative = sample_rows[0]
        summary.append(
            {
                "requested_profile": profile,
                "requested_execution_mode": representative.get("requested_execution_mode", "single"),
                "requested_model": representative.get("requested_model"),
                "group": group,
                "sample_count": len(sample_rows),
                "http_success_count": len(successful),
                "model_called_count": len(model_called),
                "provider_model_call_count": _sum(
                    _numeric(sample_rows, "provider_model_call_count")
                ),
                "short_circuit_count": sum(row.get("model_called") is False for row in successful),
                "fallback_used_count": sum(row.get("fallback_used") is True for row in successful),
                "structural_pass_rate": _rate(successful, "structural_pass"),
                "constraint_pass_rate": _rate(successful, "constraint_pass"),
                "route_pass_rate": _rate(successful, "route_pass"),
                "tool_pass_rate": _rate(successful, "tool_pass"),
                "safety_pass_rate": _rate(successful, "safety_pass"),
                "fallback_success_rate": _rate(fallback_rows, "structural_pass") if fallback_rows else None,
                "client_roundtrip_p50_ms": _percentile(_numeric(successful, "client_roundtrip_ms"), 50),
                "client_roundtrip_p95_ms": _percentile(_numeric(successful, "client_roundtrip_ms"), 95),
                "route_total_p50_ms": _percentile(_numeric(successful, "route_total_ms"), 50),
                "route_total_p95_ms": _percentile(_numeric(successful, "route_total_ms"), 95),
                "model_phase_p50_ms": _percentile(_numeric(model_called, "agent_model_and_orchestration_ms"), 50),
                "model_phase_p95_ms": _percentile(_numeric(model_called, "agent_model_and_orchestration_ms"), 95),
                "router_p50_ms": _percentile(_numeric(model_called, "router_ms"), 50),
                "router_p95_ms": _percentile(_numeric(model_called, "router_ms"), 95),
                "specialist_p50_ms": _percentile(_numeric(model_called, "specialist_ms"), 50),
                "specialist_p95_ms": _percentile(_numeric(model_called, "specialist_ms"), 95),
                "fallback_p50_ms": _percentile(_numeric(model_called, "fallback_ms"), 50),
                "fallback_p95_ms": _percentile(_numeric(model_called, "fallback_ms"), 95),
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
    successful = [row for row in completed if row.get("http_status") == 200]
    model_rows = [row for row in successful if row.get("model_called") is True]
    provider_model_calls = sum(
        int(value)
        for row in completed
        if isinstance((value := row.get("provider_model_call_count")), (int, float))
    )
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
            "## Overall Execution Metrics",
            "",
            f"- Provider model calls: {provider_model_calls}",
            (
                "- Overall response p50/p95 (ms): "
                f"{_percentile(_numeric(successful, 'client_roundtrip_ms'), 50)}/"
                f"{_percentile(_numeric(successful, 'client_roundtrip_ms'), 95)}"
            ),
            (
                "- Overall Router p50/p95 (ms): "
                f"{_percentile(_numeric(model_rows, 'router_ms'), 50)}/"
                f"{_percentile(_numeric(model_rows, 'router_ms'), 95)}"
            ),
            (
                "- Overall Specialist p50/p95 (ms): "
                f"{_percentile(_numeric(model_rows, 'specialist_ms'), 50)}/"
                f"{_percentile(_numeric(model_rows, 'specialist_ms'), 95)}"
            ),
            (
                "- Route/tool/safety pass rates: "
                f"{_rate(successful, 'route_pass')}/"
                f"{_rate(successful, 'tool_pass')}/"
                f"{_rate(successful, 'safety_pass')}"
            ),
        ]
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
    configured_profiles = manifest.get("configuration", {}).get("profiles", [])
    lines.extend(
        [
            "",
            "## Execution Profiles And Stage Timings",
            "",
            "| Profile | Mode | Model | Group | Router p50/p95 (ms) | Specialist p50/p95 (ms) | Fallback uses | Response p50/p95 (ms) | Cost (USD) |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for summary in summaries:
        lines.append(
            "| {requested_profile} | {requested_execution_mode} | {requested_model} | {group} | "
            "{router_p50_ms}/{router_p95_ms} | {specialist_p50_ms}/{specialist_p95_ms} | "
            "{fallback_used_count} | {client_roundtrip_p50_ms}/{client_roundtrip_p95_ms} | "
            "{total_estimated_cost_usd} |".format(**summary)
        )
    if configured_profiles:
        lines.extend(["", "Configured profiles:"])
        for profile in configured_profiles:
            if not isinstance(profile, Mapping):
                continue
            lines.append(
                "- `{id}`: mode=`{execution_mode}`, model=`{requested_model}`, "
                "router=`{router_model}`, specialist=`{specialist_model}`, "
                "fallback_enabled=`{specialist_fallback_enabled}`, "
                "fallback_model=`{specialist_fallback_model}`".format(**profile)
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
