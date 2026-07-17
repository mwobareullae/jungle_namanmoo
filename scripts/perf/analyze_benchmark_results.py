"""Generate recommendation benchmark summary CSV and performance graphs.

The script reads benchmark run folders produced by scripts/perf/benchmarkctl-local.ps1.
It supports both old logs that only have pipeline-level timings and newer logs
that include scoring/context breakdown fields.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RUN_NAME_RE = re.compile(
    r"^recommendation-(?P<dataset>\d+)-(?P<user_type>.+)-(?P<started_at>\d{8}-\d{6})$"
)
VUS_RE = re.compile(r"vus(?P<vus>\d+)", re.IGNORECASE)

DATASET_ORDER = [1000, 5000, 10000, 80000]
DATASET_LABEL_ORDER = [str(dataset) for dataset in DATASET_ORDER]
VUS_ORDER = [1, 3, 5, 8, 10]
VUS_LABEL_ORDER = [f"VUS {vus}" for vus in VUS_ORDER]

PIPELINE_STAGES = [
    ("user_context_load_ms", "saved profile"),
    ("skin_test_context_load_ms", "skin test"),
    ("behavior_context_load_ms", "behavior context"),
    ("intent_parse_ms", "intent"),
    ("run_save_ms", "run save"),
    ("candidate_pool_ms", "candidate pool"),
    ("search_match_ms", "search match"),
    ("search_candidate_save_ms", "candidate save"),
    ("scoring_ms", "scoring"),
    ("result_save_ms", "result save"),
    ("commit_ms", "commit"),
    ("response_load_ms", "response load"),
]

SCORING_STAGES = [
    ("scoring_data_prefetch_ms", "data prefetch"),
    ("score_context_build_ms", "context build"),
    ("score_loop_ms", "score loop"),
    ("score_sort_ms", "sort"),
    ("score_detail_materialization_ms", "top result details"),
]

# Opt4c first ranks the full candidate set with compact features, then runs the
# legacy exact scorer only for the top 50. The generic prefetch/loop metrics are
# aliases of the exact phase in this path, so including both would double count.
COARSE_TOP50_SCORING_STAGES = [
    ("coarse_feature_query_ms", "coarse feature query"),
    ("coarse_feature_build_ms", "coarse feature build"),
    ("coarse_feature_source_fallback_ms", "coarse source fallback"),
    ("coarse_context_build_ms", "coarse context build"),
    ("coarse_score_loop_ms", "coarse candidate loop"),
    ("exact_prefetch_ms", "exact top-50 prefetch"),
    ("exact_score_loop_ms", "exact top-50 score loop"),
    ("score_sort_ms", "sort"),
    ("score_detail_materialization_ms", "top result details"),
]

SCORING_PREFETCH_FIELDS = [
    ("snapshot_load_ms", "snapshot load"),
    ("candidate_bundle_ms", "candidate bundle"),
    ("effect_features_ms", "effect features"),
    ("ingredient_effects_ms", "ingredient effects"),
    ("risk_flags_ms", "risk flags"),
    ("review_segments_ms", "review segments"),
    ("behavior_signals_ms", "behavior signals"),
    ("detail_ingredients_ms", "detail ingredients"),
]

SNAPSHOT_READ_MODEL_FIELDS = [
    "scoring_snapshot_load_ms",
    "scoring_snapshot_hit_count",
    "scoring_snapshot_miss_count",
    "scoring_snapshot_fallback_ms",
    "scoring_snapshot_parse_error_count",
]

# Query timings include both database execution and row materialization because
# the measured call uses SQLAlchemy's ``.all()``. Build timings are the Python
# grouping / signal-construction work after those rows have been loaded.
BEHAVIOR_SIGNAL_DETAIL_STAGES = [
    ("prefetch_detail_behavior_signals_base_query_ms", "base product query"),
    ("prefetch_detail_behavior_signals_price_load_ms", "price load"),
    ("prefetch_detail_behavior_signals_ingredient_query_ms", "ingredient/effect query"),
    ("prefetch_detail_behavior_signals_build_ms", "Python signal build"),
]

INGREDIENT_EFFECT_DETAIL_STAGES = [
    ("prefetch_detail_ingredient_effects_query_ms", "ingredient/effect query"),
    ("prefetch_detail_ingredient_effects_build_ms", "Python grouping"),
]

SCORE_LOOP_DETAIL_STAGES = [
    ("score_loop_contribution_build_ms", "contribution build"),
    ("score_loop_ingredient_axis_ms", "ingredient axis"),
    ("score_loop_functional_axis_ms", "functional axis"),
    ("score_loop_skin_profile_axis_ms", "skin profile axis"),
    ("score_loop_search_price_market_axis_ms", "search / price / market"),
    ("score_loop_review_axis_ms", "review axis"),
    ("score_loop_behavior_axis_ms", "behavior axis"),
    ("score_loop_skin_test_axis_ms", "skin test axis"),
    ("score_loop_final_score_ms", "final weighted score"),
]

CONTEXT_LOAD_STAGES = [
    ("user_context_load_ms", "saved profile"),
    ("skin_test_context_load_ms", "skin test"),
    ("behavior_context_load_ms", "behavior"),
]

# Persistence is measured in three write groups.  Keeping each group separate
# lets the benchmark distinguish Python object construction from database work
# such as flushes and deletes.
PERSISTENCE_STAGES = [
    ("run_save_ms", "recommendation run save"),
    ("search_candidate_save_ms", "candidate trace save"),
    ("result_save_ms", "result and evidence save"),
    ("commit_ms", "transaction commit"),
    ("response_load_ms", "response reload"),
]

RUN_SAVE_DETAIL_STAGES = [
    ("run_row_build_ms", "run row build"),
    ("run_insert_flush_ms", "run insert flush"),
    ("run_relation_build_ms", "relation row build"),
    ("run_relation_add_ms", "relation add"),
    ("run_relation_flush_ms", "relation flush"),
]

CANDIDATE_SAVE_DETAIL_STAGES = [
    ("candidate_trace_match_validation_ms", "trace match validation"),
    ("candidate_trace_delete_ms", "existing trace delete"),
    ("candidate_trace_row_build_ms", "candidate row build"),
    ("candidate_trace_add_ms", "candidate add"),
    ("candidate_trace_flush_ms", "candidate flush"),
]

RESULT_SAVE_DETAIL_STAGES = [
    ("result_existing_lookup_ms", "existing result lookup"),
    ("result_existing_evidence_delete_ms", "existing evidence delete"),
    ("result_existing_result_delete_ms", "existing result delete"),
    ("result_existing_delete_flush_ms", "existing delete flush"),
    ("result_row_build_ms", "result row build"),
    ("result_add_ms", "result add"),
    ("result_flush_ms", "result flush"),
    ("evidence_row_build_ms", "evidence row build"),
    ("evidence_add_ms", "evidence add"),
    ("evidence_flush_ms", "evidence flush"),
]

INTENT_STAGES = [
    ("intent_repository_load_ms", "repository load"),
    ("intent_rule_parse_ms", "rule parser"),
    ("intent_llm_call_ms", "LLM parser"),
    ("intent_llm_merge_ms", "LLM merge"),
    ("intent_purchase_parse_ms", "purchase parser"),
    ("intent_unattributed_ms", "unattributed"),
]

INTENT_LLM_STAGES = [
    ("intent_llm_prompt_load_ms", "prompt load"),
    ("intent_llm_schema_load_ms", "schema load"),
    ("intent_llm_request_build_ms", "request build"),
    ("intent_llm_http_ms", "HTTP wait"),
    ("intent_llm_response_parse_ms", "response parse"),
    ("intent_llm_schema_validate_ms", "schema validate"),
]

INTENT_DETAIL_LLM_KEYS = {key for key, _ in INTENT_LLM_STAGES}

PURCHASE_PARSER_STAGES = [
    ("intent_purchase_normalize_ms", "normalize"),
    ("intent_purchase_price_ms", "price"),
    ("intent_purchase_category_ms", "category"),
    ("intent_purchase_brand_alias_load_ms", "brand alias load"),
    ("intent_purchase_brand_match_ms", "brand match"),
]

ANALYSIS_SUBDIRS = {
    "summary": "00-summary",
    "execution_flow": "00-summary/execution-flow",
    "persistence": "00-summary/execution-flow/persistence",
    "pipeline": "10-pipeline",
    "instrumentation": "20-instrumentation",
    "intent": "30-root-cause/intent-parser",
    "scoring": "30-root-cause/scoring",
    "data_loading": "30-root-cause/data-loading",
    "guardrails": "40-guardrails",
    "data": "data",
}


def main() -> None:
    args = parse_args()
    input_dir = args.input.resolve()
    output_dir = args.output.resolve()
    output_dirs = prepare_analysis_output(output_dir)

    rows = collect_rows(input_dir)
    if not rows:
        raise SystemExit(f"No benchmark runs found under: {input_dir}")

    rows = sorted(rows, key=row_sort_key)
    write_summary_csv(rows, output_dirs["data"] / "summary.csv")
    coverage_rows = build_instrumentation_coverage(rows)
    write_dict_csv(
        coverage_rows,
        output_dirs["data"] / "instrumentation-coverage.csv",
    )
    stage_id = args.stage_id or infer_stage_id(input_dir)
    stage_context = load_stage_context(args.registry.resolve(), stage_id)
    write_analysis_manifest(
        input_dir,
        rows,
        output_dirs["data"] / "analysis-manifest.json",
        stage_id=stage_id,
        purpose=args.purpose,
    )

    pd, plt, sns = load_plot_dependencies()
    df = prepare_plot_dataframe(pd.DataFrame(rows), pd)
    sns.set_theme(style="whitegrid", context="talk")
    plot_summary_graphs(df, output_dirs, plt, sns)
    plot_instrumentation_coverage(
        coverage_rows,
        output_dirs["instrumentation"] / "metric-coverage.png",
        plt,
        sns,
    )
    plot_stage_graphs(
        df,
        output_dirs,
        plt,
        sns,
        stage_dataset=args.stage_dataset,
        stage_vus=args.stage_vus,
        stage_context=stage_context,
    )
    write_analysis_readme(
        output_dir / "README.md",
        rows,
        coverage_rows,
        stage_id=stage_id,
        purpose=args.purpose,
        stage_context=stage_context,
        stage_dataset=args.stage_dataset,
        stage_vus=args.stage_vus,
    )

    print(f"summary={output_dirs['data'] / 'summary.csv'}")
    print(f"graphs={output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze recommendation benchmark run folders and create graphs."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Benchmark result root, e.g. perf-runs/baseline-v1-full-personalized",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Directory for summary.csv and PNG graphs.",
    )
    parser.add_argument(
        "--stage-dataset",
        type=int,
        default=80000,
        help="Dataset size used for stage breakdown graphs.",
    )
    parser.add_argument(
        "--stage-vus",
        type=int,
        default=10,
        help="VUS value used for stage breakdown graphs.",
    )
    parser.add_argument(
        "--stage-id",
        help="Implementation stage recorded in analysis-manifest.json.",
    )
    parser.add_argument(
        "--purpose",
        default="단계별 추천 성능과 병목 진단",
        help="Reason for producing this analysis.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("scripts/perf/recommendation-performance-report.json"),
        help="Stage registry used to describe the next optimization.",
    )
    return parser.parse_args()


def prepare_analysis_output(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for key, relative in ANALYSIS_SUBDIRS.items():
        path = output_dir / relative
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        paths[key] = path
    return paths


def infer_stage_id(input_dir: Path) -> str:
    parts = input_dir.parts
    if "stages" in parts:
        index = parts.index("stages")
        if index + 1 < len(parts):
            return parts[index + 1]
    return "unassigned"


def load_stage_context(registry_path: Path, stage_id: str) -> dict[str, Any]:
    if not registry_path.exists():
        return {}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    stages = sorted(registry.get("stages", []), key=lambda stage: stage.get("order", 0))
    for index, stage in enumerate(stages):
        if stage.get("id") != stage_id:
            continue
        next_stage = stages[index + 1] if index + 1 < len(stages) else None
        return {"stage": stage, "next_stage": next_stage}
    return {}


def load_plot_dependencies():
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
        import seaborn as sns
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing analysis dependency. Install with: "
            "python -m pip install -r scripts/perf/requirements-analysis.txt"
        ) from exc
    return pd, plt, sns


def prepare_plot_dataframe(df, pd):
    prepared = df.copy()
    prepared["dataset_label"] = pd.Categorical(
        prepared["dataset"].astype(str),
        categories=DATASET_LABEL_ORDER,
        ordered=True,
    )
    prepared["vus_label"] = pd.Categorical(
        prepared["vus"].map(lambda value: f"VUS {int(value)}"),
        categories=VUS_LABEL_ORDER,
        ordered=True,
    )
    if "recommendation_http_failed_rate" in prepared.columns:
        prepared["recommendation_http_failed_percent"] = (
            prepared["recommendation_http_failed_rate"] * 100
        )
    if "check_failed_rate" in prepared.columns:
        prepared["check_failed_percent"] = prepared["check_failed_rate"] * 100
    return prepared


def collect_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir in find_run_dirs(input_dir):
        row = build_run_row(input_dir, run_dir)
        if row is not None:
            rows.append(row)
    return rows


def find_run_dirs(input_dir: Path) -> list[Path]:
    run_dirs: set[Path] = set()
    for manifest_path in input_dir.rglob("manifest.json"):
        run_dirs.add(manifest_path.parent)
    for summary_path in input_dir.rglob("k6-summary.json"):
        run_dir = summary_path.parent.parent if summary_path.parent.name == "k6" else summary_path.parent
        run_dirs.add(run_dir)
    return sorted(run_dirs)


def build_run_row(input_dir: Path, run_dir: Path) -> dict[str, Any] | None:
    k6_summary = load_json(find_k6_summary(run_dir))
    manifest = load_json(run_dir / "manifest.json")
    if k6_summary is None and manifest is None:
        return None

    run_name = str((manifest or {}).get("run_id") or run_dir.name)
    name_parts = parse_run_name(run_name)
    rel_parts = run_dir.relative_to(input_dir).parts
    group = rel_parts[0] if len(rel_parts) > 1 else "."

    dataset = int_value((manifest or {}).get("dataset")) or name_parts.get("dataset")
    user_type = str((manifest or {}).get("user_type") or name_parts.get("user_type") or "unknown")
    vus = int_value((manifest or {}).get("vus")) or infer_vus(run_dir, input_dir, k6_summary)
    duration = str((manifest or {}).get("duration") or "")

    if dataset is None:
        return None

    row: dict[str, Any] = {
        "group": group,
        "run_id": run_name,
        "run_dir": str(run_dir),
        "dataset": dataset,
        "dataset_label": str(dataset),
        "user_type": user_type,
        "query_id": str((manifest or {}).get("query_id") or "all"),
        "vus": int(vus or 0),
        "vus_label": f"VUS {int(vus or 0)}",
        "duration": duration,
        "product_count": int_value((manifest or {}).get("product_count")),
        "target_product_count": int_value((manifest or {}).get("target_product_count")),
        "candidate_pool_limit": int_value((manifest or {}).get("candidate_pool_limit")),
        "cache_state": (manifest or {}).get("cache_state"),
        "bench_mode": (manifest or {}).get("bench_mode"),
        "k6_result_present": bool((manifest or {}).get("k6_result_present", k6_summary is not None)),
    }

    row.update(extract_k6_metrics(k6_summary))
    row.update(extract_k6_output_metrics(run_dir / "k6" / "k6-output.txt"))
    row.update(extract_backend_metrics(run_dir / "backend" / "backend.log"))
    row.update(extract_resource_metrics(run_dir / "resources" / "docker-stats.csv"))
    return row


def parse_run_name(run_name: str) -> dict[str, Any]:
    match = RUN_NAME_RE.match(run_name)
    if match is None:
        return {}
    return {
        "dataset": int(match.group("dataset")),
        "user_type": match.group("user_type"),
        "started_at": match.group("started_at"),
    }


def infer_vus(run_dir: Path, input_dir: Path, k6_summary: dict[str, Any] | None) -> int | None:
    for part in reversed(run_dir.relative_to(input_dir).parts):
        match = VUS_RE.search(part)
        if match is not None:
            return int(match.group("vus"))
    metric_vus = nested_get(k6_summary or {}, ["metrics", "vus", "max"])
    return int_value(metric_vus)


def find_k6_summary(run_dir: Path) -> Path:
    root_summary = run_dir / "k6-summary.json"
    if root_summary.exists():
        return root_summary
    return run_dir / "k6" / "k6-summary.json"


def extract_k6_metrics(summary: dict[str, Any] | None) -> dict[str, Any]:
    if summary is None:
        return {}
    metrics = summary.get("metrics") or {}
    duration_metric = (
        metrics.get("http_req_duration{type:recommendation}")
        or metrics.get("http_req_duration{expected_response:true}")
        or metrics.get("http_req_duration")
        or {}
    )
    failed_metric = metrics.get("http_req_failed") or {}
    reqs_metric = metrics.get("http_reqs") or {}
    iterations_metric = metrics.get("iterations") or {}
    checks_metric = metrics.get("checks") or {}

    total_http_rps = float_value(reqs_metric.get("rate"))
    recommendation_rps = float_value(iterations_metric.get("rate"))
    total_http_request_count = int_value(reqs_metric.get("count"))
    recommendation_request_count = int_value(iterations_metric.get("count"))
    total_http_failed_rate = float_value(failed_metric.get("value"))
    http_failed_count = count_from_rate(
        total_http_failed_rate,
        total_http_request_count,
    )
    check_failed_count = int_value(checks_metric.get("fails"))
    check_passed_count = int_value(checks_metric.get("passes"))
    recommendation_http_failed_rate = rate_from_counts(
        http_failed_count,
        recommendation_request_count,
    )
    check_failed_rate = rate_from_counts(
        check_failed_count,
        (check_failed_count or 0) + (check_passed_count or 0),
    )

    return {
        "latency_avg_ms": float_value(duration_metric.get("avg")),
        "latency_p50_ms": float_value(duration_metric.get("med")),
        "latency_p90_ms": float_value(duration_metric.get("p(90)")),
        "latency_p95_ms": float_value(duration_metric.get("p(95)")),
        "latency_max_ms": float_value(duration_metric.get("max")),
        # One benchmark iteration issues one recommendation request. Total HTTP
        # metrics also include setup logins for personalized users.
        "rps": recommendation_rps if recommendation_rps is not None else total_http_rps,
        "recommendation_rps": recommendation_rps,
        "total_http_rps": total_http_rps,
        "request_count": recommendation_request_count,
        "recommendation_request_count": recommendation_request_count,
        "total_http_request_count": total_http_request_count,
        "auth_request_count": (
            max(total_http_request_count - recommendation_request_count, 0)
            if total_http_request_count is not None and recommendation_request_count is not None
            else None
        ),
        "iteration_count": recommendation_request_count,
        "http_failed_count": http_failed_count,
        "http_req_failed_rate": recommendation_http_failed_rate,
        "recommendation_http_failed_rate": recommendation_http_failed_rate,
        "total_http_req_failed_rate": total_http_failed_rate,
        "check_success_rate": float_value(checks_metric.get("value")),
        "check_failed_count": check_failed_count,
        "check_failed_rate": check_failed_rate,
    }


def rate_from_counts(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def count_from_rate(rate: float | None, total: int | None) -> int | None:
    if rate is None or total is None or total < 0:
        return None
    return round(rate * total)


def extract_k6_output_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    failure_sample_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "recommendation_benchmark_failure_sample" in line:
            failure_sample_count += 1
    return {"k6_failure_sample_count": failure_sample_count}


def extract_backend_metrics(log_path: Path) -> dict[str, Any]:
    events = load_pipeline_events(log_path)
    if not events:
        return {}

    result: dict[str, Any] = {
        "pipeline_event_count": len(events),
    }

    numeric_keys = set()
    for event in events:
        for key, value in event.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_keys.add(key)

    for key in sorted(numeric_keys):
        values = [float(event[key]) for event in events if isinstance(event.get(key), (int, float))]
        if values:
            result[f"{key}_avg"] = round(statistics.mean(values), 2)
            result[f"{key}_p95"] = round(percentile(values, 95), 2)

    result.update(extract_nested_breakdown(events, "scoring_prefetch_breakdown", "prefetch"))
    result.update(extract_nested_breakdown(events, "scoring_prefetch_detail", "prefetch_detail"))
    result.update(extract_nested_breakdown(events, "score_loop_breakdown", "score_loop"))
    result.update(extract_nested_breakdown(events, "scoring_counts", "count"))
    for field_name in (
        "intent_rule_needs_llm",
        "intent_llm_attempted",
        "intent_llm_http_attempted",
        "intent_llm_used",
    ):
        result.update(extract_boolean_summary(events, field_name))
    result.update(extract_categorical_summary(events, "intent_llm_outcome"))
    result.update(extract_concern_parser_ai_metrics(log_path))
    return result


def load_pipeline_events(log_path: Path) -> list[dict[str, Any]]:
    return load_performance_events(log_path, {"recommendation_pipeline_completed"})


def load_performance_events(
    log_path: Path,
    event_names: set[str],
) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        json_start = line.find("{")
        if json_start < 0:
            continue
        try:
            event = json.loads(line[json_start:])
        except json.JSONDecodeError:
            continue
        if event.get("event") in event_names:
            events.append(event)
    return events


def extract_boolean_summary(
    events: list[dict[str, Any]],
    field_name: str,
) -> dict[str, Any]:
    values = [event[field_name] for event in events if isinstance(event.get(field_name), bool)]
    if not values:
        return {}
    true_count = sum(value is True for value in values)
    return {
        f"{field_name}_sample_count": len(values),
        f"{field_name}_true_count": true_count,
        f"{field_name}_true_rate": round(true_count / len(values), 6),
    }


def extract_categorical_summary(
    events: list[dict[str, Any]],
    field_name: str,
    *,
    output_prefix: str | None = None,
) -> dict[str, Any]:
    values = [
        str(event[field_name]).strip()
        for event in events
        if isinstance(event.get(field_name), str) and str(event[field_name]).strip()
    ]
    if not values:
        return {}

    prefix = output_prefix or field_name
    result: dict[str, Any] = {f"{prefix}_sample_count": len(values)}
    for value in sorted(set(values)):
        count = values.count(value)
        key = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "unknown"
        result[f"{prefix}_{key}_count"] = count
        result[f"{prefix}_{key}_rate"] = round(count / len(values), 6)
    return result


def extract_concern_parser_ai_metrics(log_path: Path) -> dict[str, Any]:
    events = [
        event
        for event in load_performance_events(
            log_path,
            {"ai_call_completed", "ai_call_failed"},
        )
        if event.get("operation") == "concern_parser"
    ]
    if not events:
        return {}

    durations = [
        float(event["duration_ms"])
        for event in events
        if isinstance(event.get("duration_ms"), (int, float))
    ]
    failed_count = sum(event.get("event") == "ai_call_failed" for event in events)
    result: dict[str, Any] = {
        "intent_ai_call_event_count": len(events),
        "intent_ai_call_failed_count": failed_count,
        "intent_ai_call_failed_rate": round(failed_count / len(events), 6),
    }
    if durations:
        result["intent_ai_call_duration_ms_avg"] = round(statistics.mean(durations), 2)
        result["intent_ai_call_duration_ms_p95"] = round(percentile(durations, 95), 2)
    result.update(
        extract_categorical_summary(
            events,
            "error",
            output_prefix="intent_ai_call_error",
        )
    )
    return result


def extract_nested_breakdown(
    events: list[dict[str, Any]],
    field_name: str,
    output_prefix: str,
) -> dict[str, Any]:
    keys: set[str] = set()
    for event in events:
        value = event.get(field_name)
        if isinstance(value, dict):
            keys.update(str(key) for key in value)

    result: dict[str, Any] = {}
    for key in sorted(keys):
        values = []
        for event in events:
            value = event.get(field_name)
            if isinstance(value, dict) and isinstance(value.get(key), (int, float)):
                values.append(float(value[key]))
        if values:
            result[f"{output_prefix}_{key}_avg"] = round(statistics.mean(values), 2)
            result[f"{output_prefix}_{key}_p95"] = round(percentile(values, 95), 2)
    return result


def extract_resource_metrics(path: Path) -> dict[str, Any]:
    rows = load_docker_stats_rows(path)
    if not rows:
        return {}

    result: dict[str, Any] = {}
    targets = {
        "backend": "backend",
        "elasticsearch": "elasticsearch",
        "redis": "redis",
    }
    for output_name, name_fragment in targets.items():
        matched = [
            row for row in rows
            if name_fragment in str(row.get("name", "")).lower()
        ]
        if not matched:
            continue
        cpu_values = [
            value for value in (parse_percent(row.get("cpu_percent")) for row in matched)
            if value is not None
        ]
        mem_percent_values = [
            value for value in (parse_percent(row.get("mem_percent")) for row in matched)
            if value is not None
        ]
        mem_used_values = [
            value for value in (parse_memory_used_mib(row.get("mem_usage")) for row in matched)
            if value is not None
        ]
        result.update(summarize_resource_values(cpu_values, f"resource_{output_name}_cpu_percent"))
        result.update(summarize_resource_values(mem_percent_values, f"resource_{output_name}_mem_percent"))
        result.update(summarize_resource_values(mem_used_values, f"resource_{output_name}_mem_used_mib"))
    return result


def load_docker_stats_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    ]
    if not lines:
        return []

    if lines[0].startswith("timestamp,"):
        reader = csv.DictReader(lines)
        return [
            {key: str(value or "") for key, value in row.items()}
            for row in reader
        ]

    rows: list[dict[str, str]] = []
    for line in lines:
        parts = [part.strip() for part in line.split(",", 3)]
        if len(parts) != 4:
            continue
        rows.append({
            "timestamp": "",
            "name": parts[0],
            "cpu_percent": parts[1],
            "mem_usage": parts[2],
            "mem_percent": parts[3],
        })
    return rows


def summarize_resource_values(values: list[float], prefix: str) -> dict[str, Any]:
    if not values:
        return {}
    return {
        f"{prefix}_avg": round(statistics.mean(values), 2),
        f"{prefix}_p95": round(percentile(values, 95), 2),
        f"{prefix}_max": round(max(values), 2),
    }


def parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    return float_value(text)


def parse_memory_used_mib(value: Any) -> float | None:
    if value is None:
        return None
    used_text = str(value).split("/", 1)[0].strip()
    return parse_memory_to_mib(used_text)


def parse_memory_to_mib(value: str) -> float | None:
    match = re.match(r"^(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[KMGT]?i?B)$", value.strip(), re.IGNORECASE)
    if match is None:
        return None
    number = float(match.group("number"))
    unit = match.group("unit").lower()
    factors = {
        "b": 1 / (1024 * 1024),
        "kb": 1 / 1024,
        "kib": 1 / 1024,
        "mb": 1,
        "mib": 1,
        "gb": 1024,
        "gib": 1024,
        "tb": 1024 * 1024,
        "tib": 1024 * 1024,
    }
    factor = factors.get(unit)
    if factor is None:
        return None
    return number * factor


def write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    keys: list[str] = []
    seen: set[str] = set()
    preferred = [
        "group",
        "run_id",
        "dataset",
        "user_type",
        "vus",
        "duration",
        "product_count",
        "latency_avg_ms",
        "latency_p50_ms",
        "latency_p90_ms",
        "latency_p95_ms",
        "latency_max_ms",
        "rps",
        "recommendation_rps",
        "total_http_rps",
        "http_req_failed_rate",
        "recommendation_http_failed_rate",
        "total_http_req_failed_rate",
        "check_failed_rate",
        "k6_failure_sample_count",
        "request_count",
        "total_http_request_count",
        "auth_request_count",
        "pipeline_event_count",
        "resource_backend_cpu_percent_max",
        "resource_backend_mem_percent_max",
        "resource_elasticsearch_cpu_percent_max",
        "resource_elasticsearch_mem_percent_max",
    ]
    for key in preferred:
        if any(key in row for row in rows):
            keys.append(key)
            seen.add(key)
    for row in rows:
        for key in row:
            if key not in seen:
                keys.append(key)
                seen.add(key)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_dict_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def metric_family(metric: str) -> str:
    if metric.startswith("intent_"):
        return "intent-parser"
    if metric.startswith(("score_", "scoring_", "coarse_", "exact_")):
        return "scoring"
    if metric in {key for key, _ in CONTEXT_LOAD_STAGES}:
        return "pipeline"
    if metric.startswith("prefetch_") or metric.startswith("behavior_"):
        return "data-loading"
    if metric.startswith("resource_"):
        return "guardrails"
    return "pipeline"


def build_instrumentation_coverage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = sorted(
        {
            key.rsplit("_", 1)[0]
            for row in rows
            for key in row
            if key.endswith(("_avg", "_p95"))
        }
    )
    coverage: list[dict[str, Any]] = []
    for metric in metrics:
        populated = sum(
            1
            for row in rows
            if row.get(f"{metric}_avg") is not None
            or row.get(f"{metric}_p95") is not None
        )
        total = len(rows)
        coverage.append(
            {
                "metric": metric,
                "family": metric_family(metric),
                "run_count": total,
                "populated_run_count": populated,
                "null_run_count": total - populated,
                "null_rate": (total - populated) / total if total else 0.0,
                "coverage_rate": populated / total if total else 0.0,
            }
        )
    return coverage


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_analysis_manifest(
    input_dir: Path,
    rows: list[dict[str, Any]],
    path: Path,
    *,
    stage_id: str,
    purpose: str,
) -> None:
    sources = []
    for row in sorted(rows, key=row_sort_key):
        run_dir = Path(str(row["run_dir"]))
        try:
            relative_dir = run_dir.relative_to(input_dir).as_posix()
        except ValueError:
            relative_dir = run_dir.as_posix()
        sources.append(
            {
                "run_id": row.get("run_id"),
                "relative_dir": relative_dir,
                "dataset": row.get("dataset"),
                "vus": row.get("vus"),
                "duration": row.get("duration"),
                "user_type": row.get("user_type"),
                "query_id": row.get("query_id"),
                "cache_state": row.get("cache_state"),
                "manifest_sha256": file_sha256(run_dir / "manifest.json"),
                "k6_summary_sha256": file_sha256(find_k6_summary(run_dir)),
                "backend_log_sha256": file_sha256(run_dir / "backend" / "backend.log"),
                "resource_log_sha256": file_sha256(
                    run_dir / "resources" / "docker-stats.csv"
                ),
            }
        )
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "analysis_purpose": purpose,
        "stage_id": stage_id,
        "input_dir": input_dir.as_posix(),
        "run_count": len(sources),
        "run_ids": [source["run_id"] for source in sources],
        "execution_conditions": [
            {
                "dataset": source["dataset"],
                "vus": source["vus"],
                "duration": source["duration"],
                "user_type": source["user_type"],
                "query_id": source["query_id"],
                "cache_state": source["cache_state"],
            }
            for source in sources
        ],
        "output_layout": ANALYSIS_SUBDIRS,
        "sources": sources,
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def representative_analysis_row(
    rows: list[dict[str, Any]],
    *,
    dataset: int,
    vus: int,
    preferred_run_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("dataset") == dataset and row.get("vus") == vus
    ]
    preferred = set(preferred_run_ids or [])
    if preferred:
        headline_candidates = [
            row for row in candidates if str(row.get("run_id")) in preferred
        ]
        if headline_candidates:
            candidates = headline_candidates
    if not candidates:
        return None

    measured = [
        row
        for row in candidates
        if numeric_or_none(row.get("latency_p95_ms")) is not None
    ]
    if measured:
        median_p95 = statistics.median(
            float(row["latency_p95_ms"]) for row in measured
        )
        return min(
            measured,
            key=lambda row: (
                abs(float(row["latency_p95_ms"]) - median_p95),
                str(row.get("run_id") or ""),
            ),
        )
    return max(candidates, key=lambda row: str(row.get("run_id") or ""))


def stage_headline_run_ids(stage_context: dict[str, Any]) -> list[str]:
    stage = stage_context.get("stage") or {}
    return [str(run_id) for run_id in stage.get("headline_run_ids", []) if run_id]


def write_analysis_readme(
    path: Path,
    rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    *,
    stage_id: str,
    purpose: str,
    stage_context: dict[str, Any],
    stage_dataset: int,
    stage_vus: int,
) -> None:
    row = representative_analysis_row(
        rows,
        dataset=stage_dataset,
        vus=stage_vus,
        preferred_run_ids=stage_headline_run_ids(stage_context),
    )
    pipeline_records = build_stage_records(row or {}, PIPELINE_STAGES, statistic="avg")
    bottleneck = max(pipeline_records, key=lambda item: item["value"], default=None)
    detailed_stages = (
        INTENT_STAGES
        + INTENT_LLM_STAGES
        + PURCHASE_PARSER_STAGES
        + scoring_stages_for_row(row or {})
        + SCORE_LOOP_DETAIL_STAGES
        + BEHAVIOR_SIGNAL_DETAIL_STAGES
        + INGREDIENT_EFFECT_DETAIL_STAGES
    )
    cause_records = build_stage_records(row or {}, detailed_stages, statistic="avg")
    cause = max(cause_records, key=lambda item: item["value"], default=None)
    scoring_records = build_stage_records(
        row or {},
        scoring_stages_for_row(row or {}),
        statistic="avg",
    )
    scoring_bottleneck = max(
        scoring_records,
        key=lambda item: item["value"],
        default=None,
    )
    coarse_metrics = build_coarse_top50_metrics(row or {})
    missing = [
        item["metric"]
        for item in coverage_rows
        if item["null_rate"] == 1.0
    ][:8]
    populated_families = sorted(
        {
            item["family"]
            for item in coverage_rows
            if item["populated_run_count"] > 0
        }
    )
    stage = stage_context.get("stage") or {}
    next_stage = stage_context.get("next_stage")
    if next_stage:
        next_optimization = next_stage.get("change", next_stage.get("label", "-"))
        transition_link = f"../../../transitions/{next_stage['id']}/README.md"
    else:
        next_optimization = stage.get(
            "next_bottleneck",
            "후속 최적화는 다음 측정 결과를 확인한 뒤 선택한다.",
        )
        transition_link = "후속 transition 없음"
    datasets = sorted({row.get("dataset") for row in rows if row.get("dataset")})
    vus_values = sorted({row.get("vus") for row in rows if row.get("vus")})
    lines = [
        f"# {stage.get('label', stage_id)} 로컬 분석",
        "",
        f"> 목적: {purpose}",
        "",
        "## 1. 전체 성능",
        "",
        f"- 원본 run: {len(rows)}건",
        f"- dataset: {', '.join(map(str, datasets)) or '-'}",
        f"- VUS: {', '.join(map(str, vus_values)) or '-'}",
    ]
    if row:
        lines.extend(
            [
                f"- 기준 조건: dataset {stage_dataset}, VUS {stage_vus}",
                f"- p95: {float(row.get('latency_p95_ms') or 0) / 1000:.3f}초",
                f"- RPS: {float(row.get('recommendation_rps') or row.get('rps') or 0):.3f}",
            ]
        )
    lines.extend(
        [
            "",
            "## 2. 큰 파이프라인 병목",
            "",
            (
                f"평균 기준 가장 큰 구간은 `{bottleneck['stage']}` "
                f"({bottleneck['value']:.2f}ms)이다."
                if bottleneck
                else "해당 조건에 pipeline stage 표본이 없다."
            ),
            "",
            "## 3. 기존 로그의 부족한 부분",
            "",
            (
                "모든 run에서 비어 있는 대표 metric: " + ", ".join(f"`{item}`" for item in missing)
                if missing
                else "분석 대상 metric에서 전체 누락 필드는 확인되지 않았다."
            ),
            "",
            "## 4. 추가한 세부 계측",
            "",
            "관측 가능한 metric 계열: "
            + ", ".join(f"`{family}`" for family in populated_families),
            "",
            "## 5. 확인한 실제 원인",
            "",
            (
                f"현재 세부 계측에서 가장 큰 구간은 `{cause['stage']}` "
                f"({cause['value']:.2f}ms)이다."
                if cause
                else "세부 원인을 확정할 표본이 부족하다."
            ),
            (
                f"Scoring 내부의 가장 큰 구간은 `{scoring_bottleneck['stage']}` "
                f"({scoring_bottleneck['value']:.2f}ms)이다."
                if scoring_bottleneck
                else "Scoring 내부 표본이 없다."
            ),
            (
                "Opt4c는 coarse 후보 "
                f"{coarse_metrics['coarse_candidate_count_avg']:.1f}개 중 "
                f"{coarse_metrics['exact_shortlist_size_avg']:.1f}개만 exact 경로로 보내 "
                f"상세 계산 대상을 {coarse_metrics['candidate_reduction_rate'] * 100:.1f}% 줄였다."
                if coarse_metrics
                else ""
            ),
            "",
            "## 6. 선택한 다음 최적화",
            "",
            next_optimization,
            "",
            "## 7. 대응하는 transition 결과",
            "",
            f"- {transition_link}" if transition_link.endswith(".md") else transition_link,
            "",
            "원본 목록과 해시는 [analysis-manifest.json](./data/analysis-manifest.json), "
            "계측 커버리지는 [instrumentation-coverage.csv](./data/instrumentation-coverage.csv)에서 확인한다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def plot_instrumentation_coverage(rows, path: Path, plt, sns) -> None:
    if not rows:
        return
    family_values: dict[str, list[float]] = {}
    for row in rows:
        family_values.setdefault(row["family"], []).append(row["coverage_rate"] * 100)
    labels = sorted(family_values)
    values = [statistics.mean(family_values[label]) for label in labels]
    fig, axis = plt.subplots(figsize=(10, 5.5))
    sns.barplot(x=values, y=labels, orient="h", color="#2563EB", ax=axis)
    axis.set_xlim(0, 100)
    axis.set_xlabel("average run coverage (%)")
    axis.set_ylabel("")
    axis.set_title("instrumentation coverage by metric family")
    for index, value in enumerate(values):
        axis.text(value + 1, index, f"{value:.1f}%", va="center", fontsize=10)
    save_figure(fig, path, plt)


def plot_summary_graphs(df, output_dirs: dict[str, Path], plt, sns) -> None:
    output_dir = output_dirs["summary"]
    plot_line(
        df,
        output_dir / "latency_p95_by_dataset.png",
        x="dataset_label",
        y="latency_p95_ms",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="p95 latency (ms)",
        title="p95 latency by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "latency_p95_by_vus.png",
        x="vus",
        y="latency_p95_ms",
        hue="dataset_label",
        xlabel="virtual users",
        ylabel="p95 latency (ms)",
        title="p95 latency by VUS",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "latency_avg_by_dataset.png",
        x="dataset_label",
        y="latency_avg_ms",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="average latency (ms)",
        title="average latency by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "rps_by_dataset.png",
        x="dataset_label",
        y="rps",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="requests per second",
        title="RPS by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "rps_by_vus.png",
        x="vus",
        y="rps",
        hue="dataset_label",
        xlabel="virtual users",
        ylabel="recommendation requests per second",
        title="recommendation RPS by VUS",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "http_failure_percent_by_dataset.png",
        x="dataset_label",
        y="recommendation_http_failed_percent",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="recommendation HTTP failures (%)",
        title="recommendation HTTP failure rate by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "check_failure_percent_by_dataset.png",
        x="dataset_label",
        y="check_failed_percent",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="failed response checks (%)",
        title="response check failure rate by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dirs["guardrails"] / "backend_cpu_peak_by_dataset.png",
        x="dataset_label",
        y="resource_backend_cpu_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="backend CPU peak (%; 100% = one core)",
        title="backend CPU peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dirs["guardrails"] / "backend_memory_peak_by_dataset.png",
        x="dataset_label",
        y="resource_backend_mem_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="backend memory peak (%)",
        title="backend memory peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dirs["guardrails"] / "elasticsearch_cpu_peak_by_dataset.png",
        x="dataset_label",
        y="resource_elasticsearch_cpu_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="Elasticsearch CPU peak (%; 100% = one core)",
        title="Elasticsearch CPU peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dirs["guardrails"] / "elasticsearch_memory_peak_by_dataset.png",
        x="dataset_label",
        y="resource_elasticsearch_mem_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="Elasticsearch memory peak (%)",
        title="Elasticsearch memory peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_matrix_heatmap(
        df,
        output_dir / "latency_p95_matrix.png",
        value="latency_p95_ms",
        title="p95 latency matrix",
        colorbar_label="p95 latency (ms)",
        value_format=lambda value: f"{value:,.0f}",
        cmap="YlOrRd",
        plt=plt,
        sns=sns,
    )
    plot_matrix_heatmap(
        df,
        output_dir / "rps_matrix.png",
        value="rps",
        title="recommendation RPS matrix",
        colorbar_label="requests per second",
        value_format=lambda value: f"{value:.2f}",
        cmap="YlGnBu",
        plt=plt,
        sns=sns,
    )


def plot_stage_graphs(
    df,
    output_dirs: dict[str, Path],
    plt,
    sns,
    *,
    stage_dataset: int,
    stage_vus: int,
    stage_context: dict[str, Any],
) -> None:
    row = representative_analysis_row(
        df.to_dict("records"),
        dataset=stage_dataset,
        vus=stage_vus,
        preferred_run_ids=stage_headline_run_ids(stage_context),
    )
    if row is None:
        return
    scope = f"{stage_dataset:,} products / VUS {stage_vus}"
    summary_dir = output_dirs["summary"]
    execution_flow_dir = output_dirs["execution_flow"]
    persistence_dir = output_dirs["persistence"]
    pipeline_dir = output_dirs["pipeline"]
    intent_dir = output_dirs["intent"]
    scoring_dir = output_dirs["scoring"]
    data_loading_dir = output_dirs["data_loading"]
    guardrails_dir = output_dirs["guardrails"]
    scoring_stages = scoring_stages_for_row(row)

    write_execution_flow_report(
        row,
        execution_flow_dir,
        output_dirs["data"],
        stage_context=stage_context,
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )
    write_persistence_drilldown_report(
        row,
        persistence_dir,
        output_dirs["data"],
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )

    plot_stage_bar(
        row,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_ratio_bar(
        row,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_ratio_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage share of average latency ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_donut(
        row,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage share ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_pareto(
        row,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_pareto_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline bottleneck Pareto ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_composition_by_vus(
        df,
        PIPELINE_STAGES,
        pipeline_dir / f"pipeline_stage_share_by_vus_{stage_dataset}.png",
        stage_dataset=stage_dataset,
        plt=plt,
        sns=sns,
    )
    plot_stage_share_comparison(
        df,
        PIPELINE_STAGES,
        pipeline_dir
        / (
            f"pipeline_stage_share_compare_1000_vs_{stage_dataset}"
            f"_vus{stage_vus:02d}.png"
        ),
        datasets=[1000, stage_dataset],
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )
    plot_stage_bar(
        row,
        scoring_stages,
        scoring_dir / f"scoring_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        scoring_stages,
        scoring_dir / f"scoring_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_donut(
        row,
        scoring_stages,
        scoring_dir / f"scoring_stage_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage share ({scope})",
        plt,
        sns,
        statistic="avg",
        max_segments=len(scoring_stages),
        min_share_percent=0,
    )
    prefetch_columns = [
        (f"prefetch_{field}", label)
        for field, label in SCORING_PREFETCH_FIELDS
    ]
    plot_stage_bar(
        row,
        prefetch_columns,
        data_loading_dir / f"scoring_prefetch_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring prefetch average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        prefetch_columns,
        data_loading_dir / f"scoring_prefetch_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring prefetch p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        BEHAVIOR_SIGNAL_DETAIL_STAGES,
        data_loading_dir / f"behavior_signal_detail_{stage_dataset}_vus{stage_vus:02d}.png",
        f"behavior signal prefetch detail ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        BEHAVIOR_SIGNAL_DETAIL_STAGES,
        data_loading_dir / f"behavior_signal_detail_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"behavior signal prefetch detail p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        INGREDIENT_EFFECT_DETAIL_STAGES,
        data_loading_dir / f"ingredient_effect_detail_{stage_dataset}_vus{stage_vus:02d}.png",
        f"ingredient effect prefetch detail ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        INGREDIENT_EFFECT_DETAIL_STAGES,
        data_loading_dir / f"ingredient_effect_detail_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"ingredient effect prefetch detail p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        SCORE_LOOP_DETAIL_STAGES,
        scoring_dir / f"score_loop_detail_{stage_dataset}_vus{stage_vus:02d}.png",
        f"candidate score loop detail ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        SCORE_LOOP_DETAIL_STAGES,
        scoring_dir / f"score_loop_detail_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"candidate score loop detail p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_donut(
        row,
        SCORE_LOOP_DETAIL_STAGES,
        scoring_dir / f"score_loop_detail_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"candidate score loop measured share ({scope})",
        plt,
        sns,
        statistic="avg",
        max_segments=len(SCORE_LOOP_DETAIL_STAGES),
        min_share_percent=0,
    )
    plot_stage_bar(
        row,
        CONTEXT_LOAD_STAGES,
        pipeline_dir / f"context_load_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"personalization context average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        CONTEXT_LOAD_STAGES,
        pipeline_dir / f"context_load_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"personalization context p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        INTENT_STAGES,
        intent_dir / f"intent_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"intent parser average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        INTENT_STAGES,
        intent_dir / f"intent_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"intent parser p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        INTENT_LLM_STAGES,
        intent_dir / f"intent_llm_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser detail average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_donut(
        row,
        INTENT_LLM_STAGES,
        intent_dir / f"intent_llm_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser measured share ({scope})",
        plt,
        sns,
        statistic="avg",
        max_segments=len(INTENT_LLM_STAGES),
        min_share_percent=0,
    )
    plot_intent_outcomes(
        row,
        intent_dir / f"intent_llm_outcomes_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser outcomes ({scope})",
        plt,
        sns,
    )
    plot_intent_detail_graphs(
        row,
        intent_dir,
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )
    plot_client_vs_backend_p95(
        df,
        pipeline_dir / f"client_vs_backend_p95_{stage_dataset}.png",
        stage_dataset=stage_dataset,
        plt=plt,
    )
    plot_resource_timeseries(
        row,
        guardrails_dir,
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
    )
    plot_optimization_timeline(
        df,
        summary_dir / f"optimization_timeline_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )


def uses_coarse_top50_scoring(row: dict[str, Any]) -> bool:
    return any(
        numeric_or_none(row.get(f"{metric}_{statistic}")) is not None
        for metric in ("coarse_feature_query_ms", "coarse_score_loop_ms")
        for statistic in ("avg", "p95")
    )


def scoring_stages_for_row(row: dict[str, Any]) -> list[tuple[str, str]]:
    if uses_coarse_top50_scoring(row):
        return COARSE_TOP50_SCORING_STAGES
    return SCORING_STAGES


def scoring_detail_parent_ids(row: dict[str, Any]) -> tuple[str, str]:
    if uses_coarse_top50_scoring(row):
        return "exact_prefetch_ms", "exact_score_loop_ms"
    return "scoring_data_prefetch_ms", "score_loop_ms"


def build_execution_flow_records(row) -> list[dict[str, Any]]:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    pipeline_ms = numeric_or_none(row.get("duration_ms_avg")) or 0.0
    source_run_id = str(row.get("run_id") or "")
    records = [
        {
            "level": 0,
            "parent_id": "",
            "parent": "",
            "sequence": 0,
            "component_id": "end_to_end",
            "component": "end-to-end HTTP",
            "source_metric": "latency_avg_ms",
            "value_ms": e2e_ms,
            "parent_ms": e2e_ms,
            "parent_share_percent": 100.0,
            "e2e_share_percent": 100.0,
            "cumulative_start_ms": 0.0,
            "cumulative_end_ms": e2e_ms,
            "source_run_id": source_run_id,
        }
    ]

    append_execution_children(
        records,
        parent_id="end_to_end",
        parent_label="end-to-end HTTP",
        parent_ms=e2e_ms,
        level=1,
        children=[
            ("backend_pipeline", "backend pipeline", "duration_ms_avg", pipeline_ms),
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
        residual_id="outside_pipeline",
        residual_label="outside pipeline / uninstrumented",
    )
    append_execution_children(
        records,
        parent_id="backend_pipeline",
        parent_label="backend pipeline",
        parent_ms=pipeline_ms,
        level=2,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in PIPELINE_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    scoring_ms = numeric_or_none(row.get("scoring_ms_avg")) or 0.0
    scoring_stages = scoring_stages_for_row(row)
    append_execution_children(
        records,
        parent_id="scoring_ms",
        parent_label="scoring",
        parent_ms=scoring_ms,
        level=3,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in scoring_stages
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    prefetch_parent_id, score_loop_parent_id = scoring_detail_parent_ids(row)
    prefetch_ms = numeric_or_none(row.get(f"{prefetch_parent_id}_avg")) or 0.0
    append_execution_children(
        records,
        parent_id=prefetch_parent_id,
        parent_label=(
            "exact top-50 prefetch"
            if prefetch_parent_id == "exact_prefetch_ms"
            else "data prefetch"
        ),
        parent_ms=prefetch_ms,
        level=4,
        children=[
            (
                f"prefetch_{field}",
                label,
                f"prefetch_{field}_avg",
                numeric_or_none(row.get(f"prefetch_{field}_avg")) or 0.0,
            )
            for field, label in SCORING_PREFETCH_FIELDS
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    score_loop_ms = numeric_or_none(row.get(f"{score_loop_parent_id}_avg")) or 0.0
    append_execution_children(
        records,
        parent_id=score_loop_parent_id,
        parent_label=(
            "exact top-50 score loop"
            if score_loop_parent_id == "exact_score_loop_ms"
            else "score loop"
        ),
        parent_ms=score_loop_ms,
        level=4,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in SCORE_LOOP_DETAIL_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    intent_ms = numeric_or_none(row.get("intent_parse_ms_avg")) or 0.0
    append_execution_children(
        records,
        parent_id="intent_parse_ms",
        parent_label="intent",
        parent_ms=intent_ms,
        level=3,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in INTENT_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    llm_ms = numeric_or_none(row.get("intent_llm_call_ms_avg")) or 0.0
    append_execution_children(
        records,
        parent_id="intent_llm_call_ms",
        parent_label="LLM parser",
        parent_ms=llm_ms,
        level=4,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in INTENT_LLM_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )

    append_execution_children(
        records,
        parent_id="run_save_ms",
        parent_label="recommendation run save",
        parent_ms=numeric_or_none(row.get("run_save_ms_avg")) or 0.0,
        level=3,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in RUN_SAVE_DETAIL_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )
    append_execution_children(
        records,
        parent_id="search_candidate_save_ms",
        parent_label="candidate trace save",
        parent_ms=(
            numeric_or_none(row.get("search_candidate_save_ms_avg")) or 0.0
        ),
        level=3,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in CANDIDATE_SAVE_DETAIL_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )
    append_execution_children(
        records,
        parent_id="result_save_ms",
        parent_label="result and evidence save",
        parent_ms=numeric_or_none(row.get("result_save_ms_avg")) or 0.0,
        level=3,
        children=[
            (
                key,
                label,
                f"{key}_avg",
                numeric_or_none(row.get(f"{key}_avg")) or 0.0,
            )
            for key, label in RESULT_SAVE_DETAIL_STAGES
        ],
        e2e_ms=e2e_ms,
        source_run_id=source_run_id,
    )
    return records


def append_execution_children(
    records: list[dict[str, Any]],
    *,
    parent_id: str,
    parent_label: str,
    parent_ms: float,
    level: int,
    children: list[tuple[str, str, str, float]],
    e2e_ms: float,
    source_run_id: str,
    residual_id: str = "unattributed",
    residual_label: str = "other / unattributed",
) -> None:
    positive_children = [child for child in children if child[3] > 0]
    child_total = sum(child[3] for child in positive_children)
    residual = max(parent_ms - child_total, 0.0)
    if residual > 0.005:
        positive_children.append(
            (residual_id, residual_label, "derived_parent_minus_children", residual)
        )

    cumulative = 0.0
    for sequence, (component_id, label, metric, value_ms) in enumerate(
        positive_children,
        start=1,
    ):
        records.append(
            {
                "level": level,
                "parent_id": parent_id,
                "parent": parent_label,
                "sequence": sequence,
                "component_id": component_id,
                "component": label,
                "source_metric": metric,
                "value_ms": value_ms,
                "parent_ms": parent_ms,
                "parent_share_percent": (
                    value_ms / parent_ms * 100 if parent_ms > 0 else 0.0
                ),
                "e2e_share_percent": value_ms / e2e_ms * 100 if e2e_ms > 0 else 0.0,
                "cumulative_start_ms": cumulative,
                "cumulative_end_ms": cumulative + value_ms,
                "source_run_id": source_run_id,
            }
        )
        cumulative += value_ms


def execution_flow_children(
    records: list[dict[str, Any]],
    parent_id: str,
) -> list[dict[str, Any]]:
    return [record for record in records if record["parent_id"] == parent_id]


def build_snapshot_read_model_metrics(row) -> dict[str, Any] | None:
    instrumentation_values = [
        numeric_or_none(row.get(f"{field}_avg"))
        for field in SNAPSHOT_READ_MODEL_FIELDS
    ]
    if not any(value is not None and value > 0 for value in instrumentation_values):
        return None

    hit_count = numeric_or_none(row.get("scoring_snapshot_hit_count_avg")) or 0.0
    miss_count = numeric_or_none(row.get("scoring_snapshot_miss_count_avg")) or 0.0
    candidate_count = hit_count + miss_count
    hit_rate = (
        round(hit_count / candidate_count, 6) if candidate_count > 0 else 0.0
    )
    miss_rate = (
        round(miss_count / candidate_count, 6) if candidate_count > 0 else 0.0
    )
    return {
        "source_run_id": str(row.get("run_id") or ""),
        "snapshot_load_avg_ms": (
            numeric_or_none(row.get("scoring_snapshot_load_ms_avg")) or 0.0
        ),
        "snapshot_load_p95_ms": (
            numeric_or_none(row.get("scoring_snapshot_load_ms_p95")) or 0.0
        ),
        "snapshot_fallback_avg_ms": (
            numeric_or_none(row.get("scoring_snapshot_fallback_ms_avg")) or 0.0
        ),
        "snapshot_fallback_p95_ms": (
            numeric_or_none(row.get("scoring_snapshot_fallback_ms_p95")) or 0.0
        ),
        "snapshot_hit_count_avg": hit_count,
        "snapshot_miss_count_avg": miss_count,
        "snapshot_candidate_count_avg": candidate_count,
        "snapshot_hit_rate": hit_rate,
        "snapshot_miss_rate": miss_rate,
        "snapshot_parse_error_count_avg": (
            numeric_or_none(row.get("scoring_snapshot_parse_error_count_avg"))
            or 0.0
        ),
        "snapshot_parse_error_count_p95": (
            numeric_or_none(row.get("scoring_snapshot_parse_error_count_p95"))
            or 0.0
        ),
    }


def build_coarse_top50_metrics(row) -> dict[str, Any] | None:
    if not uses_coarse_top50_scoring(row):
        return None

    row_count = numeric_or_none(row.get("coarse_feature_row_count_avg")) or 0.0
    hit_count = numeric_or_none(row.get("coarse_feature_hit_count_avg")) or 0.0
    miss_count = numeric_or_none(row.get("coarse_feature_miss_count_avg")) or 0.0
    stale_count = numeric_or_none(row.get("coarse_feature_stale_count_avg")) or 0.0
    shortlist_size = numeric_or_none(row.get("coarse_shortlist_size_avg")) or 0.0
    feature_count = hit_count + miss_count
    denominator = feature_count or row_count

    return {
        "source_run_id": str(row.get("run_id") or ""),
        "coarse_candidate_count_avg": row_count,
        "exact_shortlist_size_avg": shortlist_size,
        "exact_candidate_ratio": (
            round(shortlist_size / row_count, 6) if row_count > 0 else 0.0
        ),
        "candidate_reduction_rate": (
            round(1.0 - shortlist_size / row_count, 6) if row_count > 0 else 0.0
        ),
        "feature_hit_rate": (
            round(hit_count / denominator, 6) if denominator > 0 else 0.0
        ),
        "feature_miss_rate": (
            round(miss_count / denominator, 6) if denominator > 0 else 0.0
        ),
        "feature_stale_rate": (
            round(stale_count / denominator, 6) if denominator > 0 else 0.0
        ),
        "feature_fallback_ratio": (
            numeric_or_none(row.get("coarse_feature_fallback_ratio_avg")) or 0.0
        ),
        "legacy_fallback_count_avg": (
            numeric_or_none(row.get("legacy_fallback_count_avg")) or 0.0
        ),
        "coarse_feature_query_avg_ms": (
            numeric_or_none(row.get("coarse_feature_query_ms_avg")) or 0.0
        ),
        "coarse_feature_query_p95_ms": (
            numeric_or_none(row.get("coarse_feature_query_ms_p95")) or 0.0
        ),
        "coarse_score_loop_avg_ms": (
            numeric_or_none(row.get("coarse_score_loop_ms_avg")) or 0.0
        ),
        "coarse_score_loop_p95_ms": (
            numeric_or_none(row.get("coarse_score_loop_ms_p95")) or 0.0
        ),
        "exact_prefetch_avg_ms": (
            numeric_or_none(row.get("exact_prefetch_ms_avg")) or 0.0
        ),
        "exact_prefetch_p95_ms": (
            numeric_or_none(row.get("exact_prefetch_ms_p95")) or 0.0
        ),
        "exact_score_loop_avg_ms": (
            numeric_or_none(row.get("exact_score_loop_ms_avg")) or 0.0
        ),
        "exact_score_loop_p95_ms": (
            numeric_or_none(row.get("exact_score_loop_ms_p95")) or 0.0
        ),
    }


def write_execution_flow_report(
    row,
    output_dir: Path,
    data_dir: Path,
    *,
    stage_context: dict[str, Any],
    stage_dataset: int,
    stage_vus: int,
    plt,
    sns,
) -> None:
    records = build_execution_flow_records(row)
    if not records:
        return
    snapshot_metrics = build_snapshot_read_model_metrics(row)
    coarse_metrics = build_coarse_top50_metrics(row)

    write_dict_csv(records, data_dir / "execution-flow-timings.csv")
    basis = {
        "source_run_id": str(row.get("run_id") or ""),
        "headline_run_ids": ";".join(stage_headline_run_ids(stage_context)),
        "selection_rule": "headline run nearest to median p95",
        "dataset": stage_dataset,
        "actual_product_count": int_value(row.get("product_count")),
        "vus": stage_vus,
        "duration": str(row.get("duration") or ""),
        "user_type": str(row.get("user_type") or ""),
        "latency_avg_ms": numeric_or_none(row.get("latency_avg_ms")),
        "latency_p95_ms": numeric_or_none(row.get("latency_p95_ms")),
        "pipeline_avg_ms": numeric_or_none(row.get("duration_ms_avg")),
        "llm_attempt_rate": numeric_or_none(row.get("intent_llm_attempted_true_rate")),
    }
    write_dict_csv([basis], data_dir / "execution-flow-basis.csv")
    if snapshot_metrics is not None:
        write_dict_csv(
            [snapshot_metrics],
            data_dir / "snapshot-read-model-metrics.csv",
        )
    if coarse_metrics is not None:
        write_dict_csv(
            [coarse_metrics],
            data_dir / "coarse-top50-metrics.csv",
        )

    plot_execution_hierarchy_rings(
        row,
        records,
        output_dir / "01-execution-hierarchy-rings.png",
        plt,
        sns,
    )
    plot_pipeline_sequence(
        row,
        records,
        output_dir / "02-pipeline-sequence.png",
        plt,
        sns,
    )
    plot_scoring_drilldown(
        row,
        records,
        output_dir / "03-scoring-drilldown.png",
        plt,
        sns,
    )
    plot_intent_drilldown(
        row,
        records,
        output_dir / "04-intent-drilldown.png",
        plt,
        sns,
    )
    if snapshot_metrics is not None:
        plot_snapshot_read_model(
            snapshot_metrics,
            output_dir / "05-snapshot-read-model.png",
            plt,
        )
    if coarse_metrics is not None:
        plot_coarse_top50_guardrails(
            coarse_metrics,
            output_dir / "05-coarse-top50-guardrails.png",
            plt,
        )
    plot_bottleneck_paths(
        row,
        records,
        output_dir / "06-bottleneck-paths.png",
        plt,
        sns,
    )
    plot_execution_flow_table(
        row,
        records,
        output_dir / "07-timing-table.png",
        plt,
    )
    write_execution_flow_readme(
        output_dir / "README.md",
        row,
        records,
        basis,
        snapshot_metrics=snapshot_metrics,
        coarse_metrics=coarse_metrics,
    )


def persistence_detail_groups() -> list[tuple[str, str, list[tuple[str, str]]]]:
    return [
        ("run_save_ms", "recommendation run save", RUN_SAVE_DETAIL_STAGES),
        (
            "search_candidate_save_ms",
            "candidate trace save",
            CANDIDATE_SAVE_DETAIL_STAGES,
        ),
        ("result_save_ms", "result and evidence save", RESULT_SAVE_DETAIL_STAGES),
    ]


def has_persistence_detail(row: dict[str, Any]) -> bool:
    return any(
        numeric_or_none(row.get(f"{key}_avg")) is not None
        for _, _, stages in persistence_detail_groups()
        for key, _ in stages
    )


def write_persistence_drilldown_report(
    row: dict[str, Any],
    output_dir: Path,
    data_dir: Path,
    *,
    stage_dataset: int,
    stage_vus: int,
    plt,
    sns,
) -> None:
    if not has_persistence_detail(row):
        return

    records = build_execution_flow_records(row)
    top_level_records = build_stage_records(row, PERSISTENCE_STAGES, statistic="avg")
    detail_records = [
        record
        for parent_id, _, _ in persistence_detail_groups()
        for record in execution_flow_children(records, parent_id)
    ]
    if not detail_records:
        return

    source_run_id = str(row.get("run_id") or "")
    persistence_rows = []
    for record in detail_records:
        metric = str(record["component_id"])
        persistence_rows.append(
            {
                **record,
                "p95_ms": numeric_or_none(row.get(f"{metric}_p95")),
            }
        )
    top_level_rows = []
    for metric, label in PERSISTENCE_STAGES:
        average = numeric_or_none(row.get(f"{metric}_avg"))
        if average is None or average <= 0:
            continue
        top_level_rows.append(
            {
                "component_id": metric,
                "component": label,
                "average_ms": average,
                "p95_ms": numeric_or_none(row.get(f"{metric}_p95")),
                "http_share_percent": (
                    average
                    / (numeric_or_none(row.get("latency_avg_ms")) or 1.0)
                    * 100
                ),
            }
        )
    write_dict_csv(top_level_rows, data_dir / "persistence-stage-summary.csv")
    write_dict_csv(persistence_rows, data_dir / "persistence-drilldown-timings.csv")
    write_dict_csv(
        [
            {
                "source_run_id": source_run_id,
                "dataset": stage_dataset,
                "actual_product_count": int_value(row.get("product_count")),
                "vus": stage_vus,
                "duration": str(row.get("duration") or ""),
                "user_type": str(row.get("user_type") or ""),
                "latency_avg_ms": numeric_or_none(row.get("latency_avg_ms")),
                "latency_p95_ms": numeric_or_none(row.get("latency_p95_ms")),
                "pipeline_avg_ms": numeric_or_none(row.get("duration_ms_avg")),
                "pipeline_event_count": int_value(row.get("pipeline_event_count")),
            }
        ],
        data_dir / "persistence-drilldown-basis.csv",
    )

    scope = f"{stage_dataset:,} products / VUS {stage_vus}"
    plot_stage_bar(
        row,
        PERSISTENCE_STAGES,
        output_dir / "01-persistence-stage-average.png",
        f"persistence and response stages average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        PERSISTENCE_STAGES,
        output_dir / "02-persistence-stage-p95.png",
        f"persistence and response stages p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_persistence_hierarchy(
        records,
        output_dir / "03-persistence-hierarchy.png",
        plt,
    )
    plot_persistence_detail_distribution(
        row,
        output_dir / "04-persistence-detail-average-vs-p95.png",
        plt,
        sns,
    )
    write_persistence_drilldown_readme(
        output_dir / "README.md",
        row,
        records,
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
    )


def persistence_stage_markdown_table(row: dict[str, Any]) -> list[str]:
    records = [
        (key, label, numeric_or_none(row.get(f"{key}_avg")))
        for key, label in PERSISTENCE_STAGES
    ]
    records = [record for record in records if record[2] is not None and record[2] > 0]
    if not records:
        return ["측정값이 없습니다."]
    lines = [
        "| 구간 | 평균(ms) | p95(ms) | HTTP 평균 대비 |",
        "|---|---:|---:|---:|",
    ]
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    for metric, label, measured_value in records:
        value = float(measured_value)
        p95 = numeric_or_none(row.get(f"{metric}_p95"))
        p95_text = f"{p95:,.2f}" if p95 is not None else "-"
        lines.append(
            f"| {label} | {value:,.2f} | "
            f"{p95_text} | {value / e2e_ms * 100 if e2e_ms else 0:.1f}% |"
        )
    return lines


def write_persistence_drilldown_readme(
    path: Path,
    row: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    stage_dataset: int,
    stage_vus: int,
) -> None:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    pipeline_ms = numeric_or_none(row.get("duration_ms_avg")) or 0.0
    candidate_save_ms = numeric_or_none(row.get("search_candidate_save_ms_avg")) or 0.0
    lines = [
        "# 추천 API 저장 단계 드릴다운",
        "",
        f"- 대표 run: `{row.get('run_id', '')}`",
        f"- 조건: 실제 상품 {int_value(row.get('product_count')) or 0:,}개, "
        f"VUS {stage_vus}, {row.get('duration', '')}, `{row.get('user_type', '')}`",
        f"- HTTP 평균: **{e2e_ms:,.2f}ms**, backend pipeline 평균: "
        f"**{pipeline_ms:,.2f}ms**",
        f"- 후보 trace 저장 평균: **{candidate_save_ms:,.2f}ms** "
        f"({candidate_save_ms / e2e_ms * 100 if e2e_ms else 0:.1f}% of HTTP)",
        "",
        "## 읽는 순서",
        "",
        "1. 후보 500개 trace 저장이 전체 저장 경로에서 가장 큰지 먼저 본다.",
        "2. 그 다음 run 저장, 후보 trace 저장, 최종 결과 및 근거 저장을 각각 펼친다.",
        "3. 각 하위 단계에서 Python 객체 생성(build/add)과 DB 작업(flush/delete)을 구분한다.",
        "4. p95는 요청별 최악 구간의 95백분위이므로, 평균과 같은 행끼리만 비교한다.",
        "",
        "![저장 상위 구간 평균](./01-persistence-stage-average.png)",
        "",
        "![저장 상위 구간 p95](./02-persistence-stage-p95.png)",
        "",
        "## 저장 및 응답 재조회 상위 구간",
        "",
        *persistence_stage_markdown_table(row),
        "",
        "![저장 경로 계층](./03-persistence-hierarchy.png)",
        "",
    ]
    for parent_id, heading, _ in persistence_detail_groups():
        lines.extend(
            [
                f"## {heading}",
                "",
                *execution_flow_markdown_table(records, parent_id),
                "",
            ]
        )
    lines.extend(
        [
            "![저장 세부 단계 평균과 p95](./04-persistence-detail-average-vs-p95.png)",
            "",
            "## 해석 주의",
            "",
            "- `candidate trace save`는 현재 500개 후보를 요청마다 기록하는 경로다.",
            "- `result and evidence save`는 최종 50개 결과와 최대 150개 근거를 남기는 경로다.",
            "- `response reload`는 저장 후 응답 DTO를 만들기 위해 최종 결과를 다시 읽는 비용이며, 쓰기 단계와 분리해 본다.",
            "- 원본 수치는 `../../data/persistence-drilldown-timings.csv`, 대표 run 메타는 `../../data/persistence-drilldown-basis.csv`에 있다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def plot_persistence_hierarchy(records, path: Path, plt) -> None:
    groups = persistence_detail_groups()
    group_records = [
        (heading, execution_flow_children(records, parent_id))
        for parent_id, heading, _ in groups
    ]
    group_records = [(heading, values) for heading, values in group_records if values]
    if not group_records:
        return

    palette = ["#2563EB", "#7C3AED", "#EA580C", "#0F766E", "#DC2626", "#64748B"]
    fig, ax = plt.subplots(figsize=(16, 8.5))
    for y, (heading, children) in enumerate(group_records):
        left = 0.0
        for index, child in enumerate(children):
            value = float(child["value_ms"])
            ax.barh(y, value, left=left, color=palette[index % len(palette)], height=0.58)
            if value >= 55:
                ax.text(
                    left + value / 2,
                    y,
                    f"{child['component']}\n{value:,.0f} ms",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=9,
                    fontweight="bold",
                )
            left += value
        ax.text(left + max(left * 0.015, 8), y, f"{left:,.1f} ms", va="center", fontsize=11)
    ax.set_yticks(range(len(group_records)), [heading for heading, _ in group_records])
    ax.invert_yaxis()
    ax.set_xlabel("average milliseconds per request")
    ax.set_title("Persistence write path: parent stage split into measured substeps", fontweight="bold")
    ax.spines[["right", "top"]].set_visible(False)
    fig.tight_layout()
    save_figure(fig, path, plt)


def plot_persistence_detail_distribution(row: dict[str, Any], path: Path, plt, sns) -> None:
    records = []
    for _, heading, stages in persistence_detail_groups():
        for key, label in stages:
            average = numeric_or_none(row.get(f"{key}_avg"))
            p95 = numeric_or_none(row.get(f"{key}_p95"))
            if average is None and p95 is None:
                continue
            records.extend(
                [
                    {"group": heading, "component": label, "statistic": "average", "milliseconds": average or 0.0},
                    {"group": heading, "component": label, "statistic": "p95", "milliseconds": p95 or 0.0},
                ]
            )
    if not records:
        return
    pd, _, _ = load_plot_dependencies()
    frame = pd.DataFrame(records)
    components = (
        frame.groupby("component", as_index=False)["milliseconds"]
        .max()
        .sort_values("milliseconds", ascending=True)["component"]
        .tolist()
    )
    fig, ax = plt.subplots(figsize=(16, max(7, len(components) * 0.5 + 2)))
    sns.barplot(
        data=frame,
        x="milliseconds",
        y="component",
        hue="statistic",
        order=components,
        palette={"average": "#2563EB", "p95": "#EA580C"},
        ax=ax,
    )
    ax.set_xlabel("milliseconds per request")
    ax.set_ylabel("")
    ax.set_title("Persistence substep average vs p95", fontweight="bold")
    ax.legend(title="")
    ax.spines[["right", "top"]].set_visible(False)
    fig.tight_layout()
    save_figure(fig, path, plt)


def write_execution_flow_readme(
    path: Path,
    row,
    records: list[dict[str, Any]],
    basis: dict[str, Any],
    *,
    snapshot_metrics: dict[str, Any] | None = None,
    coarse_metrics: dict[str, Any] | None = None,
) -> None:
    e2e_ms = float(basis["latency_avg_ms"] or 0.0)
    p95_ms = float(basis["latency_p95_ms"] or 0.0)
    pipeline_ms = float(basis["pipeline_avg_ms"] or 0.0)
    attempt_rate = float(basis["llm_attempt_rate"] or 0.0)
    snapshot_lines = snapshot_read_model_markdown(snapshot_metrics)
    coarse_lines = coarse_top50_markdown(coarse_metrics)
    prefetch_parent_id, score_loop_parent_id = scoring_detail_parent_ids(row)
    guardrail_instruction = (
        "4. coarse 후보 축소율과 feature hit·miss·stale·fallback을 확인한다."
        if coarse_metrics is not None
        else "4. snapshot 적중률과 조회·fallback 비용을 확인한다."
    )
    prefetch_heading = (
        "Exact top-50 prefetch 내부"
        if prefetch_parent_id == "exact_prefetch_ms"
        else "Data prefetch 내부"
    )
    score_loop_heading = (
        "Exact top-50 score loop 내부"
        if score_loop_parent_id == "exact_score_loop_ms"
        else "Score loop 내부"
    )
    lines = [
        "# 추천 API 실행 흐름 드릴다운",
        "",
        f"- 대표 run: `{basis['source_run_id']}`",
        f"- 조건: 실제 상품 {int(basis['actual_product_count'] or 0):,}개, VUS {basis['vus']}, "
        f"{basis['duration']}, `{basis['user_type']}`",
        f"- HTTP 평균: **{e2e_ms:,.2f}ms**, p95: **{p95_ms:,.2f}ms**",
        f"- 백엔드 파이프라인 평균: **{pipeline_ms:,.2f}ms** "
        f"({pipeline_ms / e2e_ms * 100 if e2e_ms else 0:.1f}%)",
        f"- LLM 의도 파서 시도율: **{attempt_rate * 100:.1f}%**",
        "",
        "> 평균 시간은 하위 구간을 더할 수 있어 계층 분석에 사용했다. "
        "p95는 구간별 표본의 95백분위라 서로 더하면 안 된다.",
        "",
        "## 읽는 순서",
        "",
        "1. 전체 HTTP에서 파이프라인과 미계측 구간을 본다.",
        "2. 파이프라인의 실제 호출 순서와 각 구간 시간을 본다.",
        "3. 가장 큰 scoring을 coarse 선별과 exact 계산까지 내려간다.",
        guardrail_instruction,
        "5. intent를 LLM 호출과 HTTP 대기까지 내려간다.",
        "6. 주요 병목 경로 세 개를 전체 HTTP 대비 비율로 비교한다.",
        "",
        "![전체 계층](./01-execution-hierarchy-rings.png)",
        "",
        "![파이프라인 순서](./02-pipeline-sequence.png)",
        "",
        "## 전체 HTTP",
        "",
        *execution_flow_markdown_table(records, "end_to_end"),
        "",
        "## 백엔드 파이프라인",
        "",
        *execution_flow_markdown_table(records, "backend_pipeline"),
        *persistence_execution_link(row),
        "",
        "![scoring 드릴다운](./03-scoring-drilldown.png)",
        "",
        "## Scoring 내부",
        "",
        *execution_flow_markdown_table(records, "scoring_ms"),
        "",
        f"### {prefetch_heading}",
        "",
        *execution_flow_markdown_table(records, prefetch_parent_id),
        "",
        f"### {score_loop_heading}",
        "",
        *execution_flow_markdown_table(records, score_loop_parent_id),
        *coarse_lines,
        *snapshot_lines,
        "",
        "![intent 드릴다운](./04-intent-drilldown.png)",
        "",
        "## Intent 내부",
        "",
        *execution_flow_markdown_table(records, "intent_parse_ms"),
        "",
        "### LLM parser 내부",
        "",
        *execution_flow_markdown_table(records, "intent_llm_call_ms"),
        "",
        "![주요 병목 경로](./06-bottleneck-paths.png)",
        "",
        "![핵심 수치 표](./07-timing-table.png)",
        "",
        "## 해석 주의",
        "",
        "- `outside pipeline / uninstrumented`는 인증/의존성, 이벤트 로그 커밋, "
        "응답 직렬화, Caddy/네트워크, 큐 대기 등이 합쳐진 값이다.",
        "- `other / unattributed`는 상위 계측값에서 현재 하위 계측값 합계를 뺀 잔여다.",
        "- 원본 수치는 `../../data/execution-flow-timings.csv`, 기준 run은 "
        "`../../data/execution-flow-basis.csv`에 있다.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def persistence_execution_link(row: dict[str, Any]) -> list[str]:
    if not has_persistence_detail(row):
        return []
    return [
        "",
        "저장 단계의 세부 build/add/flush 분해는 "
        "[persistence 드릴다운](./persistence/README.md)에서 확인한다.",
    ]


def snapshot_read_model_markdown(
    metrics: dict[str, Any] | None,
) -> list[str]:
    if metrics is None:
        return []
    return [
        "",
        "## Snapshot Read Model",
        "",
        "| 지표 | 평균 | p95 |",
        "|---|---:|---:|",
        f"| snapshot 조회 | {metrics['snapshot_load_avg_ms']:,.2f}ms | "
        f"{metrics['snapshot_load_p95_ms']:,.2f}ms |",
        f"| fallback 경로 | {metrics['snapshot_fallback_avg_ms']:,.2f}ms | "
        f"{metrics['snapshot_fallback_p95_ms']:,.2f}ms |",
        f"| hit 후보/요청 | {metrics['snapshot_hit_count_avg']:,.2f}개 | - |",
        f"| miss 후보/요청 | {metrics['snapshot_miss_count_avg']:,.2f}개 | - |",
        f"| parse error/요청 | {metrics['snapshot_parse_error_count_avg']:,.2f}개 | "
        f"{metrics['snapshot_parse_error_count_p95']:,.2f}개 |",
        "",
        f"- snapshot hit rate: **{metrics['snapshot_hit_rate'] * 100:.2f}%**",
        f"- snapshot miss rate: **{metrics['snapshot_miss_rate'] * 100:.2f}%**",
        "- `snapshot fallback`은 누락 후보의 기존 loader 전체 구간이며 하위 loader "
        "시간과 겹치므로 prefetch 합계에 다시 더하지 않는다.",
        "- 원본 수치는 `../../data/snapshot-read-model-metrics.csv`에 있다.",
        "",
        "![snapshot read model](./05-snapshot-read-model.png)",
    ]


def coarse_top50_markdown(
    metrics: dict[str, Any] | None,
) -> list[str]:
    if metrics is None:
        return []
    return [
        "",
        "## Coarse Top-50 선별",
        "",
        "| 구간 | 평균 | p95 |",
        "|---|---:|---:|",
        f"| coarse feature 조회 | {metrics['coarse_feature_query_avg_ms']:,.2f}ms | "
        f"{metrics['coarse_feature_query_p95_ms']:,.2f}ms |",
        f"| coarse 후보 점수 계산 | {metrics['coarse_score_loop_avg_ms']:,.2f}ms | "
        f"{metrics['coarse_score_loop_p95_ms']:,.2f}ms |",
        f"| exact 상위 50개 조회 | {metrics['exact_prefetch_avg_ms']:,.2f}ms | "
        f"{metrics['exact_prefetch_p95_ms']:,.2f}ms |",
        f"| exact 상위 50개 점수 계산 | {metrics['exact_score_loop_avg_ms']:,.2f}ms | "
        f"{metrics['exact_score_loop_p95_ms']:,.2f}ms |",
        "",
        f"- coarse 대상: **{metrics['coarse_candidate_count_avg']:,.1f}개/요청**",
        f"- exact 대상: **{metrics['exact_shortlist_size_avg']:,.1f}개/요청** "
        f"({metrics['exact_candidate_ratio'] * 100:.1f}%)",
        f"- 상세 조회·정확 계산 대상 감소율: "
        f"**{metrics['candidate_reduction_rate'] * 100:.1f}%**",
        f"- feature hit/miss/stale: **{metrics['feature_hit_rate'] * 100:.2f}% / "
        f"{metrics['feature_miss_rate'] * 100:.2f}% / "
        f"{metrics['feature_stale_rate'] * 100:.2f}%**",
        f"- coarse source fallback 비율: "
        f"**{metrics['feature_fallback_ratio'] * 100:.2f}%**",
        "- generic `scoring_data_prefetch_ms`와 `score_loop_ms`는 이 경로에서 "
        "exact 단계의 별칭이므로 scoring 구성에 중복 합산하지 않는다.",
        "- 원본 수치는 `../../data/coarse-top50-metrics.csv`에 있다.",
        "",
        "![coarse top-50 guardrails](./05-coarse-top50-guardrails.png)",
    ]


def execution_flow_markdown_table(
    records: list[dict[str, Any]],
    parent_id: str,
) -> list[str]:
    children = execution_flow_children(records, parent_id)
    if not children:
        return ["계측값 없음"]
    lines = [
        "| 순서 | 구간 | 평균(ms) | 상위 대비 | HTTP 전체 대비 |",
        "|---:|---|---:|---:|---:|",
    ]
    for child in children:
        lines.append(
            f"| {child['sequence']} | {child['component']} | "
            f"{child['value_ms']:,.2f} | {child['parent_share_percent']:.1f}% | "
            f"{child['e2e_share_percent']:.1f}% |"
        )
    return lines


def flow_record_value(
    records: list[dict[str, Any]],
    component_id: str,
) -> float:
    for record in records:
        if record["component_id"] == component_id:
            return float(record["value_ms"])
    return 0.0


def compact_ms(value: float) -> str:
    return f"{value:,.2f}" if value < 10 else f"{value:,.0f}"


def plot_execution_hierarchy_rings(row, records, path: Path, plt, sns) -> None:
    from matplotlib.patches import Patch

    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    p95_ms = numeric_or_none(row.get("latency_p95_ms")) or 0.0
    pipeline_ms = numeric_or_none(row.get("duration_ms_avg")) or 0.0
    if e2e_ms <= 0 or pipeline_ms <= 0:
        return

    pipeline_children = {
        record["component_id"]: record
        for record in execution_flow_children(records, "backend_pipeline")
    }
    scoring_children = execution_flow_children(records, "scoring_ms")
    outside_ms = max(e2e_ms - pipeline_ms, 0.0)
    context_ms = sum(
        pipeline_children[key]["value_ms"]
        for key in (
            "user_context_load_ms",
            "skin_test_context_load_ms",
            "behavior_context_load_ms",
        )
        if key in pipeline_children
    )
    persistence_ms = sum(
        pipeline_children[key]["value_ms"]
        for key in (
            "run_save_ms",
            "search_candidate_save_ms",
            "result_save_ms",
            "commit_ms",
        )
        if key in pipeline_children
    )
    retrieval_ms = sum(
        pipeline_children[key]["value_ms"]
        for key in ("candidate_pool_ms", "search_match_ms")
        if key in pipeline_children
    )
    intent_ms = pipeline_children.get("intent_parse_ms", {}).get("value_ms", 0.0)
    scoring_ms = pipeline_children.get("scoring_ms", {}).get("value_ms", 0.0)
    response_ms = pipeline_children.get("response_load_ms", {}).get("value_ms", 0.0)
    grouped_total = (
        context_ms
        + intent_ms
        + persistence_ms
        + retrieval_ms
        + scoring_ms
        + response_ms
    )
    pipeline_residual_ms = max(pipeline_ms - grouped_total, 0.0)

    middle = [
        ("personalization context", context_ms, "#0F766E"),
        ("intent", intent_ms, "#EA580C"),
        ("candidate retrieval", retrieval_ms, "#2563EB"),
        ("persistence", persistence_ms, "#7C3AED"),
        ("scoring", scoring_ms, "#DC2626"),
        ("response load", response_ms, "#16A34A"),
    ]
    if pipeline_residual_ms > 0.005:
        middle.append(("pipeline other", pipeline_residual_ms, "#CBD5E1"))
    middle.append(("outside pipeline", outside_ms, "#475569"))

    scoring_colors = ["#F97316", "#84CC16", "#E11D48", "#0891B2", "#7C3AED", "#CBD5E1"]
    outer: list[tuple[str, float, str]] = []
    for label, value, color in middle:
        if label != "scoring":
            outer.append((label, value, color))
            continue
        for index, child in enumerate(scoring_children):
            outer.append(
                (
                    f"scoring: {child['component']}",
                    child["value_ms"],
                    scoring_colors[index % len(scoring_colors)],
                )
            )

    fig, ax = plt.subplots(figsize=(15.5, 10.5))
    fig.subplots_adjust(left=0.04, right=0.67, top=0.9, bottom=0.08)
    ax.pie(
        [pipeline_ms, outside_ms],
        radius=0.55,
        startangle=90,
        counterclock=False,
        colors=["#0F172A", "#94A3B8"],
        wedgeprops={"width": 0.22, "edgecolor": "white", "linewidth": 2},
    )
    ax.pie(
        [item[1] for item in middle],
        radius=0.86,
        startangle=90,
        counterclock=False,
        colors=[item[2] for item in middle],
        wedgeprops={"width": 0.25, "edgecolor": "white", "linewidth": 1.5},
    )
    ax.pie(
        [item[1] for item in outer],
        radius=1.17,
        startangle=90,
        counterclock=False,
        colors=[item[2] for item in outer],
        wedgeprops={"width": 0.25, "edgecolor": "white", "linewidth": 1.2},
    )
    ax.text(
        0,
        0,
        f"HTTP avg\n{e2e_ms:,.0f} ms\n\np95 {p95_ms:,.0f} ms",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color="#0F172A",
    )
    ax.set_title(
        "Recommendation API timing hierarchy\ninner: HTTP  |  middle: pipeline groups  |  outer: scoring detail",
        fontsize=18,
        fontweight="bold",
        pad=22,
    )
    legend_items = [
        Patch(
            facecolor=color,
            label=(
                f"{label}: {compact_ms(value)} ms "
                f"({value / e2e_ms * 100:.1f}% HTTP)"
            ),
        )
        for label, value, color in middle
        if value > 0
    ]
    legend_items.extend(
        Patch(
            facecolor=color,
            label=f"{label}: {compact_ms(value)} ms",
        )
        for label, value, color in outer
        if label.startswith("scoring:") and value > 0
    )
    fig.legend(
        handles=legend_items,
        loc="center right",
        bbox_to_anchor=(0.99, 0.5),
        frameon=False,
        fontsize=10,
        title="Measured average",
        title_fontsize=12,
    )
    fig.text(
        0.04,
        0.02,
        "The outside-pipeline slice is aggregate overhead; its internal order is not instrumented.",
        fontsize=10,
        color="#475569",
    )
    save_figure(fig, path, plt)


def plot_pipeline_sequence(row, records, path: Path, plt, sns) -> None:
    stages = execution_flow_children(records, "backend_pipeline")
    if not stages:
        return
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    pipeline_ms = numeric_or_none(row.get("duration_ms_avg")) or 0.0
    p95_ms = numeric_or_none(row.get("latency_p95_ms")) or 0.0
    palette = sns.color_palette("colorblind", n_colors=max(len(stages), 3))

    fig, (ax_stack, ax_order) = plt.subplots(
        2,
        1,
        figsize=(15.5, 11.5),
        gridspec_kw={"height_ratios": [1.1, 4.2]},
        layout="constrained",
    )
    left = 0.0
    for index, stage in enumerate(stages):
        value = stage["value_ms"]
        color = palette[index % len(palette)]
        ax_stack.barh(0, value, left=left, height=0.52, color=color, edgecolor="white")
        if value >= pipeline_ms * 0.055:
            ax_stack.text(
                left + value / 2,
                0,
                f"{stage['component']}\n{value:,.0f} ms",
                ha="center",
                va="center",
                fontsize=8.5,
                color=contrast_text_color(color),
                fontweight="bold",
            )
        left += value
    ax_stack.set_xlim(0, max(e2e_ms, pipeline_ms) * 1.01)
    ax_stack.set_yticks([0], labels=["backend pipeline"])
    ax_stack.set_xlabel("cumulative average time (ms)")
    ax_stack.set_title(
        f"Request execution order: {pipeline_ms:,.2f} ms pipeline of {e2e_ms:,.2f} ms HTTP average\n"
        f"HTTP p95 {p95_ms:,.2f} ms",
        fontweight="bold",
    )
    ax_stack.axvspan(pipeline_ms, e2e_ms, color="#E2E8F0", alpha=0.8)
    ax_stack.text(
        pipeline_ms + max(e2e_ms - pipeline_ms, 0) / 2,
        0,
        f"outside pipeline\n{max(e2e_ms - pipeline_ms, 0):,.0f} ms",
        ha="center",
        va="center",
        fontsize=9,
        color="#334155",
    )

    labels = [f"{index:02d}  {stage['component']}" for index, stage in enumerate(stages, 1)]
    values = [stage["value_ms"] for stage in stages]
    positions = list(range(len(stages)))
    bars = ax_order.barh(positions, values, color=palette[: len(stages)])
    ax_order.set_yticks(positions, labels=labels)
    ax_order.invert_yaxis()
    ax_order.set_xlabel("average time (ms)")
    ax_order.set_ylabel("")
    ax_order.set_title("Pipeline stages in call order", loc="left", fontsize=14)
    max_value = max(values)
    for position, (bar, stage) in enumerate(zip(bars, stages)):
        ax_order.text(
            bar.get_width() + max_value * 0.015,
            position,
            f"{stage['value_ms']:,.2f} ms  |  cumulative {stage['cumulative_end_ms']:,.2f} ms",
            va="center",
            fontsize=9,
        )
    ax_order.set_xlim(0, max_value * 1.58)
    save_figure(fig, path, plt)


def plot_scoring_drilldown(row, records, path: Path, plt, sns) -> None:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    scoring_ms = numeric_or_none(row.get("scoring_ms_avg")) or 0.0
    if scoring_ms <= 0:
        return
    prefetch_parent_id, score_loop_parent_id = scoring_detail_parent_ids(row)
    prefetch_label = (
        "3. inside exact top-50 prefetch"
        if prefetch_parent_id == "exact_prefetch_ms"
        else "3. inside data prefetch"
    )
    score_loop_label = (
        "4. inside exact top-50 score loop"
        if score_loop_parent_id == "exact_score_loop_ms"
        else "4. inside score loop"
    )
    rows = [
        (
            "1. scoring total",
            scoring_ms,
            [("scoring", scoring_ms)],
        ),
        (
            "2. scoring composition",
            scoring_ms,
            [
                (record["component"], record["value_ms"])
                for record in execution_flow_children(records, "scoring_ms")
            ],
        ),
        (
            prefetch_label,
            flow_record_value(records, prefetch_parent_id),
            [
                (record["component"], record["value_ms"])
                for record in execution_flow_children(
                    records,
                    prefetch_parent_id,
                )
            ],
        ),
        (
            score_loop_label,
            flow_record_value(records, score_loop_parent_id),
            [
                (record["component"], record["value_ms"])
                for record in execution_flow_children(records, score_loop_parent_id)
            ],
        ),
    ]
    plot_drilldown_rows(
        rows,
        path,
        title=(
            f"Scoring drill-down: {scoring_ms:,.2f} ms "
            f"({scoring_ms / e2e_ms * 100 if e2e_ms else 0:.1f}% of HTTP average)"
        ),
        max_total=scoring_ms,
        e2e_ms=e2e_ms,
        plt=plt,
        sns=sns,
    )


def plot_intent_drilldown(row, records, path: Path, plt, sns) -> None:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    intent_ms = numeric_or_none(row.get("intent_parse_ms_avg")) or 0.0
    llm_ms = numeric_or_none(row.get("intent_llm_call_ms_avg")) or 0.0
    attempt_rate = numeric_or_none(row.get("intent_llm_attempted_true_rate")) or 0.0
    if intent_ms <= 0:
        return
    rows = [
        ("1. intent total", intent_ms, [("intent", intent_ms)]),
        (
            "2. intent composition",
            intent_ms,
            [
                (record["component"], record["value_ms"])
                for record in execution_flow_children(records, "intent_parse_ms")
            ],
        ),
        (
            "3. LLM parser total",
            llm_ms,
            [("LLM parser", llm_ms)],
        ),
        (
            "4. inside LLM parser",
            llm_ms,
            [
                (record["component"], record["value_ms"])
                for record in execution_flow_children(records, "intent_llm_call_ms")
            ],
        ),
    ]
    plot_drilldown_rows(
        rows,
        path,
        title=(
            f"Intent drill-down: {intent_ms:,.2f} ms "
            f"({intent_ms / e2e_ms * 100 if e2e_ms else 0:.1f}% of HTTP average)"
            f"  |  LLM attempted on {attempt_rate * 100:.1f}% of requests"
        ),
        max_total=intent_ms,
        e2e_ms=e2e_ms,
        plt=plt,
        sns=sns,
    )


def plot_drilldown_rows(
    rows: list[tuple[str, float, list[tuple[str, float]]]],
    path: Path,
    *,
    title: str,
    max_total: float,
    e2e_ms: float,
    plt,
    sns,
) -> None:
    from matplotlib.colors import to_rgb

    fig, axes = plt.subplots(
        len(rows),
        1,
        figsize=(16, 3.1 * len(rows)),
        sharex=True,
        layout="constrained",
    )
    palette = sns.color_palette("colorblind", n_colors=10)
    for row_index, (row_label, parent_ms, segments) in enumerate(rows):
        ax = axes[row_index]
        left = 0.0
        for segment_index, (label, value) in enumerate(segments):
            if value <= 0:
                continue
            color = palette[segment_index % len(palette)]
            ax.barh(
                0,
                value,
                left=left,
                height=0.48,
                color=color,
                edgecolor="white",
                linewidth=1.2,
            )
            share_of_parent = value / parent_ms if parent_ms > 0 else 0.0
            share_of_canvas = value / max_total if max_total > 0 else 0.0
            if share_of_parent >= 0.07 and share_of_canvas >= 0.035:
                ax.text(
                    left + value / 2,
                    0,
                    f"{label}\n{value:,.1f} ms\n{share_of_parent * 100:.1f}%",
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color=contrast_text_color(to_rgb(color)),
                    fontweight="bold",
                )
            left += value
        ax.set_yticks([])
        ax.set_xlim(0, max_total * 1.04)
        ax.set_ylim(-0.65, 0.65)
        ax.set_ylabel("")
        ax.set_title(
            f"{row_label}  |  {parent_ms:,.2f} ms  |  "
            f"{parent_ms / e2e_ms * 100 if e2e_ms else 0:.1f}% of HTTP",
            loc="left",
            fontsize=13,
            fontweight="bold",
        )
        ax.grid(axis="y", visible=False)
        ax.spines[["left", "right", "top"]].set_visible(False)
        if len(segments) > 1:
            detail = "  |  ".join(f"{label} {value:,.1f}" for label, value in segments)
            ax.text(
                0,
                -0.56,
                detail,
                fontsize=7.7,
                color="#475569",
                va="center",
                clip_on=False,
            )
    axes[-1].set_xlabel("average time on the same absolute scale (ms)")
    fig.suptitle(title, fontsize=18, fontweight="bold")
    save_figure(fig, path, plt)


def find_execution_flow_record(
    records: list[dict[str, Any]],
    component_id: str,
    *,
    parent_id: str | None = None,
) -> dict[str, Any] | None:
    for record in records:
        if record["component_id"] != component_id:
            continue
        if parent_id is not None and record["parent_id"] != parent_id:
            continue
        return record
    return None


def plot_snapshot_read_model(metrics, path: Path, plt) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(20, 7.5))

    timing_labels = ["snapshot load", "fallback path"]
    averages = [
        metrics["snapshot_load_avg_ms"],
        metrics["snapshot_fallback_avg_ms"],
    ]
    p95_values = [
        metrics["snapshot_load_p95_ms"],
        metrics["snapshot_fallback_p95_ms"],
    ]
    positions = list(range(len(timing_labels)))
    width = 0.34
    average_bars = axes[0].bar(
        [position - width / 2 for position in positions],
        averages,
        width,
        label="average",
        color="#2563EB",
    )
    p95_bars = axes[0].bar(
        [position + width / 2 for position in positions],
        p95_values,
        width,
        label="p95",
        color="#EA580C",
    )
    axes[0].bar_label(average_bars, fmt="%.1f", padding=3, fontsize=10)
    axes[0].bar_label(p95_bars, fmt="%.1f", padding=3, fontsize=10)
    axes[0].set_xticks(positions, timing_labels)
    axes[0].set_ylabel("milliseconds")
    axes[0].set_title("Read and fallback cost", fontweight="bold")
    axes[0].legend(frameon=False)
    axes[0].spines[["right", "top"]].set_visible(False)

    hit_count = metrics["snapshot_hit_count_avg"]
    miss_count = metrics["snapshot_miss_count_avg"]
    if hit_count + miss_count > 0:
        axes[1].pie(
            [hit_count, miss_count],
            labels=["hit", "miss"],
            colors=["#0F766E", "#DC2626"],
            autopct=lambda percent: f"{percent:.2f}%" if percent > 0 else "",
            startangle=90,
            wedgeprops={"width": 0.42, "edgecolor": "white"},
        )
        axes[1].text(
            0,
            0,
            f"{hit_count + miss_count:,.1f}\ncandidates/request",
            ha="center",
            va="center",
            fontsize=13,
            fontweight="bold",
        )
    else:
        axes[1].text(0.5, 0.5, "No snapshot candidate metrics", ha="center", va="center")
        axes[1].axis("off")
    axes[1].set_title("Snapshot coverage", fontweight="bold")

    axes[2].axis("off")
    cards = [
        ("Hit rate", f"{metrics['snapshot_hit_rate'] * 100:.2f}%", "#DCFCE7", "#166534"),
        ("Miss / request", f"{miss_count:,.2f}", "#FEE2E2", "#991B1B"),
        (
            "Parse errors / request",
            f"{metrics['snapshot_parse_error_count_avg']:,.2f}",
            "#FEF3C7",
            "#92400E",
        ),
    ]
    for index, (label, value, facecolor, textcolor) in enumerate(cards):
        y = 0.82 - index * 0.3
        axes[2].text(
            0.5,
            y,
            f"{label}\n{value}",
            ha="center",
            va="center",
            fontsize=16,
            fontweight="bold",
            color=textcolor,
            bbox={
                "boxstyle": "round,pad=0.8",
                "facecolor": facecolor,
                "edgecolor": "none",
            },
        )
    axes[2].set_title("Read-model guardrails", fontweight="bold")

    fig.suptitle(
        "Opt4 snapshot read-model diagnostics",
        fontsize=20,
        fontweight="bold",
        y=0.97,
    )
    fig.text(
        0.5,
        0.04,
        "Fallback spans the legacy loader path and overlaps its child timings; "
        "it is diagnostic, not an additive pipeline segment.",
        ha="center",
        fontsize=10,
        color="#475569",
    )
    fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.16, wspace=0.3)
    save_figure(fig, path, plt)


def plot_coarse_top50_guardrails(metrics, path: Path, plt) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(20, 7.5))

    coarse_count = metrics["coarse_candidate_count_avg"]
    exact_count = metrics["exact_shortlist_size_avg"]
    funnel_labels = ["coarse candidates", "exact shortlist"]
    funnel_values = [coarse_count, exact_count]
    funnel_bars = axes[0].bar(
        funnel_labels,
        funnel_values,
        color=["#2563EB", "#0F766E"],
        width=0.62,
    )
    axes[0].bar_label(funnel_bars, fmt="%.1f", padding=4, fontsize=11)
    axes[0].set_ylabel("candidates / request")
    axes[0].set_title("Candidate funnel", fontweight="bold")
    axes[0].spines[["right", "top"]].set_visible(False)
    axes[0].text(
        0.5,
        max(funnel_values or [1]) * 0.58,
        f"-{metrics['candidate_reduction_rate'] * 100:.1f}%\nexact work",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color="#0F172A",
    )

    timing_labels = ["coarse query", "coarse loop", "exact prefetch", "exact loop"]
    timing_values = [
        metrics["coarse_feature_query_avg_ms"],
        metrics["coarse_score_loop_avg_ms"],
        metrics["exact_prefetch_avg_ms"],
        metrics["exact_score_loop_avg_ms"],
    ]
    timing_colors = ["#60A5FA", "#2563EB", "#2DD4BF", "#0F766E"]
    timing_bars = axes[1].barh(timing_labels, timing_values, color=timing_colors)
    axes[1].bar_label(timing_bars, fmt="%.1f ms", padding=4, fontsize=10)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("average milliseconds")
    axes[1].set_title("Two-pass scoring cost", fontweight="bold")
    axes[1].spines[["right", "top"]].set_visible(False)
    axes[1].set_xlim(0, max(timing_values or [1]) * 1.28)

    rate_labels = ["hit", "miss", "stale", "fallback"]
    rate_values = [
        metrics["feature_hit_rate"] * 100,
        metrics["feature_miss_rate"] * 100,
        metrics["feature_stale_rate"] * 100,
        metrics["feature_fallback_ratio"] * 100,
    ]
    rate_colors = ["#16A34A", "#DC2626", "#D97706", "#7C3AED"]
    rate_bars = axes[2].bar(rate_labels, rate_values, color=rate_colors, width=0.62)
    axes[2].bar_label(rate_bars, fmt="%.2f%%", padding=4, fontsize=10)
    axes[2].set_ylabel("percent")
    axes[2].set_ylim(0, max(105.0, max(rate_values or [0]) * 1.12))
    axes[2].set_title("Feature read guardrails", fontweight="bold")
    axes[2].spines[["right", "top"]].set_visible(False)

    fig.suptitle(
        "Opt4c coarse-to-exact scoring diagnostics",
        fontsize=20,
        fontweight="bold",
        y=0.97,
    )
    fig.text(
        0.5,
        0.04,
        "Coarse features rank the full candidate set; only the shortlist enters "
        "the detailed exact scoring path.",
        ha="center",
        fontsize=10,
        color="#475569",
    )
    fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.16, wspace=0.3)
    save_figure(fig, path, plt)


def plot_bottleneck_paths(row, records, path: Path, plt, sns) -> None:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    pipeline_ms = numeric_or_none(row.get("duration_ms_avg")) or 0.0
    if e2e_ms <= 0:
        return
    if uses_coarse_top50_scoring(row):
        paths = [
            (
                "Coarse ranking path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("scoring", flow_record_value(records, "scoring_ms")),
                    ("coarse loop", flow_record_value(records, "coarse_score_loop_ms")),
                    ("feature query", flow_record_value(records, "coarse_feature_query_ms")),
                ],
                "#2563EB",
            ),
            (
                "Exact top-50 path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("scoring", flow_record_value(records, "scoring_ms")),
                    ("exact prefetch", flow_record_value(records, "exact_prefetch_ms")),
                    ("exact loop", flow_record_value(records, "exact_score_loop_ms")),
                ],
                "#EA580C",
            ),
            (
                "Intent / external-call path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("intent", flow_record_value(records, "intent_parse_ms")),
                    ("LLM parser", flow_record_value(records, "intent_llm_call_ms")),
                    ("LLM HTTP wait", flow_record_value(records, "intent_llm_http_ms")),
                ],
                "#0F766E",
            ),
        ]
    else:
        snapshot_load_ms = flow_record_value(records, "prefetch_snapshot_load_ms")
        data_loading_leaf = (
            ("snapshot load", snapshot_load_ms)
            if snapshot_load_ms > 0
            else (
                "candidate bundle",
                flow_record_value(records, "prefetch_candidate_bundle_ms"),
            )
        )
        paths = [
            (
                "Data-loading path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("scoring", flow_record_value(records, "scoring_ms")),
                    (
                        "data prefetch",
                        flow_record_value(records, "scoring_data_prefetch_ms"),
                    ),
                    data_loading_leaf,
                ],
                "#EA580C",
            ),
            (
                "Per-candidate compute path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("scoring", flow_record_value(records, "scoring_ms")),
                    ("score loop", flow_record_value(records, "score_loop_ms")),
                    (
                        "behavior axis",
                        flow_record_value(records, "score_loop_behavior_axis_ms"),
                    ),
                ],
                "#2563EB",
            ),
            (
                "Intent / external-call path",
                [
                    ("HTTP", e2e_ms),
                    ("pipeline", pipeline_ms),
                    ("intent", flow_record_value(records, "intent_parse_ms")),
                    ("LLM parser", flow_record_value(records, "intent_llm_call_ms")),
                    ("LLM HTTP wait", flow_record_value(records, "intent_llm_http_ms")),
                ],
                "#0F766E",
            ),
        ]
    fig, axes = plt.subplots(1, 3, figsize=(20, 8.5), sharex=True, layout="constrained")
    for ax, (title, stages, accent) in zip(axes, paths):
        labels = [stage[0] for stage in stages]
        values = [stage[1] for stage in stages]
        positions = list(range(len(stages)))
        colors = ["#0F172A", "#475569", accent, accent, accent]
        alphas = [1.0, 0.9, 0.82, 0.66, 0.5]
        bars = ax.barh(positions, values, color=colors)
        for bar, alpha in zip(bars, alphas):
            bar.set_alpha(alpha)
        ax.set_yticks(positions, labels=labels)
        ax.invert_yaxis()
        ax.set_xlim(0, e2e_ms * 1.24)
        ax.set_xlabel("average ms")
        ax.set_title(title, fontsize=14, fontweight="bold")
        for position, value in enumerate(values):
            ax.text(
                value + e2e_ms * 0.015,
                position,
                f"{value:,.1f} ms\n{value / e2e_ms * 100:.1f}% HTTP",
                va="center",
                fontsize=9,
            )
        ax.spines[["right", "top"]].set_visible(False)
    fig.suptitle(
        "Three bottleneck paths, drilled down from the same HTTP average",
        fontsize=19,
        fontweight="bold",
    )
    save_figure(fig, path, plt)


def plot_execution_flow_table(row, records, path: Path, plt) -> None:
    e2e_ms = numeric_or_none(row.get("latency_avg_ms")) or 0.0
    selections = [
        ("end_to_end", None),
        ("backend_pipeline", "end_to_end"),
        ("scoring_ms", "backend_pipeline"),
        ("intent_parse_ms", "backend_pipeline"),
        ("intent_llm_call_ms", "intent_parse_ms"),
        ("intent_llm_http_ms", "intent_llm_call_ms"),
        ("candidate_pool_ms", "backend_pipeline"),
        ("search_match_ms", "backend_pipeline"),
        ("search_candidate_save_ms", "backend_pipeline"),
        ("response_load_ms", "backend_pipeline"),
        ("outside_pipeline", "end_to_end"),
    ]
    if uses_coarse_top50_scoring(row):
        selections[3:3] = [
            ("coarse_feature_query_ms", "scoring_ms"),
            ("coarse_feature_build_ms", "scoring_ms"),
            ("coarse_score_loop_ms", "scoring_ms"),
            ("exact_prefetch_ms", "scoring_ms"),
            ("prefetch_candidate_bundle_ms", "exact_prefetch_ms"),
            ("exact_score_loop_ms", "scoring_ms"),
            ("score_loop_behavior_axis_ms", "exact_score_loop_ms"),
        ]
    else:
        selections[3:3] = [
            ("scoring_data_prefetch_ms", "scoring_ms"),
            ("prefetch_snapshot_load_ms", "scoring_data_prefetch_ms"),
            ("prefetch_candidate_bundle_ms", "scoring_data_prefetch_ms"),
            ("score_loop_ms", "scoring_ms"),
            ("score_loop_behavior_axis_ms", "score_loop_ms"),
        ]
    selected = []
    for component_id, parent_id in selections:
        record = find_execution_flow_record(
            records,
            component_id,
            parent_id=parent_id,
        )
        if record:
            selected.append(record)
    if not selected:
        return

    cell_text = []
    for record in selected:
        indent = "  " * int(record["level"])
        cell_text.append(
            [
                str(record["level"]),
                f"{indent}{record['component']}",
                f"{record['value_ms']:,.2f}",
                f"{record['parent_share_percent']:.1f}%",
                f"{record['e2e_share_percent']:.1f}%",
            ]
        )

    fig, ax = plt.subplots(figsize=(15.5, 9.2))
    ax.axis("off")
    table = ax.table(
        cellText=cell_text,
        colLabels=["Depth", "Measured component", "Average ms", "% of parent", "% of HTTP"],
        colWidths=[0.08, 0.42, 0.17, 0.16, 0.16],
        cellLoc="right",
        colLoc="right",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10.5)
    table.scale(1, 1.65)
    header_color = "#0F172A"
    depth_colors = ["#E2E8F0", "#DBEAFE", "#FFEDD5", "#DCFCE7", "#F3E8FF"]
    for (row_index, column_index), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        if row_index == 0:
            cell.set_facecolor(header_color)
            cell.get_text().set_color("white")
            cell.get_text().set_fontweight("bold")
        else:
            depth = int(selected[row_index - 1]["level"])
            cell.set_facecolor(depth_colors[min(depth, len(depth_colors) - 1)])
        if column_index == 1:
            cell.get_text().set_ha("left")
    ax.set_title(
        f"Recommendation API key timing table  |  HTTP average {e2e_ms:,.2f} ms",
        fontsize=18,
        fontweight="bold",
        pad=20,
    )
    fig.text(
        0.5,
        0.035,
        "Indented rows are measured inside the preceding parent component.",
        ha="center",
        fontsize=10,
        color="#475569",
    )
    save_figure(fig, path, plt)


def plot_intent_outcomes(row, path: Path, title: str, plt, sns) -> None:
    prefix = "intent_llm_outcome_"
    suffix = "_count"
    records = []
    for key, value in row.items():
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        if key == "intent_llm_outcome_sample_count":
            continue
        numeric_value = float_value(value)
        if numeric_value is None or numeric_value <= 0:
            continue
        outcome = key[len(prefix) : -len(suffix)].replace("_", " ")
        records.append((outcome, numeric_value))
    if not records:
        return

    records.sort(key=lambda item: item[1], reverse=True)
    labels = [item[0] for item in records]
    values = [item[1] for item in records]
    total = sum(values)
    positions = list(range(len(records)))
    fig, ax = plt.subplots(
        figsize=(10.5, max(4.8, len(records) * 0.7)),
        layout="constrained",
    )
    bars = ax.barh(positions, values, color=sns.color_palette("colorblind")[2])
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("pipeline event count")
    ax.set_ylabel("")
    ax.bar_label(
        bars,
        labels=[f"{value:,.0f} ({value / total * 100:.1f}%)" for value in values],
        padding=4,
        fontsize=9,
    )
    save_figure(fig, path, plt)


def plot_intent_detail_graphs(
    row,
    output_dir: Path,
    *,
    stage_dataset: int,
    stage_vus: int,
    plt,
    sns,
) -> None:
    scope = f"{stage_dataset:,} products / VUS {stage_vus}"
    average_records = build_intent_detail_records(row, statistic="avg")
    if average_records:
        plot_single_stacked_stage_bar(
            average_records,
            output_dir / f"intent_detail_stacked_average_{stage_dataset}_vus{stage_vus:02d}.png",
            f"intent parser detailed average ({scope})",
            plt,
            sns,
            unit="ms",
        )
        plot_single_stacked_stage_bar(
            average_records,
            output_dir / f"intent_detail_stacked_share_{stage_dataset}_vus{stage_vus:02d}.png",
            f"intent parser detailed share ({scope})",
            plt,
            sns,
            unit="%",
            normalize=True,
        )
        plot_intent_detail_donut(
            average_records,
            output_dir / f"intent_detail_donut_share_{stage_dataset}_vus{stage_vus:02d}.png",
            f"intent parser detailed share donut ({scope})",
            plt,
            sns,
        )

    purchase_average_records = build_purchase_parser_detail_records(row, statistic="avg")
    if purchase_average_records:
        plot_single_stacked_stage_bar(
            purchase_average_records,
            output_dir / f"purchase_parser_stacked_average_{stage_dataset}_vus{stage_vus:02d}.png",
            f"purchase parser internal average ({scope})",
            plt,
            sns,
            unit="ms",
            legend_title="purchase component",
        )
        plot_single_stacked_stage_bar(
            purchase_average_records,
            output_dir / f"purchase_parser_stacked_share_{stage_dataset}_vus{stage_vus:02d}.png",
            f"purchase parser internal share ({scope})",
            plt,
            sns,
            unit="%",
            normalize=True,
            legend_title="purchase component",
        )
        plot_intent_detail_donut(
            purchase_average_records,
            output_dir / f"purchase_parser_donut_share_{stage_dataset}_vus{stage_vus:02d}.png",
            f"purchase parser internal share donut ({scope})",
            plt,
            sns,
            legend_title="purchase component",
        )

    run_dir = Path(str(row.get("run_dir") or ""))
    events = load_pipeline_events(run_dir / "backend" / "backend.log")
    if not events:
        return

    plot_intent_component_distribution(
        events,
        output_dir / f"intent_detail_component_distribution_{stage_dataset}_vus{stage_vus:02d}.png",
        f"intent component distribution ({scope})",
        plt,
        sns,
    )
    plot_intent_request_stacked_bars(
        events,
        output_dir / f"intent_detail_request_stacked_top_{stage_dataset}_vus{stage_vus:02d}.png",
        f"slowest intent requests by component ({scope})",
        plt,
        sns,
    )
    plot_intent_purchase_vs_llm_scatter(
        events,
        output_dir / f"intent_purchase_vs_llm_http_{stage_dataset}_vus{stage_vus:02d}.png",
        f"purchase parser vs LLM HTTP time ({scope})",
        plt,
        sns,
    )
    plot_purchase_parser_component_distribution(
        events,
        output_dir / f"purchase_parser_component_distribution_{stage_dataset}_vus{stage_vus:02d}.png",
        f"purchase parser component distribution ({scope})",
        plt,
        sns,
    )
    plot_purchase_parser_request_stacked_bars(
        events,
        output_dir / f"purchase_parser_request_stacked_top_{stage_dataset}_vus{stage_vus:02d}.png",
        f"slowest purchase parser requests by component ({scope})",
        plt,
        sns,
    )


def build_intent_detail_records(
    source,
    *,
    statistic: str | None = "avg",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def metric(key: str) -> float | None:
        if statistic:
            return numeric_or_none(source.get(f"{key}_{statistic}", source.get(key)))
        return numeric_or_none(source.get(key))

    def add(key: str, label: str) -> None:
        value = metric(key)
        if value is not None and value > 0:
            records.append({"stage": label, "value": value, "key": key})

    add("intent_repository_load_ms", "repository load")
    add("intent_rule_parse_ms", "rule parser")

    llm_detail_start = len(records)
    for key, label in INTENT_LLM_STAGES:
        add(key, f"LLM {label}")
    llm_detail_sum = sum(
        record["value"]
        for record in records[llm_detail_start:]
        if record.get("key") in INTENT_DETAIL_LLM_KEYS
    )
    llm_call = metric("intent_llm_call_ms")
    llm_other = max((llm_call or 0.0) - llm_detail_sum, 0.0)
    if llm_other > 0.01:
        records.append({"stage": "LLM other", "value": llm_other, "key": "intent_llm_other_ms"})

    add("intent_llm_merge_ms", "LLM merge")
    add("intent_purchase_parse_ms", "purchase parser")
    add("intent_unattributed_ms", "unattributed")

    measured_total = sum(record["value"] for record in records)
    total = metric("intent_parse_ms")
    intent_other = max((total or 0.0) - measured_total, 0.0)
    if intent_other > 0.01:
        records.append({"stage": "intent other", "value": intent_other, "key": "intent_other_ms"})
    return records


def build_purchase_parser_detail_records(
    source,
    *,
    statistic: str | None = "avg",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def metric(key: str) -> float | None:
        if statistic:
            return numeric_or_none(source.get(f"{key}_{statistic}", source.get(key)))
        return numeric_or_none(source.get(key))

    for key, label in PURCHASE_PARSER_STAGES:
        value = metric(key)
        if value is not None and value > 0:
            records.append({"stage": label, "value": value, "key": key})

    measured_total = sum(record["value"] for record in records)
    total = metric("intent_purchase_parse_ms")
    purchase_other = max((total or 0.0) - measured_total, 0.0)
    if purchase_other > 0.01:
        records.append(
            {
                "stage": "purchase other",
                "value": purchase_other,
                "key": "intent_purchase_other_ms",
            }
        )
    return records


def plot_single_stacked_stage_bar(
    records: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
    *,
    unit: str,
    normalize: bool = False,
    legend_title: str = "intent component",
) -> None:
    total = sum(record["value"] for record in records)
    if total <= 0:
        return

    values = [
        record["value"] / total * 100 if normalize else record["value"]
        for record in records
    ]
    colors = sns.color_palette("tab10", n_colors=len(records))
    fig, ax = plt.subplots(figsize=(13.5, 4.8), layout="constrained")
    left = 0.0
    for record, value, color in zip(records, values, colors):
        ax.barh([0], [value], left=[left], color=color, label=record["stage"])
        share = record["value"] / total * 100
        if value >= (7 if normalize else max(values) * 0.08):
            label = f"{share:.0f}%" if normalize else f"{record['value']:,.0f} ms"
            ax.text(
                left + value / 2,
                0,
                label,
                ha="center",
                va="center",
                color=contrast_text_color(color),
                fontsize=8,
            )
        left += value

    ax.set_title(title)
    ax.set_xlabel(f"share of intent parser time ({unit})" if normalize else "average time (ms)")
    ax.set_yticks([0], labels=[f"total {total:,.0f} ms"])
    ax.set_xlim(0, 100 if normalize else max(sum(values), 1.0))
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.2),
        ncol=3,
        frameon=False,
        title=legend_title,
    )
    save_figure(fig, path, plt)


def plot_intent_detail_donut(
    records: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
    *,
    legend_title: str = "intent component",
) -> None:
    total = sum(record["value"] for record in records)
    if total <= 0:
        return

    labels = [record["stage"] for record in records]
    values = [record["value"] for record in records]
    colors = sns.color_palette("tab10", n_colors=len(records))
    fig, ax = plt.subplots(figsize=(8.8, 7.2), layout="constrained")
    wedges, _, autotexts = ax.pie(
        values,
        startangle=90,
        counterclock=False,
        colors=colors,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 4 else "",
        pctdistance=0.78,
    )
    for autotext in autotexts:
        autotext.set_fontsize(8)
        autotext.set_color("white")
        autotext.set_weight("bold")
    ax.text(0, 0, f"{total:,.0f} ms", ha="center", va="center", fontsize=13, weight="bold")
    ax.set_title(title)
    ax.legend(
        wedges,
        labels,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        title=legend_title,
    )
    save_figure(fig, path, plt)


def plot_intent_component_distribution(
    events: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
) -> None:
    records: list[dict[str, Any]] = []
    for event in events:
        for record in build_intent_detail_records(event, statistic=None):
            records.append(
                {
                    "component": record["stage"],
                    "duration_ms": record["value"],
                }
            )
    if not records:
        return

    components = sorted(
        {record["component"] for record in records},
        key=lambda component: statistics.median(
            record["duration_ms"]
            for record in records
            if record["component"] == component
        ),
        reverse=True,
    )
    plot_data = {
        "component": [record["component"] for record in records],
        "duration_ms": [record["duration_ms"] for record in records],
    }
    fig, ax = plt.subplots(
        figsize=(12.5, max(5.8, len(components) * 0.55)),
        layout="constrained",
    )
    sns.boxplot(
        data=plot_data,
        x="duration_ms",
        y="component",
        order=components,
        color=sns.color_palette("colorblind")[0],
        ax=ax,
        fliersize=2,
    )
    if len(records) <= 300:
        sns.stripplot(
            data=plot_data,
            x="duration_ms",
            y="component",
            order=components,
            color="black",
            alpha=0.35,
            size=2.5,
            ax=ax,
        )
    ax.set_title(title)
    ax.set_xlabel("duration per request (ms)")
    ax.set_ylabel("")
    save_figure(fig, path, plt)


def plot_intent_request_stacked_bars(
    events: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
    *,
    max_requests: int = 12,
) -> None:
    ranked_events = sorted(
        (
            event
            for event in events
            if numeric_or_none(event.get("intent_parse_ms")) is not None
        ),
        key=lambda event: float(event.get("intent_parse_ms") or 0.0),
        reverse=True,
    )[:max_requests]
    if not ranked_events:
        return

    stage_labels = []
    for event in ranked_events:
        for record in build_intent_detail_records(event, statistic=None):
            if record["stage"] not in stage_labels:
                stage_labels.append(record["stage"])
    if not stage_labels:
        return

    colors = sns.color_palette("tab10", n_colors=len(stage_labels))
    positions = list(range(len(ranked_events)))
    left = [0.0] * len(ranked_events)
    component_values_by_event = [
        {
            record["stage"]: record["value"]
            for record in build_intent_detail_records(event, statistic=None)
        }
        for event in ranked_events
    ]
    row_totals = [sum(values.values()) for values in component_values_by_event]
    label_threshold = max(row_totals or [0.0]) * 0.04
    fig, ax = plt.subplots(
        figsize=(13.5, max(6.2, len(ranked_events) * 0.45)),
        layout="constrained",
    )
    for label, color in zip(stage_labels, colors):
        values = [
            component_values.get(label, 0.0)
            for component_values in component_values_by_event
        ]
        bars = ax.barh(positions, values, left=left, color=color, label=label)
        for index, (bar, value) in enumerate(zip(bars, values)):
            if value < max(label_threshold, row_totals[index] * 0.08):
                continue
            ax.text(
                left[index] + value / 2,
                bar.get_y() + bar.get_height() / 2,
                f"{value:,.0f}",
                ha="center",
                va="center",
                color=contrast_text_color(color),
                fontsize=7,
            )
        left = [current + value for current, value in zip(left, values)]

    labels = [
        f"#{index + 1} {numeric_or_none(event.get('intent_parse_ms')):,.0f} ms"
        for index, event in enumerate(ranked_events)
    ]
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("intent parser duration (ms)")
    ax.set_ylabel("slowest request samples")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=False,
        title="intent component",
    )
    save_figure(fig, path, plt)


def plot_intent_purchase_vs_llm_scatter(
    events: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
) -> None:
    records = []
    for event in events:
        purchase_ms = numeric_or_none(event.get("intent_purchase_parse_ms"))
        llm_http_ms = numeric_or_none(event.get("intent_llm_http_ms"))
        total_ms = numeric_or_none(event.get("intent_parse_ms"))
        if purchase_ms is None or llm_http_ms is None or total_ms is None:
            continue
        records.append(
            {
                "purchase_ms": purchase_ms,
                "llm_http_ms": llm_http_ms,
                "total_ms": total_ms,
            }
        )
    if not records:
        return

    max_axis = max(
        max(record["purchase_ms"] for record in records),
        max(record["llm_http_ms"] for record in records),
    )
    sizes = [
        40 + (record["total_ms"] / max(record["total_ms"] for record in records)) * 180
        for record in records
    ]
    fig, ax = plt.subplots(figsize=(10.5, 7.0), layout="constrained")
    ax.scatter(
        [record["purchase_ms"] for record in records],
        [record["llm_http_ms"] for record in records],
        s=sizes,
        color=sns.color_palette("colorblind")[4],
        alpha=0.65,
        edgecolor="black",
        linewidth=0.5,
    )
    ax.plot([0, max_axis], [0, max_axis], linestyle="--", color="gray", linewidth=1.2)
    ax.set_title(title)
    ax.set_xlabel("purchase parser time (ms)")
    ax.set_ylabel("LLM HTTP time (ms)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    save_figure(fig, path, plt)


def plot_purchase_parser_component_distribution(
    events: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
) -> None:
    records: list[dict[str, Any]] = []
    for event in events:
        for record in build_purchase_parser_detail_records(event, statistic=None):
            records.append(
                {
                    "component": record["stage"],
                    "duration_ms": record["value"],
                }
            )
    if not records:
        return

    components = sorted(
        {record["component"] for record in records},
        key=lambda component: statistics.median(
            record["duration_ms"]
            for record in records
            if record["component"] == component
        ),
        reverse=True,
    )
    plot_data = {
        "component": [record["component"] for record in records],
        "duration_ms": [record["duration_ms"] for record in records],
    }
    fig, ax = plt.subplots(
        figsize=(12.5, max(5.8, len(components) * 0.62)),
        layout="constrained",
    )
    sns.boxplot(
        data=plot_data,
        x="duration_ms",
        y="component",
        order=components,
        color=sns.color_palette("colorblind")[1],
        ax=ax,
        fliersize=2,
    )
    if len(records) <= 300:
        sns.stripplot(
            data=plot_data,
            x="duration_ms",
            y="component",
            order=components,
            color="black",
            alpha=0.35,
            size=2.5,
            ax=ax,
        )
    ax.set_title(title)
    ax.set_xlabel("duration per request (ms)")
    ax.set_ylabel("")
    save_figure(fig, path, plt)


def plot_purchase_parser_request_stacked_bars(
    events: list[dict[str, Any]],
    path: Path,
    title: str,
    plt,
    sns,
    *,
    max_requests: int = 12,
) -> None:
    ranked_events = sorted(
        (
            event
            for event in events
            if numeric_or_none(event.get("intent_purchase_parse_ms")) is not None
        ),
        key=lambda event: float(event.get("intent_purchase_parse_ms") or 0.0),
        reverse=True,
    )[:max_requests]
    if not ranked_events:
        return

    stage_labels = []
    for event in ranked_events:
        for record in build_purchase_parser_detail_records(event, statistic=None):
            if record["stage"] not in stage_labels:
                stage_labels.append(record["stage"])
    if not stage_labels:
        return

    colors = sns.color_palette("tab10", n_colors=len(stage_labels))
    positions = list(range(len(ranked_events)))
    left = [0.0] * len(ranked_events)
    component_values_by_event = [
        {
            record["stage"]: record["value"]
            for record in build_purchase_parser_detail_records(event, statistic=None)
        }
        for event in ranked_events
    ]
    row_totals = [sum(values.values()) for values in component_values_by_event]
    label_threshold = max(row_totals or [0.0]) * 0.04
    fig, ax = plt.subplots(
        figsize=(13.5, max(6.2, len(ranked_events) * 0.45)),
        layout="constrained",
    )
    for label, color in zip(stage_labels, colors):
        values = [
            component_values.get(label, 0.0)
            for component_values in component_values_by_event
        ]
        bars = ax.barh(positions, values, left=left, color=color, label=label)
        for index, (bar, value) in enumerate(zip(bars, values)):
            if value < max(label_threshold, row_totals[index] * 0.08):
                continue
            ax.text(
                left[index] + value / 2,
                bar.get_y() + bar.get_height() / 2,
                f"{value:,.0f}",
                ha="center",
                va="center",
                color=contrast_text_color(color),
                fontsize=7,
            )
        left = [current + value for current, value in zip(left, values)]

    labels = [
        f"#{index + 1} {numeric_or_none(event.get('intent_purchase_parse_ms')):,.0f} ms"
        for index, event in enumerate(ranked_events)
    ]
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("purchase parser duration (ms)")
    ax.set_ylabel("slowest request samples")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=False,
        title="purchase component",
    )
    save_figure(fig, path, plt)


def plot_line(
    df,
    path: Path,
    *,
    x: str,
    y: str,
    hue: str,
    xlabel: str,
    ylabel: str,
    title: str,
    plt,
    sns,
) -> None:
    if y not in df.columns or df[y].dropna().empty:
        return
    plot_df = df.dropna(subset=[x, y, hue]).sort_values([hue, x])
    if plot_df.empty:
        return

    hue_order = None
    if hue == "vus_label":
        hue_order = VUS_LABEL_ORDER
    elif hue == "dataset_label":
        hue_order = DATASET_LABEL_ORDER

    fig, ax = plt.subplots(figsize=(10.5, 6.2), layout="constrained")
    sns.lineplot(
        data=plot_df,
        x=x,
        y=y,
        hue=hue,
        hue_order=hue_order,
        marker="o",
        sort=False,
        palette="colorblind",
        ax=ax,
    )
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if x == "vus":
        ax.set_xticks(VUS_ORDER)
    legend_title = "VUS" if hue == "vus_label" else "products"
    ax.legend(title=legend_title)
    save_figure(fig, path, plt)


def plot_matrix_heatmap(
    df,
    path: Path,
    *,
    value: str,
    title: str,
    colorbar_label: str,
    value_format,
    cmap: str,
    plt,
    sns,
) -> None:
    required = ["dataset", "vus", value]
    if any(column not in df.columns for column in required):
        return
    target = df.dropna(subset=required)
    if target.empty:
        return

    matrix = target.pivot_table(
        index="vus",
        columns="dataset",
        values=value,
        aggfunc="mean",
    )
    matrix = matrix.reindex(index=VUS_ORDER, columns=DATASET_ORDER)
    matrix = matrix.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if matrix.empty:
        return

    annotations = [
        ["" if math.isnan(cell) else value_format(cell) for cell in row]
        for row in matrix.to_numpy(dtype=float)
    ]
    fig, ax = plt.subplots(figsize=(10.5, 6.4), layout="constrained")
    sns.heatmap(
        matrix,
        annot=annotations,
        fmt="",
        cmap=cmap,
        linewidths=0.8,
        linecolor="white",
        cbar_kws={"label": colorbar_label},
        ax=ax,
    )
    ax.set_title(title)
    ax.set_xlabel("dataset product count")
    ax.set_ylabel("virtual users")
    ax.set_xticklabels([f"{int(label):,}" for label in matrix.columns])
    ax.set_yticklabels([f"VUS {int(label)}" for label in matrix.index], rotation=0)
    save_figure(fig, path, plt)


def plot_stage_bar(
    row,
    stages,
    path: Path,
    title: str,
    plt,
    sns,
    *,
    statistic: str,
) -> None:
    records = build_stage_records(row, stages, statistic=statistic)
    if not records:
        return
    labels = [record["stage"] for record in records]
    values = [record["value"] for record in records]

    fig, ax = plt.subplots(
        figsize=(10.5, max(4.8, len(records) * 0.62)),
        layout="constrained",
    )
    positions = list(range(len(records)))
    ax.barh(positions, values, color=sns.color_palette("colorblind")[0])
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("milliseconds")
    ax.set_ylabel("")
    annotate_horizontal_bars(ax, values, suffix="ms")
    save_figure(fig, path, plt)


def plot_stage_ratio_bar(
    row,
    stages,
    path: Path,
    title: str,
    plt,
    sns,
    *,
    statistic: str,
) -> None:
    records = build_stage_records(row, stages, statistic=statistic)
    total = sum(record["value"] for record in records)
    if total <= 0:
        return
    labels = [record["stage"] for record in records]
    values = [record["value"] / total * 100 for record in records]

    fig, ax = plt.subplots(
        figsize=(10.5, max(4.8, len(records) * 0.62)),
        layout="constrained",
    )
    positions = list(range(len(records)))
    ax.barh(positions, values, color=sns.color_palette("colorblind")[1])
    ax.set_yticks(positions, labels=labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("share of measured stages (%)")
    ax.set_ylabel("")
    annotate_horizontal_bars(ax, values, suffix="%")
    save_figure(fig, path, plt)


def plot_stage_donut(
    row,
    stages,
    path: Path,
    title: str,
    plt,
    sns,
    *,
    statistic: str,
    max_segments: int = 7,
    min_share_percent: float = 2.0,
) -> None:
    records = build_grouped_share_records(
        row,
        stages,
        statistic=statistic,
        max_segments=max_segments,
        min_share_percent=min_share_percent,
    )
    if not records:
        return

    values = [record["value"] for record in records]
    total = sum(values)
    colors = sns.color_palette("tab10", n_colors=len(records))
    fig, ax = plt.subplots(figsize=(11.5, 6.6), layout="constrained")
    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.2},
    )
    ax.text(
        0,
        0,
        f"{total:,.0f} ms\nmeasured average",
        ha="center",
        va="center",
        fontsize=12,
    )
    legend_labels = [
        f"{record['stage']}: {record['value']:,.1f} ms "
        f"({record['share_percent']:.1f}%)"
        for record in records
    ]
    ax.legend(
        wedges,
        legend_labels,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        title="measured share",
    )
    ax.set_title(title)
    ax.set_aspect("equal")
    save_figure(fig, path, plt)


def plot_stage_pareto(
    row,
    stages,
    path: Path,
    title: str,
    plt,
    sns,
    *,
    statistic: str,
) -> None:
    records = sorted(
        build_stage_records(row, stages, statistic=statistic),
        key=lambda record: record["value"],
        reverse=True,
    )
    total = sum(record["value"] for record in records)
    if total <= 0:
        return

    labels = [record["stage"] for record in records]
    values = [record["value"] for record in records]
    cumulative: list[float] = []
    running_total = 0.0
    for value in values:
        running_total += value
        cumulative.append(running_total / total * 100)

    positions = list(range(len(records)))
    palette = sns.color_palette("colorblind")
    fig, ax = plt.subplots(figsize=(12.5, 7.0), layout="constrained")
    bars = ax.bar(positions, values, color=palette[0])
    ax.set_title(title)
    ax.set_xlabel("pipeline stage ordered by average time")
    ax.set_ylabel("average time (ms)")
    ax.set_xticks(positions, labels=labels, rotation=35, ha="right")
    ax.bar_label(
        bars,
        labels=[f"{value:,.0f}" for value in values],
        padding=3,
        fontsize=8,
    )

    share_ax = ax.twinx()
    share_ax.plot(
        positions,
        cumulative,
        color=palette[3],
        marker="o",
        linewidth=2.2,
        label="cumulative share",
    )
    share_ax.axhline(
        80,
        color=palette[2],
        linestyle="--",
        linewidth=1.4,
        label="80% reference",
    )
    share_ax.set_ylabel("cumulative measured time (%)")
    share_ax.set_ylim(0, 105)
    share_ax.legend(loc="center right")
    save_figure(fig, path, plt)


def plot_stage_composition_by_vus(
    df,
    stages,
    path: Path,
    *,
    stage_dataset: int,
    plt,
    sns,
) -> None:
    rows = []
    for vus in VUS_ORDER:
        target = df[(df["dataset"] == stage_dataset) & (df["vus"] == vus)]
        if target.empty:
            continue
        row = target.sort_values("run_id").iloc[-1]
        records = build_stage_records(row, stages, statistic="avg")
        total = sum(record["value"] for record in records)
        if total <= 0:
            continue
        rows.append(
            {
                "vus": vus,
                "shares": {
                    record["stage"]: record["value"] / total * 100
                    for record in records
                },
            }
        )
    if not rows:
        return

    stage_labels = [label for _, label in stages]
    average_shares = {
        label: statistics.mean(row["shares"].get(label, 0.0) for row in rows)
        for label in stage_labels
    }
    ranked_labels = sorted(stage_labels, key=average_shares.get, reverse=True)
    kept_labels = [
        label for label in ranked_labels if average_shares[label] >= 1.5
    ][:7]
    other_labels = [label for label in stage_labels if label not in kept_labels]
    display_labels = kept_labels + (["other"] if other_labels else [])

    colors = sns.color_palette("tab10", n_colors=len(display_labels))
    positions = list(range(len(rows)))
    left = [0.0] * len(rows)
    fig, ax = plt.subplots(figsize=(12.5, 6.6), layout="constrained")
    for label, color in zip(display_labels, colors):
        if label == "other":
            values = [
                sum(row["shares"].get(item, 0.0) for item in other_labels)
                for row in rows
            ]
            legend_label = f"other ({len(other_labels)} stages)"
        else:
            values = [row["shares"].get(label, 0.0) for row in rows]
            legend_label = label
        bars = ax.barh(
            positions,
            values,
            left=left,
            color=color,
            label=legend_label,
        )
        for index, (bar, value) in enumerate(zip(bars, values)):
            if value < 7:
                continue
            ax.text(
                left[index] + value / 2,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.0f}%",
                ha="center",
                va="center",
                color=contrast_text_color(color),
                fontsize=8,
            )
        left = [current + value for current, value in zip(left, values)]

    ax.set_title(f"pipeline stage composition by VUS ({stage_dataset:,} products)")
    ax.set_xlabel("share of measured stages (%)")
    ax.set_ylabel("")
    ax.set_xlim(0, 100)
    ax.set_yticks(positions, labels=[f"VUS {row['vus']}" for row in rows])
    ax.invert_yaxis()
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=False,
        title="pipeline stage",
    )
    save_figure(fig, path, plt)


def plot_stage_share_comparison(
    df,
    stages,
    path: Path,
    *,
    datasets: list[int],
    stage_vus: int,
    plt,
    sns,
) -> None:
    comparison_rows = []
    for dataset in dict.fromkeys(datasets):
        target = df[(df["dataset"] == dataset) & (df["vus"] == stage_vus)]
        if target.empty:
            continue
        row = target.sort_values("run_id").iloc[-1]
        records = build_stage_records(row, stages, statistic="avg")
        total = sum(record["value"] for record in records)
        if total <= 0:
            continue
        comparison_rows.append(
            {
                "dataset": dataset,
                "total": total,
                "shares": {
                    record["stage"]: record["value"] / total * 100
                    for record in records
                },
            }
        )
    if len(comparison_rows) < 2:
        return

    stage_labels = [label for _, label in stages]
    average_shares = {
        label: statistics.mean(
            row["shares"].get(label, 0.0) for row in comparison_rows
        )
        for label in stage_labels
    }
    ranked_labels = sorted(stage_labels, key=average_shares.get, reverse=True)
    kept_labels = [
        label for label in ranked_labels if average_shares[label] >= 1.5
    ][:7]
    other_labels = [label for label in stage_labels if label not in kept_labels]
    display_labels = kept_labels + (["other"] if other_labels else [])
    colors = sns.color_palette("tab10", n_colors=len(display_labels))

    def display_share(row, label: str) -> float:
        if label == "other":
            return sum(row["shares"].get(item, 0.0) for item in other_labels)
        return row["shares"].get(label, 0.0)

    fig, axes = plt.subplots(
        1,
        len(comparison_rows),
        figsize=(14.5, 7.0),
        layout="constrained",
    )
    for ax, row in zip(axes, comparison_rows):
        values = [display_share(row, label) for label in display_labels]
        ax.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            autopct=lambda percent: f"{percent:.1f}%" if percent >= 4 else "",
            pctdistance=0.78,
            textprops={"fontsize": 8},
            wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.2},
        )
        ax.text(
            0,
            0,
            f"{row['total']:,.0f} ms\nmeasured average",
            ha="center",
            va="center",
            fontsize=11,
        )
        ax.set_title(f"{row['dataset']:,} products")
        ax.set_aspect("equal")

    legend_labels = []
    for label in display_labels:
        readable_label = (
            f"other ({len(other_labels)} stages)" if label == "other" else label
        )
        shares = " / ".join(
            f"{row['dataset']:,}: {display_share(row, label):.1f}%"
            for row in comparison_rows
        )
        legend_labels.append(f"{readable_label} — {shares}")
    fig.legend(
        axes[0].patches[: len(display_labels)],
        legend_labels,
        loc="outside lower center",
        ncol=2,
        frameon=False,
        title="stage share by product count",
    )
    fig.suptitle(f"pipeline stage share comparison (VUS {stage_vus})")
    save_figure(fig, path, plt)


def plot_client_vs_backend_p95(df, path: Path, *, stage_dataset: int, plt) -> None:
    required = ["vus", "latency_p95_ms", "duration_ms_p95"]
    if any(column not in df.columns for column in required):
        return
    target = df[df["dataset"] == stage_dataset].dropna(subset=required).sort_values("vus")
    if target.empty:
        return

    fig, ax = plt.subplots(figsize=(10.5, 6.2), layout="constrained")
    ax.plot(
        target["vus"],
        target["latency_p95_ms"],
        marker="o",
        linewidth=2.2,
        label="client-observed p95",
    )
    ax.plot(
        target["vus"],
        target["duration_ms_p95"],
        marker="o",
        linewidth=2.2,
        label="backend pipeline p95",
    )
    ax.set_title(f"client vs backend p95 ({stage_dataset:,} products)")
    ax.set_xlabel("virtual users")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_xticks(VUS_ORDER)
    ax.legend()
    save_figure(fig, path, plt)


def plot_resource_timeseries(
    row,
    output_dir: Path,
    *,
    stage_dataset: int,
    stage_vus: int,
    plt,
) -> None:
    run_dir = Path(str(row.get("run_dir") or ""))
    records = load_resource_timeseries_records(run_dir / "resources" / "docker-stats.csv")
    if not records:
        return

    scope = f"{stage_dataset:,} products / VUS {stage_vus}"
    plot_resource_metric_timeseries(
        records,
        output_dir / f"resource_cpu_timeseries_{stage_dataset}_vus{stage_vus:02d}.png",
        metric="cpu_percent",
        ylabel="container CPU (%; 100% = one core)",
        title=f"container CPU over time ({scope})",
        plt=plt,
    )
    plot_resource_metric_timeseries(
        records,
        output_dir / f"resource_memory_timeseries_{stage_dataset}_vus{stage_vus:02d}.png",
        metric="mem_percent",
        ylabel="container memory usage (%)",
        title=f"container memory over time ({scope})",
        plt=plt,
    )


def load_resource_timeseries_records(path: Path) -> list[dict[str, Any]]:
    raw_rows = load_docker_stats_rows(path)
    records: list[dict[str, Any]] = []
    for row in raw_rows:
        timestamp = parse_iso_timestamp(row.get("timestamp"))
        service = identify_resource_service(row.get("name"))
        cpu_percent = parse_percent(row.get("cpu_percent"))
        mem_percent = parse_percent(row.get("mem_percent"))
        if timestamp is None or service is None:
            continue
        records.append(
            {
                "timestamp": timestamp,
                "service": service,
                "cpu_percent": cpu_percent,
                "mem_percent": mem_percent,
            }
        )
    if not records:
        return []

    started_at = min(record["timestamp"] for record in records)
    for record in records:
        record["elapsed_seconds"] = (record["timestamp"] - started_at).total_seconds()
    return records


def parse_iso_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def identify_resource_service(value: Any) -> str | None:
    name = str(value or "").lower()
    for service in ("backend", "elasticsearch", "redis"):
        if service in name:
            return service
    return None


def plot_resource_metric_timeseries(
    records: list[dict[str, Any]],
    path: Path,
    *,
    metric: str,
    ylabel: str,
    title: str,
    plt,
) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6.2), layout="constrained")
    plotted = False
    for service in ("backend", "elasticsearch", "redis"):
        service_records = sorted(
            (
                record
                for record in records
                if record["service"] == service and record.get(metric) is not None
            ),
            key=lambda record: record["elapsed_seconds"],
        )
        if not service_records:
            continue
        plotted = True
        ax.plot(
            [record["elapsed_seconds"] for record in service_records],
            [record[metric] for record in service_records],
            linewidth=2,
            label=service,
        )
    if not plotted:
        plt.close(fig)
        return
    ax.set_title(title)
    ax.set_xlabel("elapsed time (seconds)")
    ax.set_ylabel(ylabel)
    ax.legend(title="container")
    save_figure(fig, path, plt)


def plot_optimization_timeline(
    df,
    path: Path,
    *,
    stage_dataset: int,
    stage_vus: int,
    plt,
    sns,
) -> None:
    if "latency_p95_ms" not in df.columns:
        return
    target = df[(df["dataset"] == stage_dataset) & (df["vus"] == stage_vus)]
    target = target.dropna(subset=["group", "latency_p95_ms"])
    if len(target["group"].unique()) < 2:
        return

    target = target.sort_values("group")
    fig, ax = plt.subplots(figsize=(10.5, 6.2), layout="constrained")
    sns.lineplot(data=target, x="group", y="latency_p95_ms", marker="o", ax=ax)
    ax.set_title(f"optimization timeline p95 ({stage_dataset}, VUS {stage_vus})")
    ax.set_xlabel("experiment step")
    ax.set_ylabel("p95 latency (ms)")
    ax.tick_params(axis="x", rotation=25)
    save_figure(fig, path, plt)


def build_stage_records(
    row,
    stages,
    *,
    statistic: str = "avg",
) -> list[dict[str, Any]]:
    records = []
    for key, label in stages:
        value = numeric_or_none(row.get(f"{key}_{statistic}", row.get(key)))
        if value is not None and value > 0:
            records.append({"stage": label, "value": value})
    return records


def build_grouped_share_records(
    row,
    stages,
    *,
    statistic: str = "avg",
    max_segments: int = 7,
    min_share_percent: float = 2.0,
) -> list[dict[str, Any]]:
    records = build_stage_records(row, stages, statistic=statistic)
    total = sum(record["value"] for record in records)
    if total <= 0 or max_segments < 1:
        return []

    ranked = sorted(records, key=lambda record: record["value"], reverse=True)
    eligible = [
        record
        for record in ranked
        if record["value"] / total * 100 >= min_share_percent
    ]
    kept = eligible[:max_segments]
    grouped = [record for record in ranked if record not in kept]
    if grouped and len(kept) == max_segments:
        grouped.append(kept.pop())

    result = [
        {
            **record,
            "share_percent": record["value"] / total * 100,
        }
        for record in kept
    ]
    if grouped:
        grouped_value = sum(record["value"] for record in grouped)
        result.append(
            {
                "stage": f"other ({len(grouped)} stages)",
                "value": grouped_value,
                "share_percent": grouped_value / total * 100,
            }
        )
    return result


def save_figure(fig, path: Path, plt) -> None:
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def contrast_text_color(color) -> str:
    red, green, blue = color[:3]
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "black" if luminance > 0.58 else "white"


def annotate_horizontal_bars(ax, values: list[float], *, suffix: str) -> None:
    if not values:
        return
    max_value = max(values)
    offset = max_value * 0.01 if max_value else 0.1
    for index, value in enumerate(values):
        label = f"{value:.1f}{suffix}"
        ax.text(value + offset, index, label, va="center", fontsize=9)
    ax.set_xlim(right=max_value * 1.18 if max_value else 1)


def row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    dataset = int_value(row.get("dataset")) or 0
    dataset_rank = DATASET_ORDER.index(dataset) if dataset in DATASET_ORDER else len(DATASET_ORDER)
    return (str(row.get("group") or ""), int_value(row.get("vus")) or 0, dataset_rank, dataset)


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def nested_get(data: dict[str, Any], keys: list[str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return math.nan
    sorted_values = sorted(values)
    index = math.ceil((percent / 100) * len(sorted_values)) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def int_value(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def float_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def numeric_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    return None


if __name__ == "__main__":
    main()
