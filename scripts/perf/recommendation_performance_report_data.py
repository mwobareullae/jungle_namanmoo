"""Normalize recommendation benchmark runs for curated performance reporting."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from scripts.perf import analyze_benchmark_results as legacy_analysis


CATALOG_COLUMNS = [
    "run_id",
    "implementation_stage",
    "stage_label",
    "stage_order",
    "measurement_schema",
    "git_sha",
    "started_at",
    "finished_at",
    "dataset",
    "product_count",
    "target_product_count",
    "user_type",
    "query_id",
    "vus",
    "duration",
    "cache_state",
    "candidate_pool_limit",
    "run_dir",
]

COMPARABILITY_COLUMNS = [
    "run_id",
    "implementation_stage",
    "measurement_schema",
    "complete",
    "condition_matches",
    "headline_selected",
    "error_rate",
    "error_gate_passed",
    "headline_eligible",
    "problem_evidence_eligible",
    "pipeline_eligible",
    "resource_data_available",
    "exclusion_reason",
]

PREFERRED_SUMMARY_COLUMNS = CATALOG_COLUMNS + COMPARABILITY_COLUMNS[3:] + [
    "latency_avg_ms",
    "latency_p50_ms",
    "latency_p90_ms",
    "latency_p95_ms",
    "latency_max_ms",
    "recommendation_rps",
    "recommendation_request_count",
    "recommendation_http_failed_rate",
    "check_failed_rate",
    "pipeline_event_count",
]

SENSITIVE_KEY_FRAGMENTS = (
    "auth",
    "cookie",
    "password",
    "secret",
    "setup_data",
    "token",
)


def load_registry(repo_root: Path, registry_path: Path) -> dict[str, Any]:
    resolved = registry_path if registry_path.is_absolute() else repo_root / registry_path
    registry = json.loads(resolved.read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1:
        raise ValueError("Unsupported recommendation performance report registry schema")
    stage_ids = [stage["id"] for stage in registry.get("stages", [])]
    if len(stage_ids) != len(set(stage_ids)):
        raise ValueError("Duplicate implementation stage id in registry")
    return registry


def collect_report_rows(repo_root: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: dict[Path, dict[str, Any]] = {}
    for stage in registry.get("stages", []):
        for root_name in stage.get("roots", []):
            root = (repo_root / root_name).resolve()
            if not root.exists():
                continue
            for run_dir in legacy_analysis.find_run_dirs(root):
                assignments[run_dir.resolve()] = stage
        for run_name in stage.get("runs", []):
            run_dir = (repo_root / run_name).resolve()
            if run_dir.exists():
                assignments[run_dir] = stage

    loose_root = (repo_root / registry.get("loose_run_root", "perf-runs")).resolve()
    loose_runs = {
        path.resolve()
        for path in loose_root.glob("recommendation-*")
        if path.is_dir()
    }
    supplemental_runs: set[Path] = set()
    for root_name in registry.get("supplemental_run_roots", []):
        root = (repo_root / root_name).resolve()
        if root.exists():
            supplemental_runs.update(path.resolve() for path in legacy_analysis.find_run_dirs(root))

    rows: list[dict[str, Any]] = []
    for run_dir in sorted(set(assignments) | loose_runs | supplemental_runs):
        rows.append(
            build_report_row(
                repo_root,
                run_dir,
                assignments.get(run_dir),
                registry["comparison"],
            )
        )
    return sorted(rows, key=row_sort_key)


def build_report_row(
    repo_root: Path,
    run_dir: Path,
    stage: dict[str, Any] | None,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    k6_path = legacy_analysis.find_k6_summary(run_dir)
    backend_path = run_dir / "backend" / "backend.log"
    resources_path = run_dir / "resources" / "docker-stats.csv"

    manifest = load_json(manifest_path) or {}
    parsed = legacy_analysis.build_run_row(run_dir.parent, run_dir) or {}
    run_id = str(manifest.get("run_id") or run_dir.name)
    relative_run_dir = relative_posix(repo_root, run_dir)

    row: dict[str, Any] = dict(parsed)
    row.update(
        {
            "run_id": run_id,
            "run_dir": relative_run_dir,
            "implementation_stage": stage["id"] if stage else "unassigned",
            "stage_label": stage["label"] if stage else "Unassigned",
            "stage_order": stage["order"] if stage else 999,
            "stage_color": stage["color"] if stage else "#9CA3AF",
            "git_sha": str(manifest.get("git_sha") or "unknown"),
            "started_at": str(manifest.get("started_at") or ""),
            "finished_at": str(manifest.get("finished_at") or ""),
            "k6_exit_code": int_or_none(manifest.get("k6_exit_code")),
            "measurement_schema": infer_measurement_schema(parsed),
            "manifest_sha256": sha256_file(manifest_path),
            "k6_summary_sha256": sha256_file(k6_path),
            "backend_log_sha256": sha256_file(backend_path),
            "resource_log_sha256": sha256_file(resources_path),
        }
    )

    complete = bool(
        manifest_path.is_file()
        and k6_path.is_file()
        and backend_path.is_file()
        and manifest.get("k6_result_present") is True
        and numeric(row.get("pipeline_event_count"), 0) > 0
    )
    error_rates = [
        numeric_or_none(row.get("recommendation_http_failed_rate")),
        numeric_or_none(row.get("check_failed_rate")),
    ]
    error_rate = max((value for value in error_rates if value is not None), default=None)
    error_gate_passed = error_rate is not None and error_rate <= float(comparison["max_error_rate"])
    condition_matches = matches_condition(row, comparison)
    assigned = stage is not None and stage.get("status") == "measured"
    headline_run_ids = set(stage.get("headline_run_ids", [])) if stage else set()
    headline_selected = bool(
        assigned and (not headline_run_ids or run_id in headline_run_ids)
    )
    headline_eligible = bool(
        headline_selected and complete and condition_matches and error_gate_passed
    )
    problem_evidence_eligible = bool(assigned and complete and condition_matches)
    pipeline_eligible = bool(problem_evidence_eligible and numeric(row.get("pipeline_event_count"), 0) > 0)

    exclusion_reasons: list[str] = []
    if not assigned:
        exclusion_reasons.append("unassigned_stage")
    if assigned and not headline_selected:
        exclusion_reasons.append("not_selected_for_headline")
    if not complete:
        exclusion_reasons.append("incomplete_run")
    if complete and not condition_matches:
        exclusion_reasons.append("headline_condition_mismatch")
    if complete and condition_matches and not error_gate_passed:
        formatted = "unavailable" if error_rate is None else f"{error_rate:.4f}"
        exclusion_reasons.append(f"error_rate_exceeds_{comparison['max_error_rate']}:actual={formatted}")

    row.update(
        {
            "complete": complete,
            "condition_matches": condition_matches,
            "headline_selected": headline_selected,
            "error_rate": error_rate,
            "error_gate_passed": error_gate_passed,
            "headline_eligible": headline_eligible,
            "problem_evidence_eligible": problem_evidence_eligible,
            "pipeline_eligible": pipeline_eligible,
            "resource_data_available": resources_path.is_file(),
            "exclusion_reason": ";".join(exclusion_reasons),
        }
    )
    return row


def infer_measurement_schema(row: dict[str, Any]) -> str:
    if numeric_or_none(row.get("prefetch_candidate_bundle_ms_avg")) is not None:
        return "bulk-prefetch-v4"
    if (
        numeric_or_none(row.get("product_feature_load_ms_avg")) is not None
        or numeric_or_none(row.get("score_loop_ingredient_axis_ms_avg")) is not None
    ):
        return "scoring-detail-v3"
    if numeric_or_none(row.get("intent_purchase_brand_match_ms_avg")) is not None:
        return "intent-detail-v2"
    return "pipeline-v1"


def matches_condition(row: dict[str, Any], comparison: dict[str, Any]) -> bool:
    exact_fields = ("dataset", "vus", "duration", "user_type", "query_id", "cache_state")
    for field in exact_fields:
        expected = comparison.get(field)
        if expected is not None and str(row.get(field)) != str(expected):
            return False
    actual_count = comparison.get("actual_product_count")
    if actual_count is not None and int_or_none(row.get("product_count")) != int(actual_count):
        return False
    return True


def stage_rows(
    rows: Iterable[dict[str, Any]],
    stage_id: str,
    *,
    eligible_only: bool = True,
) -> list[dict[str, Any]]:
    result = [row for row in rows if row.get("implementation_stage") == stage_id]
    if eligible_only:
        result = [row for row in result if row.get("headline_eligible")]
    return sorted(result, key=row_sort_key)


def representative_row(rows: list[dict[str, Any]], metric: str = "latency_p95_ms") -> dict[str, Any] | None:
    candidates = [row for row in rows if numeric_or_none(row.get(metric)) is not None]
    if not candidates:
        return None
    median_value = statistics.median(float(row[metric]) for row in candidates)
    return min(candidates, key=lambda row: (abs(float(row[metric]) - median_value), str(row["run_id"])))


def median_metric(rows: Iterable[dict[str, Any]], metric: str) -> float | None:
    values = [float(row[metric]) for row in rows if numeric_or_none(row.get(metric)) is not None]
    return statistics.median(values) if values else None


def mean_metric(rows: Iterable[dict[str, Any]], metric: str) -> float | None:
    values = [float(row[metric]) for row in rows if numeric_or_none(row.get(metric)) is not None]
    return statistics.mean(values) if values else None


def write_csv_rows(path: Path, rows: list[dict[str, Any]], preferred: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = ordered_keys(rows, preferred or [])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def public_metrics_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drop credential-bearing fields before normalized artifacts are written."""
    return {
        key: value
        for key, value in row.items()
        if not any(fragment in key.lower() for fragment in SENSITIVE_KEY_FRAGMENTS)
    }


def ordered_keys(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    available = {key for row in rows for key in row}
    ordered = [key for key in preferred if key in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


def relative_posix(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int_or_none(row.get("stage_order")) or 999,
        int_or_none(row.get("dataset")) or 0,
        int_or_none(row.get("vus")) or 0,
        str(row.get("run_id") or ""),
    )


def numeric(value: Any, default: float) -> float:
    parsed = numeric_or_none(value)
    return parsed if parsed is not None else default


def numeric_or_none(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def int_or_none(value: Any) -> int | None:
    number = numeric_or_none(value)
    return int(number) if number is not None else None
