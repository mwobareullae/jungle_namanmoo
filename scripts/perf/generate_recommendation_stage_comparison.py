"""Generate exact Baseline-to-Opt3 recommendation performance comparisons."""

from __future__ import annotations

import argparse
import math
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.perf import recommendation_performance_report_data as report_data


STAGE_IDS = (
    "baseline-v1",
    "opt1-es-retrieval",
    "opt2-precomputed-features",
    "opt3-bulk-prefetch",
)

PIPELINE_COMPONENTS = (
    ("user_context_load_ms", "User profile"),
    ("skin_test_context_load_ms", "Skin test"),
    ("behavior_context_load_ms", "Behavior context"),
    ("intent_parse_ms", "Intent parse"),
    ("run_save_ms", "Run save"),
    ("candidate_pool_ms", "Candidate retrieval"),
    ("search_match_ms", "Search match"),
    ("search_candidate_save_ms", "Candidate save"),
    ("scoring_ms", "Personalized scoring"),
    ("result_save_ms", "Result save"),
    ("commit_ms", "Commit"),
    ("response_load_ms", "Response load"),
)

PIPELINE_GROUPS = (
    ("User context", ("user_context_load_ms", "skin_test_context_load_ms", "behavior_context_load_ms")),
    ("Intent parse", ("intent_parse_ms",)),
    ("Candidate retrieval", ("candidate_pool_ms", "search_match_ms")),
    ("Intermediate writes", ("run_save_ms", "search_candidate_save_ms")),
    ("Personalized scoring", ("scoring_ms",)),
    ("Result delivery", ("result_save_ms", "commit_ms", "response_load_ms")),
)

SCORING_COMPONENTS = (
    ("scoring_ms", "Scoring total"),
    ("scoring_data_prefetch_ms", "Feature prefetch"),
    ("score_loop_ms", "Score loop"),
    ("score_detail_materialization_ms", "Detail materialization"),
    ("score_context_build_ms", "Context build"),
    ("score_sort_ms", "Sort"),
)

TRANSITIONS = (
    ("baseline-v1", "opt1-es-retrieval", "Opt1"),
    ("opt1-es-retrieval", "opt2-precomputed-features", "Opt2"),
    ("opt2-precomputed-features", "opt3-bulk-prefetch", "Opt3"),
)

STAGE_COLORS = {
    "baseline-v1": "#6B7280",
    "opt1-es-retrieval": "#2563EB",
    "opt2-precomputed-features": "#0F766E",
    "opt3-bulk-prefetch": "#EA580C",
}

GROUP_COLORS = {
    "User context": "#4E79A7",
    "Intent parse": "#A66DD4",
    "Candidate retrieval": "#F28E2B",
    "Intermediate writes": "#9C755F",
    "Personalized scoring": "#E15759",
    "Result delivery": "#59A14F",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("scripts/perf/recommendation-performance-report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/performance/results/recommendation/transitions"),
    )
    parser.add_argument(
        "--local-output",
        type=Path,
        default=Path("perf-runs/transitions"),
        help="Local transition index linked from stage analysis README files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    registry_path = args.registry if args.registry.is_absolute() else repo_root / args.registry
    output_root = args.output if args.output.is_absolute() else repo_root / args.output
    local_output_root = (
        args.local_output if args.local_output.is_absolute() else repo_root / args.local_output
    )
    registry = report_data.load_registry(repo_root, registry_path)
    all_rows = report_data.collect_report_rows(repo_root, registry)
    stage_defs = {stage["id"]: stage for stage in registry["stages"]}
    stage_rows = select_comparable_rows(all_rows)
    validate_stage_rows(stage_rows)

    summaries = build_stage_summaries(stage_rows, stage_defs)
    transitions = build_transition_rows(summaries)
    pipeline_metrics = build_component_metrics(stage_rows, PIPELINE_COMPONENTS)
    pipeline_deltas = build_component_deltas(pipeline_metrics, PIPELINE_COMPONENTS)
    scoring_metrics = build_component_metrics(stage_rows, SCORING_COMPONENTS)

    if output_root.exists():
        shutil.rmtree(output_root)
    data_dir = output_root / "data"
    charts_dir = output_root / "charts"
    data_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    report_data.write_csv_rows(data_dir / "stage-summary.csv", summaries)
    report_data.write_csv_rows(data_dir / "stage-transition-deltas.csv", transitions)
    report_data.write_csv_rows(data_dir / "pipeline-component-metrics.csv", pipeline_metrics)
    report_data.write_csv_rows(data_dir / "pipeline-component-deltas.csv", pipeline_deltas)
    report_data.write_csv_rows(data_dir / "scoring-component-metrics.csv", scoring_metrics)
    report_data.write_csv_rows(data_dir / "run-sources.csv", build_run_sources(stage_rows))

    plt = load_plotting()
    configure_plotting(plt)
    plot_total_latency(plt, charts_dir / "01-total-latency-trend.png", summaries)
    plot_p95_waterfall(plt, charts_dir / "02-stepwise-p95-waterfall.png", summaries, transitions)
    plot_pipeline_stacked(plt, charts_dir / "03-pipeline-average-evolution.png", pipeline_metrics, summaries)
    plot_transition_components(
        plt,
        charts_dir / "04-component-reduction-by-transition.png",
        pipeline_deltas,
    )
    plot_pipeline_heatmap(plt, charts_dir / "05-pipeline-p95-heatmap.png", pipeline_metrics)
    plot_scoring_drilldown(plt, charts_dir / "06-scoring-breakdown-trend.png", scoring_metrics)
    plot_total_component_reduction(
        plt,
        charts_dir / "07-baseline-to-opt3-component-reduction.png",
        pipeline_deltas,
    )
    write_readme(
        output_root / "README.md",
        summaries,
        transitions,
        pipeline_metrics,
        pipeline_deltas,
        scoring_metrics,
    )
    write_transition_readmes(output_root, summaries, transitions)
    write_local_transition_readmes(local_output_root, transitions)
    print(f"generated={output_root}")


def select_comparable_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for stage_id in STAGE_IDS:
        candidates = [
            row
            for row in rows
            if row.get("implementation_stage") == stage_id
            and row.get("complete")
            and row.get("condition_matches")
            and row.get("headline_selected", True)
        ]
        if stage_id != "baseline-v1":
            candidates = [row for row in candidates if row.get("error_gate_passed")]
        selected[stage_id] = sorted(candidates, key=report_data.row_sort_key)
    return selected


def validate_stage_rows(stage_rows: dict[str, list[dict[str, Any]]]) -> None:
    missing = [stage_id for stage_id in STAGE_IDS if not stage_rows.get(stage_id)]
    if missing:
        raise SystemExit(f"Missing comparable stage runs: {', '.join(missing)}")
    opt3_schemas = {row.get("measurement_schema") for row in stage_rows["opt3-bulk-prefetch"]}
    if opt3_schemas != {"bulk-prefetch-v4"}:
        raise SystemExit(f"Opt3 runs must use bulk-prefetch-v4 metrics: {sorted(opt3_schemas)}")


def build_stage_summaries(
    stage_rows: dict[str, list[dict[str, Any]]],
    stage_defs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics = (
        "latency_avg_ms",
        "latency_p95_ms",
        "duration_ms_avg",
        "duration_ms_p95",
        "recommendation_rps",
        "error_rate",
    )
    summaries: list[dict[str, Any]] = []
    baseline_p95 = median_metric(stage_rows["baseline-v1"], "latency_p95_ms")
    previous_p95: float | None = None
    for stage_id in STAGE_IDS:
        rows = stage_rows[stage_id]
        summary: dict[str, Any] = {
            "stage_id": stage_id,
            "stage_label": stage_defs[stage_id]["label"],
            "stage_order": STAGE_IDS.index(stage_id),
            "run_count": len(rows),
            "measurement_schemas": ";".join(sorted({str(row["measurement_schema"]) for row in rows})),
            "run_ids": ";".join(str(row["run_id"]) for row in rows),
        }
        for metric in metrics:
            summary[metric] = median_metric(rows, metric)
        current_p95 = float(summary["latency_p95_ms"])
        summary["change_from_previous_p95_ms"] = (
            None if previous_p95 is None else previous_p95 - current_p95
        )
        summary["change_from_previous_pct"] = (
            None if previous_p95 is None else percent_reduction(previous_p95, current_p95)
        )
        summary["reduction_from_baseline_p95_ms"] = baseline_p95 - current_p95
        summary["reduction_from_baseline_pct"] = percent_reduction(baseline_p95, current_p95)
        summaries.append(summary)
        previous_p95 = current_p95
    return summaries


def build_transition_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_stage = {row["stage_id"]: row for row in summaries}
    result: list[dict[str, Any]] = []
    for before_id, after_id, label in TRANSITIONS:
        before = by_stage[before_id]
        after = by_stage[after_id]
        result.append(
            {
                "optimization": label,
                "before_stage": before_id,
                "after_stage": after_id,
                "e2e_p95_before_ms": before["latency_p95_ms"],
                "e2e_p95_after_ms": after["latency_p95_ms"],
                "e2e_p95_reduction_ms": before["latency_p95_ms"] - after["latency_p95_ms"],
                "e2e_p95_reduction_pct": percent_reduction(before["latency_p95_ms"], after["latency_p95_ms"]),
                "e2e_avg_reduction_ms": before["latency_avg_ms"] - after["latency_avg_ms"],
                "backend_p95_reduction_ms": before["duration_ms_p95"] - after["duration_ms_p95"],
                "rps_before": before["recommendation_rps"],
                "rps_after": after["recommendation_rps"],
                "rps_gain_pct": percent_gain(before["recommendation_rps"], after["recommendation_rps"]),
                "error_rate_before": before["error_rate"],
                "error_rate_after": after["error_rate"],
                "before_run_count": before["run_count"],
                "after_run_count": after["run_count"],
                "before_run_ids": before["run_ids"],
                "after_run_ids": after["run_ids"],
            }
        )
    return result


def write_transition_readmes(
    output_root: Path,
    summaries: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> None:
    summary_by_stage = {row["stage_id"]: row for row in summaries}
    for transition in transitions:
        before = summary_by_stage[transition["before_stage"]]
        after = summary_by_stage[transition["after_stage"]]
        transition_dir = output_root / str(transition["after_stage"])
        transition_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "<!-- Generated by scripts/perf/generate_recommendation_stage_comparison.py. -->",
            f"# {transition['optimization']} 단계 전환 결과",
            "",
            "## 비교 조건",
            "",
            "- 79,952개 / full-personalized / VUS10 / 3분 / cold cache",
            f"- 이전 단계: `{transition['before_stage']}` ({transition['before_run_count']}회)",
            f"- 이후 단계: `{transition['after_stage']}` ({transition['after_run_count']}회)",
            "",
            "## 핵심 변화",
            "",
            "| 지표 | 이전 | 이후 | 변화 |",
            "|---|---:|---:|---:|",
            f"| E2E p95 | {format_ms(transition['e2e_p95_before_ms'])} | {format_ms(transition['e2e_p95_after_ms'])} | -{format_ms(transition['e2e_p95_reduction_ms'])} ({float(transition['e2e_p95_reduction_pct']):.2f}%) |",
            f"| RPS | {float(transition['rps_before']):.3f} | {float(transition['rps_after']):.3f} | +{float(transition['rps_gain_pct']):.2f}% |",
            f"| 오류율 | {float(transition['error_rate_before']) * 100:.2f}% | {float(transition['error_rate_after']) * 100:.2f}% | - |",
            "",
            "## 원본 run",
            "",
            f"- 이전: `{before['run_ids']}`",
            f"- 이후: `{after['run_ids']}`",
            "",
            "## 공통 근거",
            "",
            "- [전체 단계 비교](../README.md)",
            "- [전환 수치 CSV](../data/stage-transition-deltas.csv)",
            "- [원본 run 출처](../data/run-sources.csv)",
            "",
        ]
        (transition_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_local_transition_readmes(
    output_root: Path,
    transitions: list[dict[str, Any]],
) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    index_lines = [
        "# 추천 성능 단계 전환",
        "",
        "로컬 stage 분석에서 이전·이후 비교 근거를 찾기 위한 인덱스다.",
        "",
    ]
    for transition in transitions:
        stage_id = str(transition["after_stage"])
        transition_dir = output_root / stage_id
        transition_dir.mkdir(parents=True, exist_ok=True)
        final_doc = (
            "../../../docs/performance/results/recommendation/"
            f"transitions/{stage_id}/README.md"
        )
        lines = [
            f"# {transition['optimization']} 단계 전환",
            "",
            f"- p95: {format_ms(transition['e2e_p95_before_ms'])} -> {format_ms(transition['e2e_p95_after_ms'])}",
            f"- 감소: {format_ms(transition['e2e_p95_reduction_ms'])} ({float(transition['e2e_p95_reduction_pct']):.2f}%)",
            f"- RPS: {float(transition['rps_before']):.3f} -> {float(transition['rps_after']):.3f}",
            f"- [공식 전환 리포트]({final_doc})",
            "",
        ]
        (transition_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
        index_lines.append(f"- [{transition['optimization']}](./{stage_id}/README.md)")
    index_lines.append("")
    (output_root / "README.md").write_text("\n".join(index_lines), encoding="utf-8")


def build_component_metrics(
    stage_rows: dict[str, list[dict[str, Any]]],
    components: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stage_id in STAGE_IDS:
        rows = stage_rows[stage_id]
        for metric, label in components:
            avg_key = f"{metric}_avg"
            p95_key = f"{metric}_p95"
            avg_values = numeric_values(rows, avg_key)
            p95_values = numeric_values(rows, p95_key)
            if not avg_values and not p95_values:
                continue
            result.append(
                {
                    "stage_id": stage_id,
                    "stage_order": STAGE_IDS.index(stage_id),
                    "component": metric,
                    "component_label": label,
                    "avg_ms": statistics.median(avg_values) if avg_values else None,
                    "avg_run_count": len(avg_values),
                    "p95_ms": statistics.median(p95_values) if p95_values else None,
                    "p95_run_count": len(p95_values),
                }
            )
    return result


def build_component_deltas(
    component_rows: list[dict[str, Any]],
    components: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    lookup = {(row["stage_id"], row["component"]): row for row in component_rows}
    result: list[dict[str, Any]] = []
    for before_id, after_id, label in TRANSITIONS:
        for metric, component_label in components:
            before = lookup.get((before_id, metric))
            after = lookup.get((after_id, metric))
            if not before or not after:
                continue
            result.append(
                {
                    "optimization": label,
                    "before_stage": before_id,
                    "after_stage": after_id,
                    "component": metric,
                    "component_label": component_label,
                    "avg_before_ms": before["avg_ms"],
                    "avg_after_ms": after["avg_ms"],
                    "avg_reduction_ms": value_delta(before["avg_ms"], after["avg_ms"]),
                    "avg_reduction_pct": percent_reduction(before["avg_ms"], after["avg_ms"]),
                    "p95_before_ms": before["p95_ms"],
                    "p95_after_ms": after["p95_ms"],
                    "p95_reduction_ms": value_delta(before["p95_ms"], after["p95_ms"]),
                    "p95_reduction_pct": percent_reduction(before["p95_ms"], after["p95_ms"]),
                }
            )
    return result


def build_run_sources(stage_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    keys = (
        "run_id",
        "run_dir",
        "measurement_schema",
        "latency_avg_ms",
        "latency_p95_ms",
        "recommendation_rps",
        "error_rate",
        "pipeline_event_count",
        "manifest_sha256",
        "k6_summary_sha256",
        "backend_log_sha256",
    )
    return [
        {"stage_id": stage_id, **{key: row.get(key) for key in keys}}
        for stage_id in STAGE_IDS
        for row in stage_rows[stage_id]
    ]


def load_plotting() -> Any:
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError as exc:
        raise SystemExit(
            "Missing analysis dependency. Install with: "
            "python -m pip install -r scripts/perf/requirements-analysis.txt"
        ) from exc
    sns.set_theme(style="whitegrid", context="notebook")
    return plt


def configure_plotting(plt: Any) -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 180,
            "font.size": 10,
            "axes.titleweight": "bold",
            "axes.edgecolor": "#D1D5DB",
            "grid.color": "#E5E7EB",
            "grid.linewidth": 0.8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def plot_total_latency(plt: Any, path: Path, summaries: list[dict[str, Any]]) -> None:
    labels = [short_stage(row["stage_id"]) for row in summaries]
    x = list(range(len(labels)))
    fig, (latency_ax, rps_ax) = plt.subplots(
        2,
        1,
        figsize=(10, 7.4),
        sharex=True,
        gridspec_kw={"height_ratios": [2.1, 1]},
        constrained_layout=True,
    )
    for metric, label, marker in (
        ("latency_p95_ms", "End-to-end p95", "o"),
        ("latency_avg_ms", "End-to-end average", "s"),
    ):
        values = [float(row[metric]) / 1000 for row in summaries]
        latency_ax.plot(x, values, marker=marker, linewidth=2.4, label=label)
        for index, value in enumerate(values):
            latency_ax.annotate(f"{value:.2f}s", (index, value), xytext=(0, 8), textcoords="offset points", ha="center")
    latency_ax.set_title("Recommendation latency falls across optimization stages")
    latency_ax.set_ylabel("Seconds")
    latency_ax.legend(frameon=False)

    rps = [float(row["recommendation_rps"]) for row in summaries]
    rps_ax.plot(x, rps, marker="o", linewidth=2.4, color="#0F766E")
    for index, value in enumerate(rps):
        rps_ax.annotate(f"{value:.2f} req/s", (index, value), xytext=(0, 8), textcoords="offset points", ha="center")
    rps_ax.set_ylabel("Throughput")
    rps_ax.set_xticks(x, labels)
    save_figure(plt, fig, path)


def plot_p95_waterfall(
    plt: Any,
    path: Path,
    summaries: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
) -> None:
    baseline = float(summaries[0]["latency_p95_ms"]) / 1000
    final = float(summaries[-1]["latency_p95_ms"]) / 1000
    reductions = [float(row["e2e_p95_reduction_ms"]) / 1000 for row in transitions]
    levels = [float(row["latency_p95_ms"]) / 1000 for row in summaries]
    labels = ["Baseline", "Opt1 reduction", "Opt2 reduction", "Opt3 reduction", "Opt3 total"]
    fig, ax = plt.subplots(figsize=(10, 5.8), constrained_layout=True)
    ax.bar(0, baseline, color=STAGE_COLORS["baseline-v1"], width=0.68)
    for index, reduction in enumerate(reductions, start=1):
        bottom = levels[index]
        ax.bar(index, reduction, bottom=bottom, color=STAGE_COLORS[STAGE_IDS[index]], width=0.68)
        pct = transitions[index - 1]["e2e_p95_reduction_pct"]
        label = f"-{reduction:.3f}s\n(-{pct:.1f}%)"
        if reduction < 2:
            ax.annotate(
                label,
                xy=(index, bottom + reduction / 2),
                xytext=(index, bottom + 4),
                ha="center",
                va="bottom",
                color="#111827",
                fontweight="bold",
                arrowprops={"arrowstyle": "->", "color": "#6B7280"},
            )
        else:
            ax.text(
                index,
                bottom + reduction / 2,
                label,
                ha="center",
                va="center",
                color="white",
                fontweight="bold",
            )
        ax.plot([index - 0.34, index + 0.34], [bottom, bottom], color="#6B7280", linewidth=1)
    ax.bar(4, final, color=STAGE_COLORS["opt3-bulk-prefetch"], width=0.68)
    ax.text(0, baseline + 1, f"{baseline:.2f}s", ha="center")
    ax.text(4, final + 1, f"{final:.2f}s", ha="center")
    ax.set_xticks(range(5), labels)
    ax.set_ylabel("End-to-end p95 (seconds)")
    ax.set_title(f"Stepwise p95 reduction: {baseline:.2f}s to {final:.2f}s")
    save_figure(plt, fig, path)


def plot_pipeline_stacked(
    plt: Any,
    path: Path,
    component_rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> None:
    lookup = {(row["stage_id"], row["component"]): row for row in component_rows}
    fig, ax = plt.subplots(figsize=(12, 6.5), constrained_layout=True)
    y = list(range(len(STAGE_IDS)))
    left = [0.0] * len(STAGE_IDS)
    for group_label, components in PIPELINE_GROUPS:
        values = [
            sum(float(lookup[(stage_id, component)]["avg_ms"]) for component in components if (stage_id, component) in lookup) / 1000
            for stage_id in STAGE_IDS
        ]
        ax.barh(y, values, left=left, label=group_label, color=GROUP_COLORS[group_label], height=0.62)
        left = [base + value for base, value in zip(left, values)]
    backend_avg = {row["stage_id"]: float(row["duration_ms_avg"]) / 1000 for row in summaries}
    for index, stage_id in enumerate(STAGE_IDS):
        ax.text(left[index] + 0.3, index, f"measured {left[index]:.2f}s / backend {backend_avg[stage_id]:.2f}s", va="center")
    ax.set_yticks(y, [short_stage(stage_id) for stage_id in STAGE_IDS])
    ax.invert_yaxis()
    ax.set_xlabel("Median component average (seconds)")
    ax.set_title("Average pipeline composition shows where time disappeared")
    ax.legend(ncol=3, frameon=False, loc="lower right")
    save_figure(plt, fig, path)


def plot_transition_components(plt: Any, path: Path, deltas: list[dict[str, Any]]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.2), constrained_layout=True)
    for ax, (_, _, label) in zip(axes, TRANSITIONS):
        rows = [row for row in deltas if row["optimization"] == label]
        rows = sorted(rows, key=lambda row: abs(float(row["avg_reduction_ms"])), reverse=True)[:7]
        rows = list(reversed(rows))
        values = [float(row["avg_reduction_ms"]) / 1000 for row in rows]
        colors = ["#2563EB" if value >= 0 else "#DC2626" for value in values]
        ax.barh(range(len(rows)), values, color=colors)
        ax.axvline(0, color="#6B7280", linewidth=1)
        ax.set_yticks(range(len(rows)), [row["component_label"] for row in rows])
        ax.set_title(f"{label}: average-stage change")
        ax.set_xlabel("Seconds reduced (+) / regressed (-)")
        span = max((abs(value) for value in values), default=1.0)
        ax.set_xlim(min(min(values, default=0) * 2.8, -span * 0.08), max(values, default=0) * 1.18)
        for index, value in enumerate(values):
            ax.text(value, index, f" {value:+.3f}s", va="center", ha="left" if value >= 0 else "right")
    save_figure(plt, fig, path)


def plot_pipeline_heatmap(plt: Any, path: Path, rows: list[dict[str, Any]]) -> None:
    import numpy as np
    import seaborn as sns

    lookup = {(row["stage_id"], row["component"]): row for row in rows}
    matrix = np.array(
        [
            [float(lookup[(stage_id, metric)]["p95_ms"]) / 1000 for stage_id in STAGE_IDS]
            for metric, _ in PIPELINE_COMPONENTS
        ]
    )
    fig, ax = plt.subplots(figsize=(10, 8.2), constrained_layout=True)
    sns.heatmap(
        matrix,
        annot=True,
        fmt=".2f",
        cmap="YlOrRd",
        xticklabels=[short_stage(stage_id) for stage_id in STAGE_IDS],
        yticklabels=[label for _, label in PIPELINE_COMPONENTS],
        cbar_kws={"label": "Independent component p95 (seconds)"},
        ax=ax,
    )
    ax.set_title("Pipeline p95 by stage (component p95 values are not additive)")
    save_figure(plt, fig, path)


def plot_scoring_drilldown(plt: Any, path: Path, rows: list[dict[str, Any]]) -> None:
    lookup = {(row["stage_id"], row["component"]): row for row in rows}
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), constrained_layout=True)
    for ax, suffix, title in ((axes[0], "avg_ms", "Average"), (axes[1], "p95_ms", "p95")):
        for metric, label in SCORING_COMPONENTS:
            points = [lookup.get((stage_id, metric)) for stage_id in STAGE_IDS]
            x = [index for index, point in enumerate(points) if point and point.get(suffix) is not None]
            values = [float(points[index][suffix]) / 1000 for index in x]
            if values:
                ax.plot(x, values, marker="o", linewidth=2, label=label)
        ax.set_xticks(range(len(STAGE_IDS)), [short_stage(stage_id) for stage_id in STAGE_IDS], rotation=15)
        ax.set_ylabel("Seconds")
        ax.set_title(f"Scoring breakdown: {title}")
    axes[1].legend(frameon=False, fontsize=8)
    save_figure(plt, fig, path)


def plot_total_component_reduction(plt: Any, path: Path, deltas: list[dict[str, Any]]) -> None:
    cumulative: list[dict[str, Any]] = []
    for _, label in PIPELINE_COMPONENTS:
        related = [row for row in deltas if row["component_label"] == label]
        if related:
            cumulative.append(
                {
                    "label": label,
                    "value": sum(float(row["avg_reduction_ms"]) for row in related) / 1000,
                }
            )
    cumulative.sort(key=lambda row: row["value"])
    fig, ax = plt.subplots(figsize=(10, 6.8), constrained_layout=True)
    values = [row["value"] for row in cumulative]
    colors = ["#2563EB" if value >= 0 else "#DC2626" for value in values]
    ax.barh(range(len(cumulative)), values, color=colors)
    ax.axvline(0, color="#6B7280", linewidth=1)
    ax.set_yticks(range(len(cumulative)), [row["label"] for row in cumulative])
    ax.set_xlabel("Baseline minus Opt3 median average (seconds)")
    ax.set_title("Baseline to Opt3: component-level average time reduction")
    for index, value in enumerate(values):
        ax.text(value, index, f" {value:+.3f}s", va="center", ha="left" if value >= 0 else "right")
    save_figure(plt, fig, path)


def write_readme(
    path: Path,
    summaries: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    pipeline_metrics: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    scoring_metrics: list[dict[str, Any]],
) -> None:
    baseline = summaries[0]
    latest = summaries[-1]
    total_reduction = float(baseline["latency_p95_ms"]) - float(latest["latency_p95_ms"])
    lines = [
        "# 추천 성능 단계별 비교",
        "",
        "8만 상품, VUS 10, 3분, full-personalized, cold cache 조건에서 Baseline부터 Opt3까지 비교한다.",
        "단계 수치는 각 단계의 유효 run 중앙값이며, 원본 run과 해시는 `data/run-sources.csv`에서 확인할 수 있다.",
        "",
        "## 결론",
        "",
        f"- End-to-end p95: **{format_ms(baseline['latency_p95_ms'])} -> {format_ms(latest['latency_p95_ms'])}**",
        f"- 총 감소: **{format_ms(total_reduction)} "
        f"({percent_reduction(baseline['latency_p95_ms'], latest['latency_p95_ms']):.2f}%)**",
        f"- 처리량: **{float(baseline['recommendation_rps']):.3f} -> {float(latest['recommendation_rps']):.3f} req/s**",
        "",
        "![총 응답시간 추세](charts/01-total-latency-trend.png)",
        "",
        "![단계별 p95 감소](charts/02-stepwise-p95-waterfall.png)",
        "",
        "## 단계별 정확한 수치",
        "",
        "| 단계 | run 수 | E2E 평균 | E2E p95 | Backend p95 | RPS | 오류율 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {short_stage(row['stage_id'])} | {row['run_count']} | {format_ms(row['latency_avg_ms'])} | "
            f"{format_ms(row['latency_p95_ms'])} | {format_ms(row['duration_ms_p95'])} | "
            f"{float(row['recommendation_rps']):.3f} | {float(row['error_rate']) * 100:.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 최적화 단계별 감소량",
            "",
            "| 적용 단계 | E2E p95 이전 | E2E p95 이후 | 감소량 | 감소율 | 평균 감소 | RPS 증가율 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in transitions:
        lines.append(
            f"| {row['optimization']} | {format_ms(row['e2e_p95_before_ms'])} | {format_ms(row['e2e_p95_after_ms'])} | "
            f"{format_ms(row['e2e_p95_reduction_ms'])} | {float(row['e2e_p95_reduction_pct']):.2f}% | "
            f"{format_ms(row['e2e_avg_reduction_ms'])} | {float(row['rps_gain_pct']):.2f}% |"
        )
    lines.extend(
        [
            "",
            "## 파이프라인 요소별 평균 시간",
            "",
            "양수 감소량은 빨라진 시간이고, 음수는 해당 단계에서 늘어난 시간이다.",
            "",
            "| 구성요소 | Baseline | Opt1 | Opt2 | Opt3 | Opt1 감소 | Opt2 감소 | Opt3 감소 | 총 감소 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            *build_pipeline_markdown_rows(pipeline_metrics, deltas),
            "",
            "## 스코어링 내부 평균 시간",
            "",
            "| 구성요소 | Baseline | Opt1 | Opt2 | Opt3 | 총 감소 |",
            "|---|---:|---:|---:|---:|---:|",
            *build_scoring_markdown_rows(scoring_metrics),
        ]
    )
    lines.extend(["", "## 각 단계에서 실제로 줄어든 병목", ""])
    for _, _, label in TRANSITIONS:
        related = [row for row in deltas if row["optimization"] == label]
        related.sort(key=lambda row: float(row["avg_reduction_ms"]), reverse=True)
        top = [row for row in related if float(row["avg_reduction_ms"]) > 0][:3]
        regressions = [
            row
            for row in sorted(related, key=lambda row: float(row["avg_reduction_ms"]))
            if float(row["avg_reduction_ms"]) < 0
        ][:2]
        lines.append(f"### {label}")
        lines.append("")
        for row in top:
            lines.append(
                f"- {row['component_label']}: 평균 **{format_ms(row['avg_reduction_ms'])} 감소**, "
                f"개별 p95 **{format_ms(row['p95_reduction_ms'])} 감소**"
            )
        for row in regressions:
            if float(row["avg_reduction_ms"]) < 0:
                lines.append(
                    f"- 회귀: {row['component_label']} 평균 **{format_ms(-float(row['avg_reduction_ms']))} 증가**"
                )
        lines.append("")
    lines.extend(
        [
            "![파이프라인 평균 구성](charts/03-pipeline-average-evolution.png)",
            "",
            "![단계별 구성요소 감소](charts/04-component-reduction-by-transition.png)",
            "",
            "![파이프라인 p95](charts/05-pipeline-p95-heatmap.png)",
            "",
            "![스코어링 세부 변화](charts/06-scoring-breakdown-trend.png)",
            "",
            "![Baseline 대비 Opt3 구성요소 감소](charts/07-baseline-to-opt3-component-reduction.png)",
            "",
            "## 해석 주의사항",
            "",
            "- E2E p95는 k6 요청 분포의 단계별 중앙값이다.",
            "- 구성요소 평균은 같은 단계의 backend 계측 평균 중앙값이다. 평균 구성요소 감소량을 E2E p95 감소량과 직접 합산하지 않는다.",
            "- 구성요소 p95는 각각 독립적으로 계산되므로 서로 더하면 전체 p95가 되지 않는다.",
            "- Baseline은 유효 run이 1건이고 오류율이 2%여서 개선 전 문제 증거로만 사용한다.",
            "- Opt1은 3건, Opt2는 3건, Opt3는 2건의 유효 run 중앙값이다.",
            "- manifest의 git SHA가 `unknown`이므로 구현 단계는 registry의 명시적 run 연결로 증명한다.",
            "",
            "## 원본 데이터",
            "",
            "- `data/stage-summary.csv`",
            "- `data/stage-transition-deltas.csv`",
            "- `data/pipeline-component-metrics.csv`",
            "- `data/pipeline-component-deltas.csv`",
            "- `data/scoring-component-metrics.csv`",
            "- `data/run-sources.csv`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_pipeline_markdown_rows(
    metrics: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> list[str]:
    metric_lookup = {
        (row["stage_id"], row["component"]): row
        for row in metrics
    }
    delta_lookup = {
        (row["optimization"], row["component"]): row
        for row in deltas
    }
    rows: list[str] = []
    for component, label in PIPELINE_COMPONENTS:
        values = [
            metric_lookup[(stage_id, component)]["avg_ms"]
            for stage_id in STAGE_IDS
        ]
        reductions = [
            delta_lookup[(optimization, component)]["avg_reduction_ms"]
            for optimization in ("Opt1", "Opt2", "Opt3")
        ]
        total_reduction = float(values[0]) - float(values[-1])
        rows.append(
            f"| {label} | {format_table_ms(values[0])} | {format_table_ms(values[1])} | "
            f"{format_table_ms(values[2])} | {format_table_ms(values[3])} | "
            f"{format_signed_ms(reductions[0])} | {format_signed_ms(reductions[1])} | "
            f"{format_signed_ms(reductions[2])} | {format_signed_ms(total_reduction)} |"
        )
    return rows


def build_scoring_markdown_rows(metrics: list[dict[str, Any]]) -> list[str]:
    lookup = {
        (row["stage_id"], row["component"]): row
        for row in metrics
    }
    rows: list[str] = []
    for component, label in SCORING_COMPONENTS:
        values = [
            lookup.get((stage_id, component), {}).get("avg_ms")
            for stage_id in STAGE_IDS
        ]
        available = [value for value in values if value is not None]
        if not available:
            continue
        total_reduction = (
            None
            if values[0] is None or values[-1] is None
            else float(values[0]) - float(values[-1])
        )
        rows.append(
            f"| {label} | "
            + " | ".join(format_table_ms(value) for value in values)
            + f" | {format_signed_ms(total_reduction)} |"
        )
    return rows


def median_metric(rows: Iterable[dict[str, Any]], metric: str) -> float:
    values = numeric_values(rows, metric)
    if not values:
        raise ValueError(f"Missing metric: {metric}")
    return statistics.median(values)


def numeric_values(rows: Iterable[dict[str, Any]], metric: str) -> list[float]:
    result: list[float] = []
    for row in rows:
        value = report_data.numeric_or_none(row.get(metric))
        if value is not None and math.isfinite(float(value)):
            result.append(float(value))
    return result


def value_delta(before: Any, after: Any) -> float | None:
    if before is None or after is None:
        return None
    return float(before) - float(after)


def percent_reduction(before: Any, after: Any) -> float | None:
    if before is None or after is None or float(before) == 0:
        return None
    return (float(before) - float(after)) / float(before) * 100


def percent_gain(before: Any, after: Any) -> float | None:
    if before is None or after is None or float(before) == 0:
        return None
    return (float(after) - float(before)) / float(before) * 100


def short_stage(stage_id: str) -> str:
    return {
        "baseline-v1": "Baseline",
        "opt1-es-retrieval": "Opt1 ES retrieval",
        "opt2-precomputed-features": "Opt2 Precompute",
        "opt3-bulk-prefetch": "Opt3 Bulk prefetch",
    }[stage_id]


def format_ms(value: Any) -> str:
    numeric = float(value)
    return f"{numeric:,.2f} ms ({numeric / 1000:.3f}초)"


def format_table_ms(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):,.2f} ms"


def format_signed_ms(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+,.2f} ms"


def save_figure(plt: Any, fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
