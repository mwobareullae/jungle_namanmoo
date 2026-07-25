"""Render the compact performance figures embedded by the repository README."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
import numpy as np
import seaborn as sns


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "docs" / "performance" / "results" / "recommendation" / "readme"

# Source: docs/performance/results/recommendation/data/graph-contract.csv and
# scripts/perf/generate_opt10_optimization_timeline.py. Values are p95 seconds.
BASELINE_SCALE_P95 = np.array(
    [
        [0.55, 0.96, 1.08, 10.02],
        [1.08, 2.37, 2.93, 19.96],
        [1.72, 4.00, 5.09, 33.25],
        [2.81, 6.27, 7.23, 42.01],
        [3.37, 8.16, 9.04, 52.01],
    ]
)

MILESTONES = (
    ("Baseline", 52.01, "Baseline"),
    ("후보 추출", 12.80, "Candidate retrieval"),
    ("점수화", 6.48, "Scoring"),
    ("저장·응답", 4.48, "Persist + response"),
    ("캐시·동시 처리", 3.12, "Warm cache + workers"),
)


def configure_font() -> None:
    windows_font = Path(r"C:\Windows\Fonts\malgun.ttf")
    if windows_font.exists():
        font_manager.fontManager.addfont(str(windows_font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=windows_font).get_name()
        plt.rcParams["axes.unicode_minus"] = False
        return

    preferred_fonts = ("Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans")
    available = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in preferred_fonts:
        if font_name in available:
            plt.rcParams["font.family"] = font_name
            break
    plt.rcParams["axes.unicode_minus"] = False


def render_baseline_heatmap() -> None:
    figure, axis = plt.subplots(figsize=(10.8, 5.9), constrained_layout=True)
    cmap = LinearSegmentedColormap.from_list(
        "recommendation_p95",
        ["#F0F9FF", "#CFFAFE", "#38BDF8", "#2563EB", "#312E81"],
    )
    heatmap = sns.heatmap(
        BASELINE_SCALE_P95,
        ax=axis,
        cmap=cmap,
        vmin=0,
        vmax=55,
        annot=np.vectorize(lambda value: f"{value:.2f}s")(BASELINE_SCALE_P95),
        fmt="",
        linewidths=1.4,
        linecolor="#FFFFFF",
        cbar_kws={"label": "추천 API p95 (초)", "ticks": [0, 10, 20, 30, 40, 50]},
    )
    axis.set_title("상품 규모와 동시 요청이 커질 때 드러난 추천 병목", loc="left", pad=16, fontsize=17, fontweight="bold")
    axis.text(
        0,
        1.02,
        "Baseline · full-personalized · cold cache · 3분 run",
        transform=axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#475569",
    )
    axis.set_xlabel("상품 수")
    axis.set_ylabel("동시 사용자 (VUS)")
    axis.set_xticklabels(["1K", "5K", "10K", "80K"], rotation=0)
    axis.set_yticklabels(["1", "3", "5", "8", "10"], rotation=0)
    axis.tick_params(length=0)
    heatmap.collections[0].colorbar.ax.tick_params(length=0)

    figure.savefig(OUTPUT_DIR / "01-baseline-scale-heatmap.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def render_optimization_milestones() -> None:
    labels = [label for label, _, _ in MILESTONES]
    values = [value for _, value, _ in MILESTONES]
    positions = np.arange(len(values))
    colors = ["#7C3AED", "#2563EB", "#0EA5E9", "#14B8A6", "#F97316"]

    figure, (upper_axis, lower_axis) = plt.subplots(
        2,
        1,
        figsize=(10.8, 6.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.15, 3], "hspace": 0.08},
        constrained_layout=True,
    )

    for axis in (upper_axis, lower_axis):
        axis.set_facecolor("#FFFFFF")
        axis.grid(axis="y", color="#E2E8F0", linewidth=0.8)
        axis.spines[["left", "right"]].set_color("#CBD5E1")
        axis.plot(positions[1:], values[1:], color="#94A3B8", linewidth=2, linestyle="--", zorder=1)
        axis.scatter(positions, values, s=92, color=colors, edgecolor="#FFFFFF", linewidth=1.8, zorder=3)

    upper_axis.set_ylim(48, 55)
    lower_axis.set_ylim(0, 15)
    upper_axis.spines["bottom"].set_visible(False)
    lower_axis.spines["top"].set_visible(False)
    upper_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    lower_axis.set_xticks(positions, labels)
    lower_axis.set_ylabel("추천 API p95 (초)")

    for index, value in enumerate(values):
        axis = upper_axis if index == 0 else lower_axis
        axis.annotate(
            f"{value:.2f}s",
            (index, value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            fontweight="bold",
            color=colors[index],
        )

    # Paired waves make the omitted range explicit without implying a continuous line.
    wave_x = np.linspace(-0.02, 1.02, 240)
    for axis, base_y in ((upper_axis, 0.0), (lower_axis, 1.0)):
        for offset in (-0.018, 0.018):
            wave_y = base_y + offset + np.sin(wave_x * np.pi * 18) * 0.012
            axis.plot(
                wave_x,
                wave_y,
                transform=axis.transAxes,
                color="#64748B",
                linewidth=1.1,
                clip_on=False,
            )

    upper_axis.set_title("병목을 분리한 뒤 핵심 이정표별 p95 변화", loc="left", pad=16, fontsize=17, fontweight="bold")
    upper_axis.text(
        0,
        1.02,
        "80K 상품 · full-personalized · VUS 10 · Baseline cold cache / 최종 warm cache + multi-worker",
        transform=upper_axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        color="#475569",
    )
    lower_axis.legend(
        handles=[Patch(facecolor=color, edgecolor="none", label=detail) for color, (_, _, detail) in zip(colors, MILESTONES)],
        loc="upper left",
        bbox_to_anchor=(0, -0.28),
        ncol=3,
        frameon=False,
        fontsize=9,
    )
    lower_axis.text(
        0.99,
        -0.25,
        "52.01초 → 3.12초  |  48.89초 감소 (약 94%)",
        transform=lower_axis.transAxes,
        ha="right",
        va="center",
        fontsize=10,
        fontweight="bold",
        color="#0F172A",
    )

    figure.savefig(OUTPUT_DIR / "02-optimization-milestones.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def main() -> None:
    sns.set_theme(style="white", context="notebook")
    configure_font()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    render_baseline_heatmap()
    render_optimization_milestones()
    print(f"generated={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
