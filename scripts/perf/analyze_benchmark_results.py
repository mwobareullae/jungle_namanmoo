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
from pathlib import Path
from typing import Any


RUN_NAME_RE = re.compile(
    r"^recommendation-(?P<dataset>\d+)-(?P<user_type>.+)-(?P<started_at>\d{8}-\d{6})$"
)
VUS_RE = re.compile(r"vus(?P<vus>\d+)", re.IGNORECASE)

DATASET_ORDER = [1000, 5000, 10000, 80000]

PIPELINE_STAGES = [
    ("intent_parse_ms", "intent"),
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
    df = pd.DataFrame(rows)
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

    return {
        "latency_avg_ms": float_value(duration_metric.get("avg")),
        "latency_p50_ms": float_value(duration_metric.get("med")),
        "latency_p90_ms": float_value(duration_metric.get("p(90)")),
        "latency_p95_ms": float_value(duration_metric.get("p(95)")),
        "latency_max_ms": float_value(duration_metric.get("max")),
        "rps": float_value(reqs_metric.get("rate")),
        "request_count": int_value(reqs_metric.get("count")),
        "iteration_count": int_value(iterations_metric.get("count")),
        "http_req_failed_rate": float_value(failed_metric.get("value")),
        "check_success_rate": float_value(checks_metric.get("value")),
    }


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
    return result


def load_pipeline_events(log_path: Path) -> list[dict[str, Any]]:
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
        if event.get("event") == "recommendation_pipeline_completed":
            events.append(event)
    return events


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
        "http_req_failed_rate",
        "request_count",
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
        x="dataset",
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
        x="dataset",
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
        x="dataset",
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
        output_dir / "error_rate_by_dataset.png",
        x="dataset",
        y="http_req_failed_rate",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="HTTP request failure rate",
        title="error rate by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "backend_cpu_peak_by_dataset.png",
        x="dataset",
        y="resource_backend_cpu_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="backend CPU peak (%)",
        title="backend CPU peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "backend_memory_peak_by_dataset.png",
        x="dataset",
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
        x="dataset",
        y="resource_elasticsearch_cpu_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="Elasticsearch CPU peak (%)",
        title="Elasticsearch CPU peak by dataset",
        plt=plt,
        sns=sns,
    )
    plot_line(
        df,
        output_dir / "elasticsearch_memory_peak_by_dataset.png",
        x="dataset",
        y="resource_elasticsearch_mem_percent_max",
        hue="vus_label",
        xlabel="dataset product count",
        ylabel="Elasticsearch memory peak (%)",
        title="Elasticsearch memory peak by dataset",
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

    plot_stage_bar(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        "pipeline stage average (ms)",
        plt,
        sns,
    )
    plot_stage_ratio_bar(
        row,
        PIPELINE_STAGES,
        output_dir / f"pipeline_stage_ratio_{stage_dataset}_vus{stage_vus:02d}.png",
        "pipeline stage ratio (%)",
        plt,
        sns,
    )
    plot_stage_bar(
        row,
        SCORING_STAGES,
        output_dir / f"scoring_stage_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        "scoring stage average (ms)",
        plt,
        sns,
    )
    prefetch_columns = [
        (f"prefetch_{field}_avg", label)
        for field, label in SCORING_PREFETCH_FIELDS
    ]
    plot_stage_bar(
        row,
        prefetch_columns,
        output_dir / f"scoring_prefetch_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        "scoring prefetch average (ms)",
        plt,
        sns,
    )
    plot_stage_bar(
        row,
        CONTEXT_LOAD_STAGES,
        output_dir / f"context_load_breakdown_{stage_dataset}_vus{stage_vus:02d}.png",
        "context load average (ms)",
        plt,
        sns,
    )
    plot_optimization_timeline(
        df,
        output_dir / f"optimization_timeline_p95_{stage_dataset}_vus{stage_vus:02d}.png",
        stage_dataset=stage_dataset,
        stage_vus=stage_vus,
        plt=plt,
        sns=sns,
    )


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
    plot_df = df.dropna(subset=[x, y, hue]).sort_values([x, hue])
    if plot_df.empty:
        return

    plt.figure(figsize=(9.5, 5.5))
    sns.set_theme(style="whitegrid")
    ax = sns.lineplot(data=plot_df, x=x, y=y, hue=hue, marker="o")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if x == "dataset":
        ax.set_xticks(DATASET_ORDER)
    ax.legend(title=hue.replace("_", " "))
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_stage_bar(row, stages, path: Path, title: str, plt, sns) -> None:
    records = build_stage_records(row, stages)
    if not records:
        return
    labels = [record["stage"] for record in records]
    values = [record["value"] for record in records]

    plt.figure(figsize=(9.5, max(4.5, len(records) * 0.55)))
    sns.set_theme(style="whitegrid")
    ax = sns.barplot(x=values, y=labels, orient="h", color=sns.color_palette()[0])
    ax.set_title(title)
    ax.set_xlabel("milliseconds")
    ax.set_ylabel("")
    annotate_horizontal_bars(ax, values, suffix="ms")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def plot_stage_ratio_bar(row, stages, path: Path, title: str, plt, sns) -> None:
    records = build_stage_records(row, stages)
    total = sum(record["value"] for record in records)
    if total <= 0:
        return
    labels = [record["stage"] for record in records]
    values = [record["value"] / total * 100 for record in records]

    plt.figure(figsize=(9.5, max(4.5, len(records) * 0.55)))
    sns.set_theme(style="whitegrid")
    ax = sns.barplot(x=values, y=labels, orient="h", color=sns.color_palette()[1])
    ax.set_title(title)
    ax.set_xlabel("share of measured stages (%)")
    ax.set_ylabel("")
    annotate_horizontal_bars(ax, values, suffix="%")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


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
    plt.figure(figsize=(9.5, 5.5))
    sns.set_theme(style="whitegrid")
    ax = sns.lineplot(data=target, x="group", y="latency_p95_ms", marker="o")
    ax.set_title(f"optimization timeline p95 ({stage_dataset}, VUS {stage_vus})")
    ax.set_xlabel("experiment step")
    ax.set_ylabel("p95 latency (ms)")
    ax.tick_params(axis="x", rotation=25)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def build_stage_records(row, stages) -> list[dict[str, Any]]:
    records = []
    for key, label in stages:
        value = numeric_or_none(row.get(f"{key}_avg", row.get(key)))
        if value is not None and value > 0:
            records.append({"stage": label, "value": value})
    return records


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
