"""Compare two benchmark analysis summaries and create before/after graphs."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


STAGE_GROUPS = {
    "pipeline": [
        ("user_context_load_ms_p95", "user context"),
        ("skin_test_context_load_ms_p95", "skin test"),
        ("behavior_context_load_ms_p95", "behavior context"),
        ("intent_parse_ms_p95", "intent parse"),
        ("candidate_pool_ms_p95", "candidate pool"),
        ("scoring_ms_p95", "scoring"),
        ("result_save_ms_p95", "result save"),
        ("response_load_ms_p95", "response load"),
    ],
    "scoring": [
        ("scoring_data_prefetch_ms_p95", "data prefetch"),
        ("score_context_build_ms_p95", "context build"),
        ("score_loop_ms_p95", "score loop"),
        ("score_sort_ms_p95", "sort"),
    ],
    "prefetch": [
        ("prefetch_behavior_signals_ms_p95", "behavior signals"),
        ("prefetch_ingredient_effects_ms_p95", "ingredient effects"),
        ("prefetch_functional_info_ms_p95", "functional info"),
        ("prefetch_skin_profiles_ms_p95", "skin profiles"),
        ("prefetch_review_metrics_ms_p95", "review metrics"),
        ("prefetch_review_segments_ms_p95", "review segments"),
        ("prefetch_market_signals_ms_p95", "market signals"),
        ("prefetch_risk_flags_ms_p95", "risk flags"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two recommendation benchmark summary.csv files."
    )
    parser.add_argument("--baseline", required=True, help="Baseline summary.csv path.")
    parser.add_argument("--optimized", required=True, help="Optimized summary.csv path.")
    parser.add_argument("--output", required=True, help="Output directory for graphs.")
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--optimized-label", default="optimized")
    parser.add_argument("--stage-dataset", type=int, default=80000)
    parser.add_argument("--stage-vus", type=int, default=10)
    return parser.parse_args()


def prepare_frame(path: Path, stage: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["stage"] = stage
    for column in ("dataset", "vus"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    return frame


def save_line_compare(agg: pd.DataFrame, output: Path) -> None:
    plot_df = agg[["stage", "dataset", "vus", "latency_p95_ms"]].dropna()
    graph = sns.relplot(
        data=plot_df,
        x="vus",
        y="latency_p95_ms",
        hue="stage",
        col="dataset",
        kind="line",
        marker="o",
        col_wrap=2,
        facet_kws={"sharey": False},
        height=4,
        aspect=1.4,
    )
    graph.set_axis_labels("VUS", "p95 latency (ms)")
    graph.set_titles("dataset={col_name}")
    graph.fig.suptitle("p95 latency by dataset and VUS", y=1.03)
    graph.savefig(output / "compare_latency_p95_by_dataset_vus.png", dpi=180, bbox_inches="tight")
    plt.close(graph.fig)


def save_improvement_heatmap(wide: pd.DataFrame, output: Path, optimized_label: str) -> None:
    heat = wide.pivot(index="dataset", columns="vus", values="improvement_pct").sort_index()
    plt.figure(figsize=(9, 5))
    sns.heatmap(
        heat,
        annot=True,
        fmt=".1f",
        cmap="RdYlGn",
        center=0,
        cbar_kws={"label": "p95 improvement (%)"},
    )
    plt.title(f"p95 latency improvement: baseline -> {optimized_label}")
    plt.xlabel("VUS")
    plt.ylabel("Dataset size")
    plt.tight_layout()
    plt.savefig(output / "compare_latency_p95_improvement_heatmap.png", dpi=180)
    plt.close()


def save_target_bar(agg: pd.DataFrame, output: Path, dataset: int, vus: int) -> None:
    key = agg[(agg["dataset"] == dataset) & (agg["vus"] == vus)]
    if key.empty:
        return
    plt.figure(figsize=(7, 4.5))
    sns.barplot(
        data=key,
        x="stage",
        y="latency_p95_ms",
        hue="stage",
        legend=False,
        palette=["#8B95A1", "#3182F6"],
    )
    for index, row in enumerate(key.itertuples()):
        plt.text(index, row.latency_p95_ms, f"{row.latency_p95_ms:,.0f} ms", ha="center", va="bottom")
    plt.title(f"{dataset} products / VUS{vus} p95 latency")
    plt.xlabel("")
    plt.ylabel("p95 latency (ms)")
    plt.tight_layout()
    plt.savefig(output / f"compare_{dataset}_vus{vus}_p95_before_after.png", dpi=180)
    plt.close()


def save_rps_compare(agg: pd.DataFrame, output: Path) -> None:
    if "recommendation_rps" not in agg.columns:
        return
    plot_df = agg[["stage", "dataset", "vus", "recommendation_rps"]].dropna()
    graph = sns.relplot(
        data=plot_df,
        x="vus",
        y="recommendation_rps",
        hue="stage",
        col="dataset",
        kind="line",
        marker="o",
        col_wrap=2,
        facet_kws={"sharey": False},
        height=4,
        aspect=1.4,
    )
    graph.set_axis_labels("VUS", "recommendation RPS")
    graph.set_titles("dataset={col_name}")
    graph.fig.suptitle("Recommendation throughput by dataset and VUS", y=1.03)
    graph.savefig(output / "compare_recommendation_rps_by_dataset_vus.png", dpi=180, bbox_inches="tight")
    plt.close(graph.fig)


def mean_row(frame: pd.DataFrame, dataset: int, vus: int) -> pd.Series | None:
    rows = frame[(frame["dataset"] == dataset) & (frame["vus"] == vus)]
    if rows.empty:
        return None
    return rows.select_dtypes(include=[np.number]).mean(numeric_only=True)


def save_stage_comparison(
    baseline: pd.DataFrame,
    optimized: pd.DataFrame,
    output: Path,
    dataset: int,
    vus: int,
    baseline_label: str,
    optimized_label: str,
) -> None:
    baseline_row = mean_row(baseline, dataset, vus)
    optimized_row = mean_row(optimized, dataset, vus)
    if baseline_row is None or optimized_row is None:
        return

    for group_name, fields in STAGE_GROUPS.items():
        records: list[dict[str, str | float]] = []
        for key, label in fields:
            if key in baseline_row.index:
                records.append(
                    {"component": label, "stage": baseline_label, "p95_ms": float(baseline_row.get(key, 0) or 0)}
                )
            if key in optimized_row.index:
                records.append(
                    {"component": label, "stage": optimized_label, "p95_ms": float(optimized_row.get(key, 0) or 0)}
                )
        comp = pd.DataFrame(records)
        if comp.empty:
            continue

        order = comp.groupby("component")["p95_ms"].max().sort_values(ascending=False).index.tolist()
        plt.figure(figsize=(11, max(4.5, 0.45 * len(order))))
        sns.barplot(
            data=comp,
            y="component",
            x="p95_ms",
            hue="stage",
            order=order,
            palette=["#8B95A1", "#3182F6"],
        )
        plt.title(f"{dataset}/VUS{vus} {group_name} p95 breakdown")
        plt.xlabel("p95 ms")
        plt.ylabel("")
        plt.tight_layout()
        plt.savefig(output / f"compare_{dataset}_vus{vus}_{group_name}_breakdown.png", dpi=180)
        plt.close()

        pivot = comp.pivot_table(index="component", columns="stage", values="p95_ms", aggfunc="mean").fillna(0)
        if baseline_label not in pivot.columns or optimized_label not in pivot.columns:
            continue
        pivot["delta_ms"] = pivot[optimized_label] - pivot[baseline_label]
        pivot["improvement_pct"] = np.where(
            pivot[baseline_label] > 0,
            (pivot[baseline_label] - pivot[optimized_label]) / pivot[baseline_label] * 100,
            np.nan,
        )
        pivot.reset_index().to_csv(
            output / f"compare_{dataset}_vus{vus}_{group_name}_delta.csv",
            index=False,
            encoding="utf-8-sig",
        )

        delta_df = pivot.reset_index().sort_values("delta_ms")
        plt.figure(figsize=(10, max(4.5, 0.45 * len(delta_df))))
        colors = ["#3182F6" if value < 0 else "#F04452" for value in delta_df["delta_ms"]]
        plt.barh(delta_df["component"], delta_df["delta_ms"], color=colors)
        plt.axvline(0, color="#222", linewidth=1)
        plt.title(f"{dataset}/VUS{vus} {group_name} delta: {optimized_label} - {baseline_label}")
        plt.xlabel("delta p95 ms (negative is faster)")
        plt.ylabel("")
        plt.tight_layout()
        plt.savefig(output / f"compare_{dataset}_vus{vus}_{group_name}_delta.png", dpi=180)
        plt.close()


def write_readme(output: Path, wide: pd.DataFrame, dataset: int, vus: int) -> None:
    lines = ["# Benchmark Comparison", ""]
    target = wide[(wide["dataset"] == dataset) & (wide["vus"] == vus)]
    if not target.empty:
        row = target.iloc[0]
        lines.extend(
            [
                f"- Target: dataset={dataset}, VUS={vus}",
                f"- Baseline p95: {row['baseline']:,.2f} ms",
                f"- Optimized p95: {row['optimized']:,.2f} ms",
                f"- Delta: {row['delta_ms']:,.2f} ms",
                f"- Improvement: {row['improvement_pct']:.2f}%",
                "",
            ]
        )
    lines.extend(
        [
            "## Main Graphs",
            "- `compare_latency_p95_by_dataset_vus.png`",
            "- `compare_latency_p95_improvement_heatmap.png`",
            f"- `compare_{dataset}_vus{vus}_p95_before_after.png`",
            f"- `compare_{dataset}_vus{vus}_pipeline_breakdown.png`",
            f"- `compare_{dataset}_vus{vus}_scoring_breakdown.png`",
            f"- `compare_{dataset}_vus{vus}_prefetch_breakdown.png`",
        ]
    )
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", font="DejaVu Sans")
    plt.rcParams["axes.unicode_minus"] = False

    baseline = prepare_frame(Path(args.baseline), "baseline")
    optimized = prepare_frame(Path(args.optimized), "optimized")
    df = pd.concat([baseline, optimized], ignore_index=True)

    metrics = [
        "latency_p95_ms",
        "latency_avg_ms",
        "rps",
        "recommendation_rps",
        "intent_parse_ms_p95",
        "candidate_pool_ms_p95",
        "scoring_ms_p95",
        "scoring_data_prefetch_ms_p95",
        "score_loop_ms_p95",
        "prefetch_behavior_signals_ms_p95",
        "prefetch_ingredient_effects_ms_p95",
    ]
    available_metrics = [metric for metric in metrics if metric in df.columns]
    agg = df.groupby(["stage", "dataset", "vus"], dropna=False)[available_metrics].mean().reset_index()
    agg.to_csv(output / "compare_summary_by_dataset_vus.csv", index=False, encoding="utf-8-sig")

    wide = agg.pivot_table(index=["dataset", "vus"], columns="stage", values="latency_p95_ms").reset_index()
    if {"baseline", "optimized"}.issubset(wide.columns):
        wide["delta_ms"] = wide["optimized"] - wide["baseline"]
        wide["improvement_pct"] = (wide["baseline"] - wide["optimized"]) / wide["baseline"] * 100
        wide.to_csv(output / "latency_p95_improvement.csv", index=False, encoding="utf-8-sig")
        save_line_compare(agg, output)
        save_improvement_heatmap(wide, output, args.optimized_label)
        save_target_bar(agg, output, args.stage_dataset, args.stage_vus)
        write_readme(output, wide, args.stage_dataset, args.stage_vus)

    save_rps_compare(agg, output)
    save_stage_comparison(
        baseline,
        optimized,
        output,
        args.stage_dataset,
        args.stage_vus,
        args.baseline_label,
        args.optimized_label,
    )

    print(f"comparison_output={output.resolve()}")
    for path in sorted(output.iterdir()):
        print(path.name)


if __name__ == "__main__":
    main()
