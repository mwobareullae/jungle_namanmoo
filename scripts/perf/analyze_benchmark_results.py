"""Generate recommendation benchmark summary CSV and portfolio graphs.

The script reads benchmark run folders produced by scripts/perf/benchmarkctl-local.ps1.
It supports both old logs that only have pipeline-level timings and newer logs
that include scoring/context breakdown fields.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from datetime import datetime
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
]

SCORING_PREFETCH_FIELDS = [
    ("ingredient_effects_ms", "ingredient effects"),
    ("functional_info_ms", "functional info"),
    ("skin_tags_ms", "skin tags"),
    ("skin_profiles_ms", "skin profiles"),
    ("risk_flags_ms", "risk flags"),
    ("market_signals_ms", "market signals"),
    ("review_metrics_ms", "review metrics"),
    ("review_segments_ms", "review segments"),
    ("behavior_signals_ms", "behavior signals"),
]

CONTEXT_LOAD_STAGES = [
    ("user_context_load_ms", "saved profile"),
    ("skin_test_context_load_ms", "skin test"),
    ("behavior_context_load_ms", "behavior"),
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


def main() -> None:
    args = parse_args()
    input_dir = args.input.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = collect_rows(input_dir)
    if not rows:
        raise SystemExit(f"No benchmark runs found under: {input_dir}")

    rows = sorted(rows, key=row_sort_key)
    write_summary_csv(rows, output_dir / "summary.csv")

    pd, plt, sns = load_plot_dependencies()
    df = prepare_plot_dataframe(pd.DataFrame(rows), pd)
    sns.set_theme(style="whitegrid", context="talk")
    plot_summary_graphs(df, output_dir, plt, sns)
    plot_stage_graphs(
        df,
        output_dir,
        plt,
        sns,
        stage_dataset=args.stage_dataset,
        stage_vus=args.stage_vus,
    )

    print(f"summary={output_dir / 'summary.csv'}")
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
    return parser.parse_args()


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


def plot_summary_graphs(df, output_dir: Path, plt, sns) -> None:
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
        output_dir / "backend_cpu_peak_by_dataset.png",
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
        output_dir / "backend_memory_peak_by_dataset.png",
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
        output_dir / "elasticsearch_cpu_peak_by_dataset.png",
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
        output_dir / "elasticsearch_memory_peak_by_dataset.png",
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
    output_dir: Path,
    plt,
    sns,
    *,
    stage_dataset: int,
    stage_vus: int,
) -> None:
    target = df[(df["dataset"] == stage_dataset) & (df["vus"] == stage_vus)]
    if target.empty:
        return
    row = target.sort_values("run_id").iloc[-1]
    scope = f"{stage_dataset:,} products / VUS {stage_vus}"

    plot_stage_bar(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_ratio_bar(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_ratio_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage share of average latency ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_donut(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline stage share ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_pareto(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_pareto_{stage_dataset}_vus{stage_vus:02d}.png",
        f"pipeline bottleneck Pareto ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_composition_by_vus(
        df,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_share_by_vus_{stage_dataset}.png",
        stage_dataset=stage_dataset,
        plt=plt,
        sns=sns,
    )
    plot_stage_share_comparison(
        df,
        PIPELINE_STAGES,
        output_dir
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
        SCORING_STAGES,
        output_dir / f"scoring_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        SCORING_STAGES,
        output_dir / f"scoring_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_donut(
        row,
        SCORING_STAGES,
        output_dir / f"scoring_stage_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring stage share ({scope})",
        plt,
        sns,
        statistic="avg",
        max_segments=len(SCORING_STAGES),
        min_share_percent=0,
    )
    prefetch_columns = [
        (f"prefetch_{field}", label)
        for field, label in SCORING_PREFETCH_FIELDS
    ]
    plot_stage_bar(
        row,
        prefetch_columns,
        output_dir / f"scoring_prefetch_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring prefetch average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        prefetch_columns,
        output_dir / f"scoring_prefetch_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"scoring prefetch p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        CONTEXT_LOAD_STAGES,
        output_dir / f"context_load_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"personalization context average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        CONTEXT_LOAD_STAGES,
        output_dir / f"context_load_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"personalization context p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        INTENT_STAGES,
        output_dir / f"intent_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"intent parser average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_bar(
        row,
        INTENT_STAGES,
        output_dir / f"intent_stage_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        f"intent parser p95 ({scope})",
        plt,
        sns,
        statistic="p95",
    )
    plot_stage_bar(
        row,
        INTENT_LLM_STAGES,
        output_dir / f"intent_llm_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser detail average ({scope})",
        plt,
        sns,
        statistic="avg",
    )
    plot_stage_donut(
        row,
        INTENT_LLM_STAGES,
        output_dir / f"intent_llm_share_donut_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser measured share ({scope})",
        plt,
        sns,
        statistic="avg",
        max_segments=len(INTENT_LLM_STAGES),
        min_share_percent=0,
    )
    plot_intent_outcomes(
        row,
        output_dir / f"intent_llm_outcomes_{stage_dataset}_vus{stage_vus:02d}.png",
        f"LLM parser outcomes ({scope})",
        plt,
        sns,
    )
    plot_client_vs_backend_p95(
        df,
        output_dir / f"client_vs_backend_p95_{stage_dataset}.png",
        stage_dataset=stage_dataset,
        plt=plt,
    )
    plot_resource_timeseries(
        row,
        output_dir,
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
    )
    plot_optimization_timeline(
        df,
        output_dir / f"optimization_timeline_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )


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
