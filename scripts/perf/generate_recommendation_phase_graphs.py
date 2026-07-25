"""Render drill-down figures for the recommendation performance guide.

The figures deliberately separate end-to-end HTTP p95 from internal averages.
Percentiles are not additive, so the two measurements must not be combined.
"""

from __future__ import annotations

import math
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "docs" / "performance" / "recommendation" / "assets"


TIMELINE = (
    ("Baseline", 52.01, "baseline"),
    ("Opt1", 12.80, "improved"),
    ("Opt2", 7.77, "improved"),
    ("Opt3", 7.38, "improved"),
    ("Opt4a", 8.62, "reverted"),
    ("Opt4b", 8.69, "reverted"),
    ("Opt4c", 7.34, "improved"),
    ("Opt5", 6.76, "improved"),
    ("Opt6", 6.48, "improved"),
    ("Opt7", 5.43, "improved"),
    ("Opt8", 5.65, "reverted"),
    ("Opt8b", 4.74, "improved"),
    ("Opt9", 4.48, "improved"),
    ("Opt10", 4.00, "cache"),
    ("Opt11", 3.12, "final"),
)

TIMELINE_COLORS = {
    "baseline": "#7C3AED",
    "improved": "#2563EB",
    "reverted": "#DC2626",
    "cache": "#EA580C",
    "final": "#059669",
}


def configure_font() -> None:
    windows_font = Path(r"C:\Windows\Fonts\malgun.ttf")
    if windows_font.exists():
        font_manager.fontManager.addfont(str(windows_font))
        plt.rcParams["font.family"] = font_manager.FontProperties(
            fname=windows_font
        ).get_name()
    else:
        plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams["axes.unicode_minus"] = False


def render_phase_pair(
    *,
    filename: str,
    title: str,
    subtitle: str,
    e2e_before: float,
    e2e_after: float,
    target_label: str,
    target_before: float,
    target_after: float,
    target_unit: str = "s",
    target_note: str,
) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(10.6, 5.8))
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.13, top=0.75, hspace=0.38)
    accent = "#2563EB"
    before_color = "#CBD5E1"
    after_color = "#0EA5E9"

    for axis, label, before, after, unit in (
        (axes[0], "전체 추천 API HTTP p95", e2e_before, e2e_after, "s"),
        (axes[1], target_label, target_before, target_after, target_unit),
    ):
        axis.barh(["변경 전", "변경 후"], [before, after], color=[before_color, after_color], height=0.5)
        axis.invert_yaxis()
        axis.set_xlim(0, max(before, after) * 1.23 if max(before, after) else 1)
        axis.grid(axis="x", color="#E2E8F0", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0)
        for index, value in enumerate((before, after)):
            axis.text(
                value + max(before, after) * 0.02,
                index,
                f"{value:.2f}{unit}",
                va="center",
                color="#0F172A",
                fontweight="bold",
            )
        reduction = (1 - after / before) * 100 if before else 0
        axis.set_title(
            f"{label}  |  {before:.2f}{unit} -> {after:.2f}{unit}  ({reduction:.1f}% 감소)",
            loc="left",
            fontsize=11.5,
            fontweight="bold",
            color=accent,
            pad=9,
        )

    figure.suptitle(title, x=0.08, y=0.97, ha="left", fontsize=17, fontweight="bold", color="#0F172A")
    figure.text(0.08, 0.88, subtitle, color="#475569", fontsize=9.5)
    axes[1].text(0, -0.34, target_note, transform=axes[1].transAxes, color="#475569", fontsize=9)
    figure.savefig(OUTPUT_DIR / filename, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def render_opt1_baseline_drilldown_legacy_means() -> None:
    """Show the measured path from end-to-end p95 to the Opt1 bottleneck.

    Internal averages are intentionally not presented as a p95 decomposition.
    They were used to decide where to instrument and optimize first.
    """

    figure = plt.figure(figsize=(11.2, 7.0))
    grid = figure.add_gridspec(
        3,
        1,
        height_ratios=(1.25, 0.38, 3.1),
        hspace=0.05,
        left=0.08,
        right=0.96,
        top=0.86,
        bottom=0.12,
    )
    outcome_axis = figure.add_subplot(grid[0])
    arrow_axis = figure.add_subplot(grid[1])
    stages_axis = figure.add_subplot(grid[2])

    for axis in (outcome_axis, arrow_axis, stages_axis):
        axis.set_axis_off()

    outcome_axis.text(
        0.5,
        0.70,
        "Baseline 추천 API HTTP p95",
        ha="center",
        va="center",
        fontsize=12,
        color="#475569",
    )
    outcome_axis.text(
        0.5,
        0.32,
        "52.01초",
        ha="center",
        va="center",
        fontsize=32,
        fontweight="bold",
        color="#7C3AED",
        bbox={
            "boxstyle": "round,pad=0.52",
            "facecolor": "#F3E8FF",
            "edgecolor": "#C084FC",
            "linewidth": 1.4,
        },
    )
    arrow_axis.annotate(
        "",
        xy=(0.5, 0.02),
        xytext=(0.5, 0.98),
        arrowprops={"arrowstyle": "-|>", "color": "#94A3B8", "lw": 1.8},
    )

    values = (21.93, 6.97, 2.18, 4.73)
    labels = (
        "intent parse\n21.93초",
        "scoring\n6.97초",
        "candidate\n2.18초",
        "other\n4.73초",
    )
    colors = ("#7C3AED", "#2563EB", "#0EA5E9", "#CBD5E1")
    total = sum(values)
    left = 0.0
    for value, label, color in zip(values, labels, colors, strict=True):
        width = value / total
        stages_axis.barh(0.50, width, left=left, height=0.35, color=color)
        label_color = "#FFFFFF" if color != "#CBD5E1" else "#334155"
        stages_axis.text(
            left + width / 2,
            0.50,
            label,
            ha="center",
            va="center",
            fontsize=11 if value >= 5 else 9.5,
            fontweight="bold",
            color=label_color,
        )
        left += width

    stages_axis.set_xlim(0, 1)
    stages_axis.set_ylim(0, 1)
    stages_axis.text(
        0,
        0.93,
        "같은 Baseline run의 내부 단계 평균 계측",
        fontsize=14,
        fontweight="bold",
        color="#0F172A",
    )
    stages_axis.text(
        0,
        0.80,
        "p95를 분해한 값이 아니라, 병목 후보를 찾기 위해 분리 측정한 평균입니다.",
        fontsize=9.5,
        color="#475569",
    )
    stages_axis.annotate(
        "구매 조건 파싱 내부에서\n브랜드 alias 약 2,657개를\n매 요청 정규식 전수 검사",
        xy=(values[0] / total / 2, 0.66),
        xytext=(0.18, 0.10),
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#6D28D9",
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "#F3E8FF",
            "edgecolor": "#C084FC",
            "linewidth": 1.2,
        },
        arrowprops={"arrowstyle": "-|>", "color": "#7C3AED", "lw": 1.5},
    )
    stages_axis.text(
        0.62,
        0.10,
        "Opt1 결정\n전수 텍스트 매칭은 Python parser가 아니라\nElasticsearch 역색인 후보 검색으로 이동",
        ha="left",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#075985",
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": "#E0F2FE",
            "edgecolor": "#38BDF8",
            "linewidth": 1.2,
        },
    )

    figure.suptitle(
        "Opt1의 출발점: 전체 지연에서 내부 병목까지",
        x=0.08,
        y=0.97,
        ha="left",
        fontsize=18,
        fontweight="bold",
        color="#0F172A",
    )
    figure.text(
        0.08,
        0.905,
        "80K 상품 · full-personalized · VUS 10 · 3분 run · Baseline cold cache",
        fontsize=10,
        color="#475569",
    )
    figure.savefig(
        OUTPUT_DIR / "01-opt1-baseline-drilldown.png",
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)


def render_opt1_baseline_drilldown() -> None:
    """Render one logged baseline request nearest the measured HTTP p95.

    HTTP p95 is a distribution statistic, so component percentiles and means
    cannot be added to reconstruct it. This chart instead uses one complete
    request trace nearest the k6 p95; its segments add to the actual duration.
    """

    run_dir = (
        REPO_ROOT
        / "perf-runs"
        / "stages"
        / "baseline-v1"
        / "runs"
        / "scale-sweep"
        / "recommendation-80000-full-personalized-20260714-053424"
    )
    summary = json.loads((run_dir / "k6-summary.json").read_text(encoding="utf-8"))
    p95_ms = summary["metrics"]["http_req_duration{type:recommendation}"]["p(95)"]

    events = []
    for raw_line in (run_dir / "backend" / "backend.log").read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if "recommendation_pipeline_completed" not in raw_line:
            continue
        json_start = raw_line.find("{")
        if json_start < 0:
            continue
        try:
            event = json.loads(raw_line[json_start:])
        except json.JSONDecodeError:
            continue
        if event.get("event") == "recommendation_pipeline_completed":
            events.append(event)

    trace = min(events, key=lambda event: abs(event["duration_ms"] - p95_ms))
    context_ms = sum(
        trace.get(key, 0) or 0
        for key in (
            "user_context_load_ms",
            "skin_test_context_load_ms",
            "behavior_context_load_ms",
        )
    )
    candidate_ms = sum(
        trace.get(key, 0) or 0
        for key in (
            "candidate_pool_ms",
            "search_match_ms",
            "search_candidate_save_ms",
        )
    )
    persist_response_ms = sum(
        trace.get(key, 0) or 0
        for key in (
            "run_save_ms",
            "result_save_ms",
            "commit_ms",
            "response_load_ms",
        )
    )
    stages = (
        ("프로필·행동 컨텍스트", context_ms / 1000, "#94A3B8"),
        ("의도 해석", trace["intent_parse_ms"] / 1000, "#7C3AED"),
        ("후보 생성·결합", candidate_ms / 1000, "#0EA5E9"),
        ("개인화 점수화", trace["scoring_ms"] / 1000, "#2563EB"),
        ("저장·응답 구성", persist_response_ms / 1000, "#14B8A6"),
    )
    trace_seconds = trace["duration_ms"] / 1000

    figure, axis = plt.subplots(figsize=(12.0, 5.9))
    figure.subplots_adjust(left=0.08, right=0.97, bottom=0.20, top=0.64)

    left = 0.0
    for label, seconds, color in stages:
        axis.barh(0, seconds, left=left, height=0.48, color=color, edgecolor="white", linewidth=1.5)
        if seconds >= 2.2:
            axis.text(
                left + seconds / 2,
                0,
                f"{label}\n{seconds:.2f}s",
                ha="center",
                va="center",
                fontsize=10.5,
                fontweight="bold",
                color="white",
            )
        left += seconds

    axis.set_xlim(0, math.ceil(trace_seconds) + 1)
    axis.set_yticks([0], ["p95-근접 실제 요청"])
    axis.set_xlabel("서버 파이프라인 시간 (초)", labelpad=10)
    axis.grid(axis="x", color="#E2E8F0", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="y", length=0)
    axis.text(
        trace_seconds + 0.25,
        0,
        f"합계 {trace_seconds:.2f}s",
        va="center",
        ha="left",
        fontsize=11,
        fontweight="bold",
        color="#0F172A",
    )

    figure.suptitle(
        "Baseline p95 근처 실제 요청: 시간은 어디에 쓰였나",
        x=0.08,
        y=0.96,
        ha="left",
        fontsize=18,
        fontweight="bold",
        color="#0F172A",
    )
    figure.text(
        0.08,
        0.885,
        "80K 상품 · full-personalized · VUS 10 · 3분 · cold cache",
        fontsize=10,
        color="#475569",
    )
    figure.text(
        0.08,
        0.785,
        f"HTTP p95 (k6)  {p95_ms / 1000:.2f}s",
        fontsize=11.5,
        fontweight="bold",
        color="#7C3AED",
        bbox={"boxstyle": "round,pad=0.30", "facecolor": "#F3E8FF", "edgecolor": "#C084FC"},
    )
    figure.text(
        0.38,
        0.785,
        f"p95와 가장 가까운 로그  {trace_seconds:.2f}s",
        fontsize=13,
        fontweight="bold",
        color="#0F172A",
        bbox={"boxstyle": "round,pad=0.30", "facecolor": "#F8FAFC", "edgecolor": "#CBD5E1"},
    )
    figure.text(
        0.08,
        0.085,
        "의도 해석 35.33s (66.9%) · 개인화 점수화 10.74s (20.3%) · 후보 생성·결합 3.65s (6.9%) · 저장·응답 2.58s (4.9%)",
        fontsize=10.5,
        color="#334155",
    )
    figure.text(
        0.08,
        0.035,
        "HTTP p95는 분포 통계입니다. 평균 단계값을 더하지 않고, p95에 가장 가까운 단일 요청 로그의 단계 합계를 표시했습니다.",
        fontsize=9,
        color="#64748B",
    )
    figure.savefig(
        OUTPUT_DIR / "01-opt1-baseline-drilldown.png",
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)


def render_cache_and_concurrency() -> None:
    figure, axes = plt.subplots(2, 1, figsize=(10.6, 5.8))
    figure.subplots_adjust(left=0.08, right=0.98, bottom=0.13, top=0.75, hspace=0.38)
    before_color = "#CBD5E1"
    after_color = "#F97316"
    rows = (
        (axes[0], "전체 추천 API HTTP p95", 4.48, 3.12, "s"),
        (axes[1], "완료 처리량 (RPS)", 2.809, 4.631, " req/s"),
    )
    for axis, label, before, after, unit in rows:
        axis.barh(["이전", "캐시 + multi-worker"], [before, after], color=[before_color, after_color], height=0.5)
        axis.invert_yaxis()
        axis.set_xlim(0, max(before, after) * 1.28)
        axis.grid(axis="x", color="#E2E8F0", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0)
        for index, value in enumerate((before, after)):
            axis.text(value + max(before, after) * 0.025, index, f"{value:.3f}{unit}", va="center", fontweight="bold")
        direction = "감소" if label.startswith("전체") else "증가"
        change = abs((after / before - 1) * 100)
        axis.set_title(
            f"{label}  |  {before:.3f}{unit} -> {after:.3f}{unit}  ({change:.1f}% {direction})",
            loc="left",
            fontsize=11.5,
            fontweight="bold",
            color="#EA580C",
            pad=9,
        )

    figure.suptitle("04. 캐시와 동시 처리 확장", x=0.08, y=0.97, ha="left", fontsize=17, fontweight="bold", color="#0F172A")
    figure.text(
        0.08,
        0.88,
        "80K 상품 / full-personalized / VUS 10 / 3분 run. Opt9 cold cache와 Opt11 warm cache + multi-worker를 비교합니다.",
        color="#475569",
        fontsize=9.5,
    )
    axes[1].text(
        0,
        -0.34,
        "p95와 RPS는 서로 다른 지표입니다. 응답 지연과 완료 처리량을 함께 확인해 확장 효과를 판단했습니다.",
        transform=axes[1].transAxes,
        color="#475569",
        fontsize=9,
    )
    figure.savefig(OUTPUT_DIR / "04-cache-concurrency-impact.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def render_full_optimization_timeline() -> None:
    labels = [label for label, _, _ in TIMELINE]
    values = [value for _, value, _ in TIMELINE]
    positions = list(range(len(TIMELINE)))
    colors = [TIMELINE_COLORS[outcome] for _, _, outcome in TIMELINE]

    figure, (upper_axis, lower_axis) = plt.subplots(
        2,
        1,
        figsize=(13.2, 7.8),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 3.0], "hspace": 0.08},
    )
    figure.subplots_adjust(left=0.075, right=0.985, bottom=0.16, top=0.82)

    for axis in (upper_axis, lower_axis):
        axis.grid(axis="y", color="#E2E8F0", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)

    lower_axis.plot(
        positions[1:],
        values[1:],
        color="#94A3B8",
        linewidth=2.2,
        linestyle="--",
        zorder=1,
    )
    upper_axis.scatter(
        [0],
        [values[0]],
        s=118,
        color=colors[0],
        edgecolor="#FFFFFF",
        linewidth=1.8,
        zorder=3,
    )
    lower_axis.scatter(
        positions[1:],
        values[1:],
        s=96,
        color=colors[1:],
        edgecolor="#FFFFFF",
        linewidth=1.7,
        zorder=3,
    )

    upper_axis.set_ylim(48, 55)
    lower_axis.set_ylim(0, 15)
    upper_axis.spines["bottom"].set_visible(False)
    lower_axis.spines["top"].set_visible(False)
    upper_axis.tick_params(axis="x", bottom=False, labelbottom=False)
    lower_axis.set_xticks(positions, labels)
    lower_axis.set_ylabel("추천 API p95 (초)")

    for index, (_, value, outcome) in enumerate(TIMELINE):
        axis = upper_axis if index == 0 else lower_axis
        axis.annotate(
            f"{value:.2f}s",
            (index, value),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            color=TIMELINE_COLORS[outcome],
            fontsize=9.5,
            fontweight="bold",
        )

    wave_x = [position / 220 for position in range(-5, 226)]
    for axis, base_y in ((upper_axis, 0.0), (lower_axis, 1.0)):
        for offset in (-0.018, 0.018):
            wave_y = [
                base_y + offset + math.sin(value * 18 * math.pi) * 0.012
                for value in wave_x
            ]
            axis.plot(
                wave_x,
                wave_y,
                transform=axis.transAxes,
                color="#64748B",
                linewidth=1.1,
                clip_on=False,
            )

    upper_axis.set_title(
        "Baseline부터 Opt11까지: 측정 기반 최적화 타임라인",
        loc="left",
        pad=16,
        fontsize=17,
        fontweight="bold",
        color="#0F172A",
    )
    upper_axis.text(
        0,
        1.03,
        "80K 상품 · full-personalized · VUS 10 · 3분 run · 각 점은 동일 stage의 중앙 p95",
        transform=upper_axis.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#475569",
    )
    lower_axis.legend(
        handles=[
            Patch(facecolor=TIMELINE_COLORS["improved"], edgecolor="none", label="채택한 개선"),
            Patch(facecolor=TIMELINE_COLORS["reverted"], edgecolor="none", label="되돌린 실험·회귀"),
            Patch(facecolor=TIMELINE_COLORS["cache"], edgecolor="none", label="Redis warm cache"),
            Patch(facecolor=TIMELINE_COLORS["final"], edgecolor="none", label="최종 비교 지점"),
        ],
        loc="upper left",
        bbox_to_anchor=(0, -0.25),
        ncol=4,
        frameon=False,
        fontsize=9,
    )
    lower_axis.text(
        0.995,
        -0.25,
        "52.01초 → 3.12초  |  48.89초 감소 (약 94%)",
        transform=lower_axis.transAxes,
        ha="right",
        va="center",
        fontsize=10,
        fontweight="bold",
        color="#0F172A",
    )
    lower_axis.text(
        0,
        -0.40,
        "축 절단: 15초~48초 구간은 생략했습니다. Opt4a·Opt4b는 snapshot/read model 실험 후 되돌렸고, Opt8은 회귀를 확인했습니다.",
        transform=lower_axis.transAxes,
        ha="left",
        fontsize=8.8,
        color="#475569",
    )

    figure.savefig(
        OUTPUT_DIR / "00-full-optimization-timeline.png",
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(figure)


def main() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    configure_font()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    render_full_optimization_timeline()
    render_opt1_baseline_drilldown()
    render_phase_pair(
        filename="01-candidate-retrieval-impact.png",
        title="01. 후보 생성·추출 최적화",
        subtitle="80K 상품 / full-personalized / VUS 10 / 3분 run. Baseline과 Opt1의 비교입니다.",
        e2e_before=52.01,
        e2e_after=12.80,
        target_label="candidate_pool_ms 평균",
        target_before=2.18,
        target_after=0.87,
        target_note="내부 지표는 HTTP p95와 분리해 표시했습니다. candidate_pool_ms 평균은 60.1% 감소했습니다.",
    )
    render_phase_pair(
        filename="02-scoring-impact.png",
        title="02. 개인화 점수화 최적화",
        subtitle="80K 상품 / full-personalized / VUS 10 / 3분 run. Opt1과 Opt6의 비교입니다.",
        e2e_before=12.80,
        e2e_after=6.48,
        target_label="scoring_ms 평균",
        target_before=3.70,
        target_after=1.20,
        target_note="사전 집계 feature, bulk prefetch, coarse-to-fine ranking 적용 후 scoring_ms 평균은 67.6% 감소했습니다.",
    )
    render_phase_pair(
        filename="03-persistence-response-impact.png",
        title="03. 저장·응답 최적화",
        subtitle="80K 상품 / full-personalized / VUS 10 / 3분 run. Opt6과 Opt9의 비교입니다.",
        e2e_before=6.48,
        e2e_after=4.48,
        target_label="후보 500개 trace 저장 평균",
        target_before=0.60,
        target_after=0.00,
        target_note="후보 trace 저장을 제거한 직접 효과입니다. 이후 결과·근거 SQLAlchemy Core 저장과 화면 전용 projection query를 적용했습니다.",
    )
    render_cache_and_concurrency()
    print(f"generated={OUTPUT_DIR}")


if __name__ == "__main__":
    main()
