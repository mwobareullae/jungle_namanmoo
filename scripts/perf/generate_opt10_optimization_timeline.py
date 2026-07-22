"""Render the 80k/VUS10 recommendation optimization trend through Opt10.

This is intentionally separate from the curated report generator.  That report
registry currently ends at Opt4c, while this script records the measured runs
used for the Opt10 checkpoint without overwriting the older documentation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import FancyBboxPatch, Patch


@dataclass(frozen=True)
class Stage:
    stage_id: str
    label: str
    run_ids: tuple[str, ...]
    cache_mode: str
    note: str
    outcome: str = "improved"


STAGES = (
    Stage("baseline-v1", "Baseline", ("recommendation-80000-full-personalized-20260714-053424",), "off", "Initial pipeline"),
    Stage("opt1-es-retrieval", "Opt1", (
        "recommendation-80000-full-personalized-20260714-225808",
        "recommendation-80000-full-personalized-20260715-001631",
        "recommendation-80000-full-personalized-20260715-004324",
    ), "off", "ES-centered retrieval"),
    Stage("opt2-precomputed-features", "Opt2", (
        "recommendation-80000-full-personalized-20260715-053752",
        "recommendation-80000-full-personalized-20260715-054137",
        "recommendation-80000-full-personalized-20260715-054517",
    ), "off", "Precomputed features"),
    Stage("opt3-bulk-prefetch", "Opt3", (
        "recommendation-80000-full-personalized-20260715-092247",
        "recommendation-80000-full-personalized-20260715-092634",
        "recommendation-80000-full-personalized-20260715-093021",
    ), "off", "Bulk prefetch"),
    Stage("opt4a-snapshot", "Opt4a", (
        "recommendation-80000-full-personalized-20260716-205631",
        "recommendation-80000-full-personalized-20260716-210023",
        "recommendation-80000-full-personalized-20260716-210410",
    ), "off", "Snapshot read-model attempt (reverted)", "reverted"),
    Stage("opt4b-compact-read-model", "Opt4b", (
        "recommendation-80000-full-personalized-20260716-233731",
        "recommendation-80000-full-personalized-20260716-234122",
        "recommendation-80000-full-personalized-20260716-234511",
    ), "off", "Compact read model (reverted)", "reverted"),
    Stage("opt4c-coarse-top50", "Opt4c", (
        "recommendation-80000-full-personalized-20260717-043340",
        "recommendation-80000-full-personalized-20260717-043735",
        "recommendation-80000-full-personalized-20260717-044128",
    ), "off", "Coarse top-50"),
    Stage("opt5-selected-detail-ingredients", "Opt5", (
        "recommendation-80000-full-personalized-20260717-082847",
        "recommendation-80000-full-personalized-20260717-083237",
        "recommendation-80000-full-personalized-20260717-083628",
    ), "off", "Selected detail ingredients"),
    Stage("opt6-candidate-pool-v2", "Opt6", (
        "recommendation-80000-full-personalized-20260717-201826",
        "recommendation-80000-full-personalized-20260717-202600",
        "recommendation-80000-full-personalized-20260717-202212",
    ), "off", "Candidate pool v2"),
    Stage("opt7-remove-candidate-trace", "Opt7", (
        "recommendation-80000-full-personalized-20260718-025108",
        "recommendation-80000-full-personalized-20260718-025452",
        "recommendation-80000-full-personalized-20260718-030355",
    ), "off", "Remove candidate trace writes"),
    Stage("opt8-bulk-result-insert", "Opt8", (
        "recommendation-80000-full-personalized-20260718-051421",
        "recommendation-80000-full-personalized-20260718-051804",
        "recommendation-80000-full-personalized-20260718-052147",
    ), "off", "Bulk result insert", "regression"),
    Stage("opt8b-raw-sql-persist", "Opt8b", (
        "recommendation-80000-full-personalized-20260718-063647",
        "recommendation-80000-full-personalized-20260718-064033",
        "recommendation-80000-full-personalized-20260718-064419",
    ), "off", "Core SQL persistence"),
    Stage("opt9-response-load", "Opt9", (
        "recommendation-80000-full-personalized-20260719-034636",
        "recommendation-80000-full-personalized-20260719-035022",
        "recommendation-80000-full-personalized-20260719-035407",
    ), "off", "Response projection"),
    Stage("opt10-candidate-cache", "Opt10", (
        "recommendation-80000-full-personalized-20260719-092324",
        "recommendation-80000-full-personalized-20260719-092748",
        "recommendation-80000-full-personalized-20260719-093211",
    ), "warm", "Redis candidate cache (warm)"),
    Stage("opt11-worker-scaleout", "Opt11", (
        "recommendation-80000-full-personalized-w2-20260719-220833",
    ), "warm", "Uvicorn worker scale-out (best comparable 3-minute run)"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("perf-runs/stages/opt10-candidate-cache/analysis/01-optimization-timeline"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    output.mkdir(parents=True, exist_ok=True)

    rows = [summarize_stage(repo_root, stage) for stage in STAGES]
    write_csv(output / "stage-summary.csv", rows)
    write_readme(output / "README.md", rows)
    plot_p95_trend(output / "01-p95-optimization-trend.png", rows)
    plot_rps_trend(output / "02-rps-optimization-trend.png", rows)
    plot_reduction(output / "03-p95-reduction-by-stage.png", rows)
    plot_p95_zoom(output / "04-p95-optimization-trend-opt1-onward.png", rows)
    worker_rows = collect_worker_rows(repo_root)
    write_csv(output / "opt11-worker-summary.csv", worker_rows)
    plot_worker_scaleout(output / "05-opt11-worker-scaleout.png", worker_rows)
    plot_poster_challenge_layout(output / "06-poster-challenge-layout.png", rows)
    plot_pipeline_optimization_map(output / "07-pipeline-optimization-map.png", rows)
    baseline_scale_rows = collect_scale_sweep_rows(repo_root, "baseline-v1")
    opt10_scale_rows = collect_scale_sweep_rows(repo_root, "opt10-candidate-cache")
    plot_scale_heatmap_comparison(
        output / "08-p95-scale-heatmap-baseline-vs-opt10.png",
        baseline_scale_rows,
        opt10_scale_rows,
    )
    plot_80k_dumbbell_comparison(
        output / "09-80k-concurrency-dumbbell-baseline-vs-opt10.png",
        baseline_scale_rows,
        opt10_scale_rows,
    )
    print(f"generated={output}")


def summarize_stage(repo_root: Path, stage: Stage) -> dict[str, object]:
    by_id: dict[str, Path] = {}
    for manifest_path in (repo_root / "perf-runs").rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        by_id[str(manifest.get("run_id") or manifest_path.parent.name)] = manifest_path.parent

    p95_values: list[float] = []
    rps_values: list[float] = []
    for run_id in stage.run_ids:
        run_dir = by_id.get(run_id)
        if run_dir is None:
            raise FileNotFoundError(f"Selected run is missing: {stage.stage_id}/{run_id}")
        summary_path = run_dir / "k6" / "k6-summary.json"
        if not summary_path.exists():
            summary_path = run_dir / "k6-summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        metrics = summary["metrics"]
        duration = metrics.get("http_req_duration{type:recommendation}") or metrics["http_req_duration"]
        p95_values.append(float(duration["p(95)"]))
        rps_values.append(float(metrics["iterations"]["rate"]))

    return {
        "stage_id": stage.stage_id,
        "stage": stage.label,
        "cache_mode": stage.cache_mode,
        "note": stage.note,
        "outcome": stage.outcome,
        "run_count": len(stage.run_ids),
        "run_ids": ";".join(stage.run_ids),
        "p95_median_ms": round(statistics.median(p95_values), 2),
        "p95_min_ms": round(min(p95_values), 2),
        "p95_max_ms": round(max(p95_values), 2),
        "rps_median": round(statistics.median(rps_values), 3),
        "rps_min": round(min(rps_values), 3),
        "rps_max": round(max(rps_values), 3),
    }


def plot_p95_trend(path: Path, rows: list[dict[str, object]]) -> None:
    """Render every checkpoint without letting the 52-second baseline flatten later work.

    The vertical gap is deliberate: it is a broken y-axis, not a missing data
    point.  Both axes draw the same dashed series so the Baseline-to-Opt1 drop
    remains visible while the later 3-13 second changes stay readable.
    """
    labels = [str(row["stage"]) for row in rows]
    values = [float(row["p95_median_ms"]) / 1000 for row in rows]
    colors = [point_color(row) for row in rows]
    positions = list(range(len(rows)))
    later_values = values[1:]
    lower_max = max(later_values) + 0.9
    upper_min = values[0] - 4.0
    upper_max = values[0] + 2.4

    fig, (top_ax, bottom_ax) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(15, 8),
        gridspec_kw={"height_ratios": [1, 3], "hspace": 0.06},
    )
    for axis in (top_ax, bottom_ax):
        # Baseline is separated by the omitted range, so do not imply a
        # continuous line between 52s and Opt1.
        axis.plot(positions[1:], values[1:], color="#94A3B8", linewidth=1.8, linestyle="--", zorder=1)
        axis.scatter(positions, values, s=90, color=colors, zorder=3)
        axis.grid(axis="y", alpha=0.25)

    top_ax.set_ylim(upper_min, upper_max)
    bottom_ax.set_ylim(0, lower_max)
    top_ax.spines["bottom"].set_visible(False)
    bottom_ax.spines["top"].set_visible(False)
    top_ax.tick_params(axis="x", bottom=False, labelbottom=False)
    bottom_ax.set_xticks(positions, labels)

    for index, value in enumerate(values):
        axis = top_ax if value >= upper_min else bottom_ax
        axis.annotate(
            f"{value:.2f}s",
            (index, value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )

    bottom_ax.set_ylabel("Recommendation HTTP p95 (seconds)")
    fig.suptitle("80k products / full-personalized / VUS 10 / 3-minute runs", y=0.98)
    bottom_ax.text(
        0.01,
        0.03,
        "Broken y-axis: 14s to 48s is omitted. Blue: retained improvement. Red: reverted/regression. Orange: warm Redis cache.",
        transform=bottom_ax.transAxes,
        fontsize=9,
        color="#374151",
    )
    fig.tight_layout()
    draw_figure_break_wave(fig, top_ax, bottom_ax)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_rps_trend(path: Path, rows: list[dict[str, object]]) -> None:
    labels = [str(row["stage"]) for row in rows]
    values = [float(row["rps_median"]) for row in rows]
    colors = [point_color(row) for row in rows]
    fig, ax = plt.subplots(figsize=(15, 6))
    bars = ax.bar(labels, values, color=colors)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.04, f"{value:.2f}", ha="center", fontsize=9)
    ax.set_ylabel("Completed recommendation requests / second")
    ax.set_title("Throughput trend for the same headline condition")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_reduction(path: Path, rows: list[dict[str, object]]) -> None:
    baseline = float(rows[0]["p95_median_ms"])
    labels = [str(row["stage"]) for row in rows]
    reductions = [(baseline - float(row["p95_median_ms"])) / 1000 for row in rows]
    colors = [point_color(row) for row in rows]
    fig, ax = plt.subplots(figsize=(15, 6))
    bars = ax.bar(labels, reductions, color=colors)
    for bar, value in zip(bars, reductions):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.25, f"-{value:.1f}s", ha="center", fontsize=9)
    ax.set_ylabel("p95 reduction vs baseline (seconds)")
    ax.set_title("Cumulative p95 reduction from the baseline")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_p95_zoom(path: Path, rows: list[dict[str, object]]) -> None:
    """Show the smaller, later improvements without the 52-second baseline."""
    zoom_rows = rows[1:]
    labels = [str(row["stage"]) for row in zoom_rows]
    values = [float(row["p95_median_ms"]) / 1000 for row in zoom_rows]
    colors = [point_color(row) for row in zoom_rows]
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(range(len(zoom_rows)), values, color="#94A3B8", linewidth=1.8, linestyle="--", zorder=1)
    ax.scatter(range(len(zoom_rows)), values, s=90, color=colors, zorder=3)
    for index, value in enumerate(values):
        ax.annotate(f"{value:.2f}s", (index, value), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=9)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_ylim(min(values) - 0.45, max(values) + 0.8)
    ax.set_ylabel("Recommendation HTTP p95 (seconds)")
    ax.set_title("Optimization trend after Opt1 (zoomed)")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def point_color(row: dict[str, object]) -> str:
    if row["outcome"] in {"reverted", "regression"}:
        return "#DC2626"
    if row["cache_mode"] == "warm":
        return "#D97706"
    return "#2563EB"


def draw_figure_break_wave(fig, top_ax, bottom_ax) -> None:
    """Draw a paired continuous wave across the omitted y-axis range."""
    top_box = top_ax.get_position()
    bottom_box = bottom_ax.get_position()
    x_values = [top_box.x0 + (top_box.x1 - top_box.x0) * index / 480 for index in range(481)]
    center_y = (bottom_box.y1 + top_box.y0) / 2
    gap = top_box.y0 - bottom_box.y1
    amplitude = gap * 0.10
    for offset in (-gap * 0.12, gap * 0.12):
        y_values = [
            center_y + offset + amplitude * math.sin(index / 480 * math.tau * 14)
            for index in range(481)
        ]
        fig.add_artist(Line2D(
            x_values,
            y_values,
            transform=fig.transFigure,
            color="#334155",
            linewidth=1.1,
            solid_capstyle="round",
        ))


def plot_poster_challenge_layout(path: Path, rows: list[dict[str, object]]) -> None:
    """Render a single-slide mock: measured p95 trend plus pipeline explanation."""
    configure_korean_font()
    labels = [str(row["stage"]) for row in rows]
    values = [float(row["p95_median_ms"]) / 1000 for row in rows]
    colors = [point_color(row) for row in rows]
    positions = list(range(len(rows)))

    fig = plt.figure(figsize=(16, 9), facecolor="#F8FAFC")
    fig.text(0.055, 0.93, "01", color="white", fontsize=23, fontweight="bold", ha="center", va="center",
             bbox={"boxstyle": "circle,pad=0.46", "facecolor": "#2563C9", "edgecolor": "none"})
    fig.text(0.10, 0.945, "8만 상품 개인화 추천 파이프라인 성능 최적화", fontsize=21, fontweight="bold", color="#1D4ED8")
    fig.text(0.10, 0.902, "병목 구간을 계측하고, 후보 추출 · 점수화 · 저장/응답을 순차적으로 재설계", fontsize=11.5, color="#64748B")

    chart_grid = fig.add_gridspec(2, 1, left=0.07, right=0.63, bottom=0.27, top=0.82,
                                  height_ratios=[1, 3], hspace=0.06)
    top_ax = fig.add_subplot(chart_grid[0])
    bottom_ax = fig.add_subplot(chart_grid[1], sharex=top_ax)
    for axis in (top_ax, bottom_ax):
        axis.set_facecolor("white")
        axis.plot(positions[1:], values[1:], color="#94A3B8", linewidth=1.7, linestyle="--", zorder=1)
        axis.scatter(positions, values, s=58, color=colors, zorder=3, edgecolors="white", linewidth=0.8)
        axis.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    top_ax.set_ylim(48, 54.4)
    bottom_ax.set_ylim(2.2, 14.1)
    top_ax.spines["bottom"].set_visible(False)
    bottom_ax.spines["top"].set_visible(False)
    top_ax.tick_params(axis="x", bottom=False, labelbottom=False)
    bottom_ax.set_xticks(positions, labels, fontsize=7.5)
    bottom_ax.set_ylabel("Recommendation HTTP p95 (seconds)", fontsize=9)
    for index, value in enumerate(values):
        axis = top_ax if value >= 48 else bottom_ax
        axis.annotate(f"{value:.1f}s", (index, value), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=7.2, color="#0F172A")
    fig.tight_layout()
    draw_figure_break_wave(fig, top_ax, bottom_ax)
    fig.text(0.07, 0.235, "Measured end-to-end p95 checkpoints. Red: reverted experiment. Orange: Redis warm cache.", fontsize=8.5, color="#64748B")

    panel = fig.add_axes([0.67, 0.27, 0.28, 0.55])
    panel.set_axis_off()
    savings = pipeline_savings(rows)
    panel.text(0.0, 1.03, "추천 처리 범위 축소", fontsize=16, fontweight="bold", color="#0F172A")
    panel.text(0.0, 0.975, "측정된 p95는 왼쪽 그래프에서 확인", fontsize=9.5, color="#64748B")
    pipeline_cards = (
        (0.72, "ES 후보 500개", "Elasticsearch 중심 후보 추출", "Opt1 · Opt6", "#DBEAFE", "#1D4ED8"),
        (0.42, "빠른 500개 → 상세 50개", "사전 집계 · bulk prefetch · cascade scoring", "Opt2 · Opt3 · Opt4c · Opt5", "#DCFCE7", "#15803D"),
        (0.12, "결과·근거 저장 → 화면 10개", "불필요 저장 제거 · Core SQL · projection query", "Opt7 · Opt8b · Opt9", "#F3E8FF", "#7E22CE"),
    )
    for index, (y, title, body, stage, fill, accent) in enumerate(pipeline_cards):
        # Keep the embedded poster panel in one visual system. The standalone
        # pipeline map below carries the richer card treatment.
        fill = "#F8FBFF"
        accent = "#2563EB"
        panel.add_patch(FancyBboxPatch((0.0, y), 1.0, 0.19, boxstyle="round,pad=0.018,rounding_size=0.025",
                                       linewidth=0.8, edgecolor=accent, facecolor=fill))
        panel.text(0.045, y + 0.125, title, fontsize=12.2, fontweight="bold", color="#0F172A")
        panel.text(0.045, y + 0.072, body, fontsize=8.7, color="#334155")
        panel.text(0.045, y + 0.025, str(savings[index]["stages"]), fontsize=8.5, color=accent, fontweight="bold")
        panel.text(0.95, y + 0.125, f"-{float(savings[index]['saving']):.2f}s", ha="right", fontsize=10.5, color=accent, fontweight="bold")
        panel.text(0.95, y + 0.070, "채택 단계 누적 절감", ha="right", fontsize=6.9, color="#64748B")
    panel.annotate("", xy=(0.5, 0.63), xytext=(0.5, 0.71), arrowprops={"arrowstyle": "-|>", "color": "#94A3B8", "lw": 1.5})
    panel.annotate("", xy=(0.5, 0.33), xytext=(0.5, 0.41), arrowprops={"arrowstyle": "-|>", "color": "#94A3B8", "lw": 1.5})

    footer = fig.add_axes([0.055, 0.06, 0.89, 0.12])
    footer.set_axis_off()
    footer.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.015,rounding_size=0.03",
                                    linewidth=0.9, edgecolor="#BFDBFE", facecolor="#FFFFFF"))
    footer.text(0.035, 0.63, "Core pipeline", fontsize=10, color="#64748B", fontweight="bold")
    footer.text(0.035, 0.25, "p95 52.01s → 4.48s", fontsize=18, color="#2563C9", fontweight="bold")
    footer.text(0.37, 0.63, "Measured improvement", fontsize=10, color="#64748B", fontweight="bold")
    footer.text(0.37, 0.25, "91.4% reduction", fontsize=18, color="#2563C9", fontweight="bold")
    footer.text(0.67, 0.63, "Best serving condition", fontsize=10, color="#64748B", fontweight="bold")
    footer.text(0.67, 0.25, "p95 3.12s · 4.63 RPS · 0% errors", fontsize=15.5, color="#2563C9", fontweight="bold")
    fig.savefig(path, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)


def collect_scale_sweep_rows(repo_root: Path, stage_id: str) -> list[dict[str, object]]:
    """Load one 3-minute full-personalized run per dataset/VUS scale cell."""
    run_root = repo_root / "perf-runs" / "stages" / stage_id / "runs" / "scale-sweep"
    rows: list[dict[str, object]] = []
    for manifest_path in sorted(run_root.rglob("manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not (
            manifest.get("user_type") == "full-personalized"
            and manifest.get("duration") == "3m"
            and str(manifest.get("dataset")) in {"1000", "5000", "10000", "80000"}
            and int(manifest.get("vus") or 0) in {1, 3, 5, 8, 10}
        ):
            continue
        summary_path = manifest_path.parent / "k6" / "k6-summary.json"
        if not summary_path.exists():
            summary_path = manifest_path.parent / "k6-summary.json"
        if not summary_path.exists():
            continue
        metrics = json.loads(summary_path.read_text(encoding="utf-8"))["metrics"]
        duration = metrics.get("http_req_duration{type:recommendation}") or metrics["http_req_duration"]
        rows.append(
            {
                "dataset": int(manifest["dataset"]),
                "vus": int(manifest["vus"]),
                "p95_ms": float(duration["p(95)"]),
            }
        )

    expected = {(dataset, vus) for dataset in (1000, 5000, 10000, 80000) for vus in (1, 3, 5, 8, 10)}
    actual = {(int(row["dataset"]), int(row["vus"])) for row in rows}
    missing = expected - actual
    if missing:
        raise ValueError(f"{stage_id} scale sweep is incomplete: {sorted(missing)}")
    return rows


def stage_value_map(rows: list[dict[str, object]]) -> dict[str, float]:
    return {str(row["stage_id"]): float(row["p95_median_ms"]) / 1000 for row in rows}


def pipeline_savings(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Group only retained sequential checkpoints; reverted attempts are excluded."""
    values = stage_value_map(rows)

    def delta(previous: str, current: str) -> float:
        return max(0.0, values[previous] - values[current])

    return [
        {
            "number": "01",
            "title": "ES 후보 500개",
            "description": "Elasticsearch 후보 추출 · 후보 캐시",
            "stages": "Opt1 · Opt6 · Opt10",
            "saving": delta("baseline-v1", "opt1-es-retrieval") + delta("opt5-selected-detail-ingredients", "opt6-candidate-pool-v2") + delta("opt9-response-load", "opt10-candidate-cache"),
        },
        {
            "number": "02",
            "title": "빠른 500개 → 상세 50개",
            "description": "사전 집계 feature · bulk prefetch · cascade scoring",
            "stages": "Opt2 · Opt3 · Opt4c · Opt5",
            "saving": delta("opt1-es-retrieval", "opt2-precomputed-features") + delta("opt2-precomputed-features", "opt3-bulk-prefetch") + delta("opt3-bulk-prefetch", "opt4c-coarse-top50") + delta("opt4c-coarse-top50", "opt5-selected-detail-ingredients"),
        },
        {
            "number": "03",
            "title": "결과·근거 저장 → 화면 10개",
            "description": "후보 추적 제거 · Core SQL · projection query",
            "stages": "Opt7 · Opt8b · Opt9",
            "saving": delta("opt6-candidate-pool-v2", "opt7-remove-candidate-trace") + delta("opt7-remove-candidate-trace", "opt8b-raw-sql-persist") + delta("opt8b-raw-sql-persist", "opt9-response-load"),
        },
    ]


def plot_pipeline_optimization_map(path: Path, rows: list[dict[str, object]]) -> None:
    """Render a poster-ready pipeline map with measured retained checkpoint deltas."""
    configure_korean_font()
    groups = pipeline_savings(rows)
    values = stage_value_map(rows)
    baseline = values["baseline-v1"]
    opt10 = values["opt10-candidate-cache"]
    total_reduction = baseline - opt10

    fig, ax = plt.subplots(figsize=(12.5, 8.2), facecolor="#F6F8FC")
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.06, 0.92, "추천 파이프라인: 처리 범위 축소", fontsize=24, fontweight="bold", color="#102A43")
    ax.text(
        0.06,
        0.875,
        "채택된 순차 체크포인트의 p95 감소량 기준 · 80K 상품 / full-personalized / VUS 10 / 3분",
        fontsize=10.5,
        color="#627D98",
    )

    card_y_positions = (0.64, 0.39, 0.14)
    accent_colors = ("#2563EB", "#0F766E", "#475569")
    fills = ("#EDF4FF", "#ECFDF7", "#F3F6FA")
    for index, (group, y, accent, fill) in enumerate(zip(groups, card_y_positions, accent_colors, fills)):
        ax.add_patch(
            FancyBboxPatch(
                (0.06, y),
                0.88,
                0.17,
                boxstyle="round,pad=0.012,rounding_size=0.018",
                linewidth=1.1,
                edgecolor="#D7E2F0",
                facecolor=fill,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (0.075, y + 0.03),
                0.075,
                0.11,
                boxstyle="round,pad=0.006,rounding_size=0.016",
                linewidth=0,
                facecolor=accent,
            )
        )
        ax.text(0.1125, y + 0.085, str(group["number"]), ha="center", va="center", fontsize=13, color="white", fontweight="bold")
        ax.text(0.175, y + 0.113, str(group["title"]), fontsize=17, fontweight="bold", color="#102A43")
        ax.text(0.175, y + 0.068, str(group["description"]), fontsize=10.5, color="#486581")
        ax.text(0.175, y + 0.025, str(group["stages"]), fontsize=10, color=accent, fontweight="bold")
        ax.text(0.90, y + 0.104, f"-{float(group['saving']):.2f}s", ha="right", fontsize=20, color=accent, fontweight="bold")
        ax.text(0.90, y + 0.057, "채택 단계 누적 p95 절감", ha="right", fontsize=8.8, color="#627D98")
        if index < len(groups) - 1:
            ax.annotate(
                "",
                xy=(0.50, y - 0.025),
                xytext=(0.50, y - 0.070),
                arrowprops={"arrowstyle": "-|>", "color": "#9FB3C8", "lw": 1.8},
            )

    ax.add_patch(
        FancyBboxPatch(
            (0.06, 0.03),
            0.88,
            0.065,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0,
            facecolor="#102A43",
        )
    )
    ax.text(0.09, 0.061, f"Baseline {baseline:.2f}s", fontsize=12.5, color="#D9E2EC", va="center", fontweight="bold")
    ax.text(0.50, 0.061, f"총 p95 절감 -{total_reduction:.2f}s", fontsize=15, color="white", va="center", ha="center", fontweight="bold")
    ax.text(0.91, 0.061, f"Opt10 {opt10:.2f}s", fontsize=12.5, color="#8DE0D0", va="center", ha="right", fontweight="bold")

    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def scale_value_map(rows: list[dict[str, object]]) -> dict[tuple[int, int], float]:
    return {(int(row["dataset"]), int(row["vus"])): float(row["p95_ms"]) / 1000 for row in rows}


def plot_scale_heatmap_comparison(
    path: Path,
    baseline_rows: list[dict[str, object]],
    opt10_rows: list[dict[str, object]],
) -> None:
    """Render the scale cliff and the same-grid Opt10 warm-cache recovery."""
    configure_korean_font()
    datasets = (1000, 5000, 10000, 80000)
    vus_values = (1, 3, 5, 8, 10)
    baseline = scale_value_map(baseline_rows)
    opt10 = scale_value_map(opt10_rows)
    cmap = ListedColormap(["#DDF4EC", "#B8E1D4", "#F7D17E", "#E86B5D"])
    norm = BoundaryNorm((0, 3, 5, 10, 60), cmap.N)

    fig, axes = plt.subplots(1, 2, figsize=(14, 7.8), facecolor="#F6F8FC")
    fig.suptitle("8만 상품 구간의 p95 안정화", fontsize=22, fontweight="bold", color="#102A43", y=0.985)
    fig.text(0.5, 0.932, "동일한 데이터 크기 · 동시 사용자 조합에서 측정한 추천 API p95", ha="center", fontsize=10.5, color="#627D98")

    for axis, values, title in (
        (axes[0], baseline, "Baseline · cold candidate path"),
        (axes[1], opt10, "Opt10 · Redis warm candidate cache"),
    ):
        matrix = [[values[(dataset, vus)] for dataset in datasets] for vus in vus_values]
        axis.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
        axis.set_title(title, fontsize=13.5, fontweight="bold", color="#243B53", pad=14)
        axis.set_xticks(range(len(datasets)), [f"{dataset // 1000}K" for dataset in datasets])
        axis.set_yticks(range(len(vus_values)), [f"VUS {vus}" for vus in vus_values])
        axis.tick_params(length=0, labelsize=11, colors="#334E68")
        for row_index, vus in enumerate(vus_values):
            for column_index, dataset in enumerate(datasets):
                value = values[(dataset, vus)]
                text_color = "white" if value >= 10 else "#102A43"
                axis.text(column_index, row_index, f"{value:.2f}s", ha="center", va="center", fontsize=10.5, color=text_color, fontweight="bold")
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.set_xticks([index - 0.5 for index in range(len(datasets) + 1)], minor=True)
        axis.set_yticks([index - 0.5 for index in range(len(vus_values) + 1)], minor=True)
        axis.grid(which="minor", color="white", linewidth=2.2)
        axis.tick_params(which="minor", bottom=False, left=False)

    legend = [
        Patch(facecolor="#DDF4EC", label="< 3s"),
        Patch(facecolor="#B8E1D4", label="3–5s"),
        Patch(facecolor="#F7D17E", label="5–10s"),
        Patch(facecolor="#E86B5D", label=">= 10s"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.085), fontsize=10)
    baseline_80k = baseline[(80000, 10)]
    opt10_80k = opt10[(80000, 10)]
    fig.text(
        0.5,
        0.145,
        f"80K / VUS 10: {baseline_80k:.2f}s → {opt10_80k:.2f}s  ({(1 - opt10_80k / baseline_80k) * 100:.1f}% 감소)",
        ha="center",
        fontsize=12.5,
        color="#0F766E",
        fontweight="bold",
    )
    fig.tight_layout(rect=(0.02, 0.19, 0.98, 0.84))
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


def plot_80k_dumbbell_comparison(
    path: Path,
    baseline_rows: list[dict[str, object]],
    opt10_rows: list[dict[str, object]],
) -> None:
    """Show the before/after p95 gap at 80K for every concurrency level."""
    configure_korean_font()
    baseline = scale_value_map(baseline_rows)
    opt10 = scale_value_map(opt10_rows)
    vus_values = (1, 3, 5, 8, 10)
    y_positions = list(range(len(vus_values)))
    before = [baseline[(80000, vus)] for vus in vus_values]
    after = [opt10[(80000, vus)] for vus in vus_values]

    fig, ax = plt.subplots(figsize=(12, 6.6), facecolor="#F6F8FC")
    ax.set_facecolor("#F6F8FC")
    for y, before_value, after_value in zip(y_positions, before, after):
        ax.hlines(y, after_value, before_value, color="#B8C7D9", linewidth=4, zorder=1)
        ax.scatter(after_value, y, s=135, color="#0F766E", edgecolor="white", linewidth=1.6, zorder=3)
        ax.scatter(before_value, y, s=135, color="#E86B5D", edgecolor="white", linewidth=1.6, zorder=3)
        ax.text(after_value - 0.45, y - 0.20, f"{after_value:.2f}s", ha="right", va="center", fontsize=10.5, color="#0F766E", fontweight="bold")
        ax.text(before_value + 0.45, y - 0.20, f"{before_value:.2f}s", ha="left", va="center", fontsize=10.5, color="#B42318", fontweight="bold")
        ax.text((before_value + after_value) / 2, y + 0.22, f"-{(1 - after_value / before_value) * 100:.1f}%", ha="center", va="center", fontsize=9.5, color="#627D98")

    ax.set_yticks(y_positions, [f"VUS {vus}" for vus in vus_values])
    ax.invert_yaxis()
    ax.set_ylim(len(vus_values) - 0.62, -0.62)
    ax.set_xlim(-1, max(before) + 7)
    ax.set_xlabel("Recommendation HTTP p95 (seconds)", color="#334E68")
    ax.set_title("80K 개인화 추천: 동시 사용자 증가에도 유지된 p95", fontsize=19, fontweight="bold", color="#102A43", pad=18)
    ax.text(0.5, 1.01, "full-personalized · 3-minute scale sweep · Baseline cold vs Opt10 Redis warm", transform=ax.transAxes, ha="center", fontsize=10, color="#627D98")
    ax.grid(axis="x", color="#D9E2EC", linewidth=0.9)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0, colors="#334E68")
    ax.tick_params(axis="x", colors="#627D98")
    fig.legend(
        handles=[
            Line2D([0], [0], marker="o", color="none", markerfacecolor="#E86B5D", markersize=9, label="Baseline"),
            Line2D([0], [0], marker="o", color="none", markerfacecolor="#0F766E", markersize=9, label="Opt10 warm"),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        frameon=False,
        ncol=2,
        fontsize=10,
    )
    fig.tight_layout(rect=(0.02, 0.075, 0.98, 1.0))
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def configure_korean_font() -> None:
    font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
    if font_path.exists():
        font_manager.fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams["axes.unicode_minus"] = False


def collect_worker_rows(repo_root: Path) -> list[dict[str, object]]:
    """Summarize all comparable Opt11 80k/VUS10/3-minute warm-cache runs."""
    run_root = repo_root / "perf-runs" / "stages" / "opt11-worker-scaleout" / "runs"
    grouped: dict[int, list[dict[str, float]]] = {}
    for manifest_path in run_root.rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = str(manifest.get("run_id") or "")
        if not (
            str(manifest.get("dataset")) == "80000"
            and str(manifest.get("vus")) == "10"
            and manifest.get("duration") == "3m"
            and manifest.get("user_type") == "full-personalized"
            and manifest.get("candidate_cache_state") == "warm"
        ):
            continue
        worker_marker = run_id.split("-w", 1)
        if len(worker_marker) != 2:
            continue
        worker_count = int(worker_marker[1].split("-", 1)[0])
        summary_path = manifest_path.parent / "k6" / "k6-summary.json"
        if not summary_path.exists():
            summary_path = manifest_path.parent / "k6-summary.json"
        metrics = json.loads(summary_path.read_text(encoding="utf-8"))["metrics"]
        duration = metrics.get("http_req_duration{type:recommendation}") or metrics["http_req_duration"]
        grouped.setdefault(worker_count, []).append(
            {
                "avg_ms": float(duration["avg"]),
                "p95_ms": float(duration["p(95)"]),
                "rps": float(metrics["iterations"]["rate"]),
            }
        )

    result: list[dict[str, object]] = []
    for workers, runs in sorted(grouped.items()):
        p95 = [run["p95_ms"] for run in runs]
        averages = [run["avg_ms"] for run in runs]
        rps = [run["rps"] for run in runs]
        result.append(
            {
                "workers": workers,
                "run_count": len(runs),
                "p95_median_ms": round(statistics.median(p95), 2),
                "p95_min_ms": round(min(p95), 2),
                "p95_max_ms": round(max(p95), 2),
                "avg_median_ms": round(statistics.median(averages), 2),
                "rps_median": round(statistics.median(rps), 3),
                "rps_min": round(min(rps), 3),
                "rps_max": round(max(rps), 3),
            }
        )
    return result


def plot_worker_scaleout(path: Path, rows: list[dict[str, object]]) -> None:
    labels = [f"{int(row['workers'])} worker" for row in rows]
    p95 = [float(row["p95_median_ms"]) / 1000 for row in rows]
    p95_low = [value - float(row["p95_min_ms"]) / 1000 for value, row in zip(p95, rows)]
    p95_high = [float(row["p95_max_ms"]) / 1000 - value for value, row in zip(p95, rows)]
    rps = [float(row["rps_median"]) for row in rows]

    fig, (latency_ax, rps_ax) = plt.subplots(1, 2, figsize=(13, 5.5))
    bars = latency_ax.bar(labels, p95, color="#2563EB", yerr=[p95_low, p95_high], capsize=7)
    for bar, value in zip(bars, p95):
        latency_ax.text(bar.get_x() + bar.get_width() / 2, value + 0.07, f"{value:.2f}s", ha="center", fontsize=10)
    latency_ax.set_ylabel("Recommendation HTTP p95 (seconds)")
    latency_ax.set_title("p95 median with min-max range")
    latency_ax.grid(axis="y", alpha=0.25)

    bars = rps_ax.bar(labels, rps, color="#0F766E")
    for bar, value in zip(bars, rps):
        rps_ax.text(bar.get_x() + bar.get_width() / 2, value + 0.05, f"{value:.2f}", ha="center", fontsize=10)
    rps_ax.set_ylabel("Completed recommendations / second")
    rps_ax.set_title("Median throughput")
    rps_ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Opt11 Uvicorn worker scale-out: 80k / full-personalized / VUS 10 / 3-minute / Redis warm", y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_readme(path: Path, rows: list[dict[str, object]]) -> None:
    baseline = float(rows[0]["p95_median_ms"])
    opt9 = next(row for row in rows if row["stage_id"] == "opt9-response-load")
    opt10 = next(row for row in rows if row["stage_id"] == "opt10-candidate-cache")
    opt11 = next(row for row in rows if row["stage_id"] == "opt11-worker-scaleout")
    text = "\n".join(
        [
            "# Opt10 Optimization Timeline",
            "",
            "Condition: 79,952 actual products, full-personalized user, VUS 10, 3-minute run, query set=all.",
            "Each point is the median of the explicitly listed run IDs in `stage-summary.csv`.",
            "",
            f"- Baseline p95: {baseline / 1000:.2f}s",
            f"- Opt9 p95: {float(opt9['p95_median_ms']) / 1000:.2f}s ({(1 - float(opt9['p95_median_ms']) / baseline) * 100:.1f}% lower than baseline)",
            f"- Opt10 warm-cache p95: {float(opt10['p95_median_ms']) / 1000:.2f}s ({(1 - float(opt10['p95_median_ms']) / baseline) * 100:.1f}% lower than baseline)",
            f"- Opt11 best comparable 3-minute worker run p95: {float(opt11['p95_median_ms']) / 1000:.2f}s ({(1 - float(opt11['p95_median_ms']) / baseline) * 100:.1f}% lower than baseline)",
            "",
            "## Reading the graphs",
            "",
            "- `01-p95-optimization-trend.png`: primary latency trend. Every measured optimization attempt is shown with a broken y-axis, so the 52-second baseline and later 3-13 second changes remain readable together. Red points are reverted/regression experiments; orange points are warm Redis cache measurements.",
            "- `02-rps-optimization-trend.png`: completed recommendation throughput.",
            "- `03-p95-reduction-by-stage.png`: cumulative reduction versus baseline.",
            "- `04-p95-optimization-trend-opt1-onward.png`: magnified Opt1-to-Opt10 p95 trend, so later improvements remain visible despite the 52-second baseline.",
            "- `05-opt11-worker-scaleout.png`: worker-scale comparison; it uses all completed comparable Opt11 runs, unlike the main timeline's selected best Opt11 checkpoint.",
            "",
            "The Opt9 run with p95 around 65ms is intentionally excluded because it is not plausible under the surrounding 3-minute VUS10 measurements. The selected Opt9 runs are the later stable repeats. Opt11 uses the best 3-minute warm-cache worker run rather than the shorter 30-second pilot.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
