"""Build curated recommendation performance graphs and case-study documents.

This renderer intentionally stays separate from analyze_benchmark_results.py.
The older script remains the exhaustive diagnostic surface; this script turns
registered, comparable runs into a focused performance narrative.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.perf import analyze_benchmark_results as legacy_analysis
from scripts.perf import recommendation_performance_report_data as report_data


PIPELINE_COMPONENTS = [
    ("user_context_load_ms", "저장 프로필"),
    ("skin_test_context_load_ms", "스킨 테스트"),
    ("behavior_context_load_ms", "행동 컨텍스트"),
    ("intent_parse_ms", "의도 분석"),
    ("run_save_ms", "실행 저장"),
    ("candidate_pool_ms", "후보 추출"),
    ("search_match_ms", "검색 매칭"),
    ("search_candidate_save_ms", "후보 저장"),
    ("scoring_ms", "개인화 스코어링"),
    ("result_save_ms", "결과 저장"),
    ("commit_ms", "커밋"),
    ("response_load_ms", "응답 조회"),
]

PIPELINE_GROUPS = [
    ("사용자 컨텍스트", ["user_context_load_ms", "skin_test_context_load_ms", "behavior_context_load_ms"]),
    ("의도 분석", ["intent_parse_ms"]),
    ("후보 검색", ["candidate_pool_ms", "search_match_ms"]),
    ("중간 저장", ["run_save_ms", "search_candidate_save_ms"]),
    ("개인화 스코어링", ["scoring_ms"]),
    ("결과 전달", ["result_save_ms", "commit_ms", "response_load_ms"]),
]

SCORING_COMPONENTS = [
    ("scoring_data_prefetch_ms", "데이터 사전 조회"),
    ("score_context_build_ms", "점수 컨텍스트"),
    ("score_loop_ms", "후보 점수 반복"),
    ("score_detail_materialization_ms", "상세 결과 구성"),
    ("score_sort_ms", "정렬"),
]

PREFETCH_COMPONENTS = [
    ("prefetch_candidate_bundle_ms", "후보 bundle load"),
    ("prefetch_product_features_ms", "상품 특징"),
    ("prefetch_effect_features_ms", "효능 특징"),
    ("prefetch_ingredient_effects_ms", "성분·효능"),
    ("prefetch_functional_info_ms", "기능성 정보"),
    ("prefetch_skin_tags_ms", "피부 태그"),
    ("prefetch_skin_profiles_ms", "피부 프로필"),
    ("prefetch_risk_flags_ms", "위험 플래그"),
    ("prefetch_market_signals_ms", "시장 신호"),
    ("prefetch_review_metrics_ms", "리뷰 지표"),
    ("prefetch_review_segments_ms", "리뷰 세그먼트"),
    ("prefetch_behavior_signals_ms", "행동 신호"),
]

METRIC_LABELS = {
    "latency_p95_ms": "End-to-end p95",
    "recommendation_rps": "처리량",
    "intent_parse_ms_p95": "의도 분석 p95",
    "candidate_pool_ms_p95": "후보 추출 p95",
    "scoring_ms_p95": "스코어링 p95",
    "scoring_data_prefetch_ms_p95": "사전 조회 p95",
    "score_loop_ms_p95": "점수 반복 p95",
    "prefetch_candidate_bundle_ms_p95": "후보 bundle load p95",
}

PIPELINE_COLORS = {
    "사용자 컨텍스트": "#4E79A7",
    "의도 분석": "#A66DD4",
    "후보 검색": "#F28E2B",
    "중간 저장": "#9C755F",
    "개인화 스코어링": "#E15759",
    "결과 전달": "#59A14F",
}

GRAPH_CONTRACT = [
    {
        "id": "scale-map",
        "question": "상품 수와 동시 사용자가 늘 때 어디서 성능이 무너지는가?",
        "metrics": "k6 recommendation p95, error rate",
        "chart": "공유 색상 범위 heatmap small multiples",
        "location": "main",
        "output": "01-scale-latency-heatmaps.png",
    },
    {
        "id": "baseline-bottleneck",
        "question": "최적화 전 평균 요청에서 가장 큰 병목은 무엇인가?",
        "metrics": "동일 대표 run의 backend pipeline stage 평균",
        "chart": "Pareto",
        "location": "main",
        "output": "02-baseline-pipeline-pareto.png",
    },
    {
        "id": "optimization-timeline",
        "question": "구현 단계를 거치며 p95와 처리량이 어떻게 변했는가?",
        "metrics": "반복 run의 k6 p95/RPS 중앙값과 개별 값",
        "chart": "상하 2단 point/line panels",
        "location": "main",
        "output": "03-optimization-timeline.png",
    },
    {
        "id": "pipeline-evolution",
        "question": "병목이 구현 단계마다 어디로 이동했는가?",
        "metrics": "각 단계 대표 run의 동일 요청계측 평균",
        "chart": "절대시간 horizontal stacked bars",
        "location": "main",
        "output": "04-pipeline-evolution.png",
    },
    {
        "id": "direct-effects",
        "question": "각 최적화가 목표 지표를 실제로 줄였는가?",
        "metrics": "공통 backend stage p95 중앙값",
        "chart": "stage-faceted dumbbell",
        "location": "main",
        "output": "05-optimization-effects.png",
    },
    {
        "id": "current-bottleneck",
        "question": "최신 측정에서 다음으로 줄일 병목은 어디인가?",
        "metrics": "최신 대표 run의 pipeline/scoring/prefetch 평균",
        "chart": "3단 nested horizontal bars",
        "location": "main",
        "output": "06-current-bottleneck-drilldown.png",
    },
    {
        "id": "repeat-stability",
        "question": "개선 결과가 반복 실행에서도 유지되고 실패를 숨기지 않았는가?",
        "metrics": "개별 p95, 중앙값, min/max, error rate",
        "chart": "strip/range and error panels",
        "location": "main",
        "output": "07-repeat-stability.png",
    },
    {
        "id": "resource-guardrails",
        "question": "지연 개선 중 CPU와 메모리가 위험하게 증가하지 않았는가?",
        "metrics": "대표 run의 backend CPU/memory p95",
        "chart": "small-multiple bars",
        "location": "appendix",
        "output": "resource-guardrails.png",
    },
    {
        "id": "run-coverage",
        "question": "각 구현 단계에서 어떤 dataset/VUS 조건을 측정했고 오류 기준을 통과했는가?",
        "metrics": "완료 run 수와 error gate 통과 run 수",
        "chart": "annotated heatmap",
        "location": "appendix",
        "output": "run-coverage.png",
    },
    {
        "id": "opt1-request-distribution",
        "question": "ES retrieval 전환으로 의도 분석과 후보 추출의 요청별 분포가 어떻게 바뀌었는가?",
        "metrics": "backend 원시 요청의 intent/candidate latency",
        "chart": "ECDF small multiples",
        "location": "details/opt1-es-retrieval",
        "output": "backend-latency-ecdf.png",
    },
    {
        "id": "opt2-request-distribution",
        "question": "사전 계산 후 scoring 하위 단계의 요청별 분포가 어떻게 이동했는가?",
        "metrics": "backend 원시 요청의 scoring/prefetch/loop latency",
        "chart": "ECDF small multiples",
        "location": "details/opt2-precomputed-features",
        "output": "scoring-latency-ecdf.png",
    },
    {
        "id": "opt2-stage-effect",
        "question": "사전 계산이 목표 scoring 단계 p95를 직접 줄였는가?",
        "metrics": "반복 run의 scoring 하위 stage p95 중앙값",
        "chart": "dumbbell",
        "location": "details/opt2-precomputed-features",
        "output": "scoring-p95-breakdown.png",
    },
    {
        "id": "opt3-request-distribution",
        "question": "후보 점수 데이터 통합 조회로 scoring 하위 단계의 요청별 분포가 어떻게 바뀌었는가?",
        "metrics": "backend 요청별 scoring/prefetch/loop latency",
        "chart": "ECDF small multiples",
        "location": "details/opt3-bulk-prefetch",
        "output": "scoring-latency-ecdf.png",
    },
    {
        "id": "opt3-stage-effect",
        "question": "bulk prefetch가 scoring 하위 단계 p95를 직접 줄였는가?",
        "metrics": "반복 run의 scoring 하위 stage p95 중앙값",
        "chart": "dumbbell",
        "location": "details/opt3-bulk-prefetch",
        "output": "scoring-p95-breakdown.png",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate curated recommendation performance report artifacts."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("scripts/perf/recommendation-performance-report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/performance/results/recommendation"),
    )
    parser.add_argument(
        "--main-doc",
        type=Path,
        default=Path("docs/performance/recommendation-performance-case-study.md"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    registry_path = args.registry if args.registry.is_absolute() else repo_root / args.registry
    output_root = args.output if args.output.is_absolute() else repo_root / args.output
    main_doc = args.main_doc if args.main_doc.is_absolute() else repo_root / args.main_doc

    registry = report_data.load_registry(repo_root, registry_path)
    rows = report_data.collect_report_rows(repo_root, registry)
    if not rows:
        raise SystemExit("No registered or loose recommendation benchmark runs found")

    paths = prepare_output_paths(output_root)
    write_normalized_outputs(repo_root, registry_path, registry, rows, paths)

    pd, plt, sns = load_plot_dependencies()
    configure_theme(plt, sns)
    graph_outputs = generate_graphs(repo_root, registry, rows, paths, pd, plt, sns)
    write_case_study(main_doc, registry, rows, graph_outputs, output_root)
    write_stage_details(registry, rows, graph_outputs, output_root)

    print(f"run_catalog={paths['data'] / 'run_catalog.csv'}")
    print(f"comparability={paths['data'] / 'comparability.csv'}")
    print(f"graphs={output_root}")
    print(f"case_study={main_doc}")


def prepare_output_paths(output_root: Path) -> dict[str, Path]:
    paths = {
        "root": output_root,
        "main": output_root / "main",
        "details": output_root / "details",
        "appendix": output_root / "appendix",
        "data": output_root / "data",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def write_normalized_outputs(
    repo_root: Path,
    registry_path: Path,
    registry: dict[str, Any],
    rows: list[dict[str, Any]],
    paths: dict[str, Path],
) -> None:
    report_data.write_csv_rows(
        paths["data"] / "run_catalog.csv",
        [{key: row.get(key) for key in report_data.CATALOG_COLUMNS} for row in rows],
        report_data.CATALOG_COLUMNS,
    )
    report_data.write_csv_rows(
        paths["data"] / "comparability.csv",
        [{key: row.get(key) for key in report_data.COMPARABILITY_COLUMNS} for row in rows],
        report_data.COMPARABILITY_COLUMNS,
    )
    report_data.write_csv_rows(
        paths["data"] / "normalized_summary.csv",
        [report_data.public_metrics_row(row) for row in rows],
        report_data.PREFERRED_SUMMARY_COLUMNS,
    )
    report_data.write_csv_rows(
        paths["data"] / "graph-contract.csv",
        GRAPH_CONTRACT,
        ["id", "question", "metrics", "chart", "location", "output"],
    )

    provenance = build_provenance(repo_root, registry_path, registry, rows)
    report_data.write_json(paths["data"] / "provenance.json", provenance)


def build_provenance(
    repo_root: Path,
    registry_path: Path,
    registry: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    stages = []
    for stage in sorted(registry["stages"], key=lambda item: item["order"]):
        target = target_rows(rows, stage["id"], eligible_only=True)
        fallback = target_rows(rows, stage["id"], eligible_only=False)
        representative = report_data.representative_row(target or fallback)
        stages.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "status": stage["status"],
                "compared_to": stage.get("compared_to"),
                "registered_run_count": sum(
                    row["implementation_stage"] == stage["id"] for row in rows
                ),
                "headline_eligible_run_ids": [row["run_id"] for row in target],
                "representative_run_id": representative.get("run_id") if representative else None,
            }
        )

    return {
        "schema_version": 1,
        "generator": "scripts/perf/generate_recommendation_performance_report.py",
        "registry": report_data.relative_posix(repo_root, registry_path),
        "registry_sha256": report_data.sha256_file(registry_path),
        "comparison": registry["comparison"],
        "stages": stages,
        "sources": [
            {
                "run_id": row["run_id"],
                "implementation_stage": row["implementation_stage"],
                "run_dir": row["run_dir"],
                "manifest_sha256": row.get("manifest_sha256"),
                "k6_summary_sha256": row.get("k6_summary_sha256"),
                "backend_log_sha256": row.get("backend_log_sha256"),
                "resource_log_sha256": row.get("resource_log_sha256"),
                "headline_eligible": row["headline_eligible"],
                "exclusion_reason": row["exclusion_reason"],
            }
            for row in rows
        ],
        "limitations": [
            "manifest git_sha is unknown in the collected benchmark runs",
            "baseline 80000/VUS10 exceeds the 1% error gate and is problem evidence only",
            "Opt2 has target-condition repeats but no complete dataset-by-VUS matrix",
            "top-level loose runs stay unassigned until implementation evidence is registered",
        ],
    }


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


def configure_theme(plt, sns) -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Malgun Gothic",
                "Noto Sans CJK KR",
                "NanumGothic",
                "AppleGothic",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.titleweight": "bold",
            "axes.titlesize": 15,
            "axes.labelsize": 11,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def generate_graphs(repo_root, registry, rows, paths, pd, plt, sns) -> dict[str, str]:
    outputs: dict[str, str] = {}
    outputs["scale"] = save_scale_heatmaps(registry, rows, paths["main"], pd, plt, sns)
    outputs["baseline"] = save_baseline_pareto(registry, rows, paths["main"], plt)
    outputs["timeline"] = save_optimization_timeline(registry, rows, paths["main"], plt)
    outputs["pipeline"] = save_pipeline_evolution(registry, rows, paths["main"], plt)
    outputs["effects"] = save_optimization_effects(registry, rows, paths["main"], plt)
    outputs["bottleneck"] = save_current_bottleneck(registry, rows, paths["main"], plt)
    outputs["stability"] = save_repeat_stability(registry, rows, paths["main"], plt)
    outputs["resources"] = save_resource_guardrails(registry, rows, paths["appendix"], plt)
    outputs["coverage"] = save_run_coverage(registry, rows, paths["appendix"], pd, plt, sns)
    outputs.update(save_stage_detail_graphs(repo_root, registry, rows, paths["details"], plt))
    return outputs


def save_scale_heatmaps(registry, rows, output_dir, pd, plt, sns) -> str:
    datasets = [1000, 5000, 10000, 80000]
    vus_values = [1, 3, 5, 8, 10]
    complete_stages = []
    for stage in measured_stages(registry):
        stage_rows_all = [
            row for row in rows
            if row["implementation_stage"] == stage["id"] and row["complete"]
        ]
        cells = {(int(row["dataset"]), int(row["vus"])) for row in stage_rows_all}
        if all((dataset, vus) in cells for dataset in datasets for vus in vus_values):
            complete_stages.append(stage)

    if not complete_stages:
        raise ValueError("No implementation stage has a complete dataset-by-VUS matrix")
    selected = [complete_stages[0]]
    if complete_stages[-1]["id"] != complete_stages[0]["id"]:
        selected.append(complete_stages[-1])

    medians: dict[tuple[str, int, int], float] = {}
    failure_cells: set[tuple[str, int, int]] = set()
    for stage in selected:
        for dataset in datasets:
            for vus in vus_values:
                cell = [
                    row for row in rows
                    if row["implementation_stage"] == stage["id"]
                    and row["complete"]
                    and int(row["dataset"]) == dataset
                    and int(row["vus"]) == vus
                ]
                value = report_data.median_metric(cell, "latency_p95_ms")
                if value is not None:
                    medians[(stage["id"], dataset, vus)] = value / 1000
                if any(not row["error_gate_passed"] for row in cell):
                    failure_cells.add((stage["id"], dataset, vus))

    vmax = max(medians.values())
    fig, axes = plt.subplots(1, len(selected), figsize=(7.2 * len(selected), 5.8), squeeze=False)
    for axis, stage in zip(axes[0], selected):
        matrix = pd.DataFrame(
            [
                [medians.get((stage["id"], dataset, vus), math.nan) for vus in vus_values]
                for dataset in datasets
            ],
            index=["1천", "5천", "1만", "79,952"],
            columns=[f"VUS {vus}" for vus in vus_values],
        )
        annotations = matrix.copy().astype(object)
        for row_index, dataset in enumerate(datasets):
            for column_index, vus in enumerate(vus_values):
                value = matrix.iloc[row_index, column_index]
                suffix = "\nFAIL" if (stage["id"], dataset, vus) in failure_cells else ""
                annotations.iloc[row_index, column_index] = (
                    "-" if math.isnan(value) else f"{value:.2f}s{suffix}"
                )
        sns.heatmap(
            matrix,
            ax=axis,
            annot=annotations,
            fmt="",
            cmap="YlOrRd",
            vmin=0,
            vmax=vmax,
            linewidths=1,
            linecolor="white",
            cbar=axis is axes[0][-1],
            cbar_kws={"label": "클라이언트 p95 (초)"},
        )
        axis.set_title(stage["label"])
        axis.set_xlabel("동시 사용자")
        axis.set_ylabel("상품 수" if axis is axes[0][0] else "")
    fig.suptitle("8만 상품과 높은 동시성에서 응답 지연이 급격히 증가했다", y=1.02)
    add_footer(
        fig,
        "target=1천/5천/1만/8만(actual 79,952) · VUS=1/3/5/8/10 · 3m · full-personalized · query=all · cold · repeat=1/cell · source=k6 · FAIL=오류율 1% 초과",
    )
    path = output_dir / "01-scale-latency-heatmaps.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_baseline_pareto(registry, rows, output_dir, plt) -> str:
    baseline = measured_stages(registry)[0]
    candidates = target_rows(rows, baseline["id"], eligible_only=False)
    representative = report_data.representative_row(candidates)
    if representative is None:
        raise ValueError("Baseline target run is unavailable")

    records = []
    for key, label in PIPELINE_COMPONENTS:
        value = value_of(representative, f"{key}_avg")
        if value is not None and value > 0:
            records.append((label, value))
    records.sort(key=lambda item: item[1], reverse=True)
    total = sum(value for _, value in records)
    cumulative = []
    running = 0.0
    for _, value in records:
        running += value
        cumulative.append(running / total * 100 if total else 0)

    fig, axis = plt.subplots(figsize=(12, 6.8))
    labels = [label for label, _ in records]
    values = [value / 1000 for _, value in records]
    bars = axis.bar(range(len(records)), values, color="#6B7280", width=0.72)
    axis.set_xticks(range(len(records)), labels, rotation=30, ha="right")
    axis.set_ylabel("대표 run 단계별 평균 (초)")
    axis.set_ylim(bottom=0)
    for bar, value in zip(bars, values):
        axis.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.2f}s", ha="center", va="bottom", fontsize=9)
    cumulative_axis = axis.twinx()
    cumulative_axis.plot(range(len(records)), cumulative, color="#B91C1C", marker="o", linewidth=2)
    cumulative_axis.set_ylabel("계측 단계 누적 비율 (%)")
    cumulative_axis.set_ylim(0, 105)
    top_names = "·".join(label for label, _ in records[:2])
    axis.set_title(f"Baseline 평균 지연의 중심은 {top_names}였다")
    add_footer(
        fig,
        f"target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=1 · source=backend events · "
        f"오류율 {float(representative.get('error_rate') or 0) * 100:.2f}%로 개선율 기준에서는 제외",
    )
    path = output_dir / "02-baseline-pipeline-pareto.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_optimization_timeline(registry, rows, output_dir, plt) -> str:
    stages = measured_stages(registry)
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.6), sharex=True)
    valid_medians: list[tuple[int, float, float]] = []
    for index, stage in enumerate(stages):
        eligible = target_rows(rows, stage["id"], eligible_only=True)
        evidence = target_rows(rows, stage["id"], eligible_only=False)
        plotted = eligible or evidence
        if not plotted:
            continue
        invalid = not bool(eligible)
        color = stage["color"]
        for offset, row in enumerate(plotted):
            jitter = (offset - (len(plotted) - 1) / 2) * 0.06
            marker = "x" if not row["error_gate_passed"] else "o"
            axes[0].scatter(index + jitter, float(row["latency_p95_ms"]) / 1000, color=color, marker=marker, s=55, zorder=3)
            axes[1].scatter(index + jitter, float(row["recommendation_rps"]), color=color, marker=marker, s=55, zorder=3)
        p95 = report_data.median_metric(plotted, "latency_p95_ms")
        rps = report_data.median_metric(plotted, "recommendation_rps")
        if p95 is None or rps is None:
            continue
        axes[0].scatter(index, p95 / 1000, color=color, edgecolor="white", linewidth=1.5, s=150, zorder=4)
        axes[1].scatter(index, rps, color=color, edgecolor="white", linewidth=1.5, s=150, zorder=4)
        axes[0].annotate(
            f"중앙값 {p95 / 1000:.2f}s",
            (index, p95 / 1000),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
        )
        axes[1].annotate(
            f"중앙값 {rps:.2f}",
            (index, rps),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
        )
        if invalid:
            axes[0].annotate(
                "오류 기준 초과",
                (index, p95 / 1000),
                xytext=(0, -18),
                textcoords="offset points",
                ha="center",
                va="top",
                color="#B91C1C",
                fontsize=9,
            )
        else:
            valid_medians.append((index, p95 / 1000, rps))

    if len(valid_medians) >= 2:
        axes[0].plot([item[0] for item in valid_medians], [item[1] for item in valid_medians], color="#374151", linewidth=1.5)
        axes[1].plot([item[0] for item in valid_medians], [item[2] for item in valid_medians], color="#374151", linewidth=1.5)
    axes[0].set_ylabel("클라이언트 p95 (초)")
    axes[1].set_ylabel("추천 처리량 (RPS)")
    axes[1].set_xticks(range(len(stages)), [stage["label"] for stage in stages], rotation=12)
    for axis in axes:
        axis.set_ylim(bottom=0)
    axes[0].set_title("구조 최적화가 진행되며 p95는 낮아지고 처리량은 증가했다")
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=1/3/3 · source=k6 · 큰 점=중앙값 · x=오류율 1% 초과",
    )
    path = output_dir / "03-optimization-timeline.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_pipeline_evolution(registry, rows, output_dir, plt) -> str:
    stage_records = []
    for stage in measured_stages(registry):
        eligible = target_rows(rows, stage["id"], eligible_only=True)
        evidence = target_rows(rows, stage["id"], eligible_only=False)
        representative = report_data.representative_row(eligible or evidence)
        if representative is None:
            continue
        group_values = {
            label: sum(value_of(representative, f"{key}_avg") or 0 for key in keys)
            for label, keys in PIPELINE_GROUPS
        }
        stage_records.append((stage, representative, group_values, bool(eligible)))

    fig, axis = plt.subplots(figsize=(12, 6.6))
    y_positions = list(range(len(stage_records)))
    left = [0.0] * len(stage_records)
    for label, _ in PIPELINE_GROUPS:
        values = [record[2][label] / 1000 for record in stage_records]
        bars = axis.barh(y_positions, values, left=left, color=PIPELINE_COLORS[label], label=label, height=0.62)
        for index, (bar, value) in enumerate(zip(bars, values)):
            total = sum(stage_records[index][2].values()) / 1000
            if value > max(total * 0.18, 1.0):
                axis.text(left[index] + value / 2, index, f"{value:.2f}s", ha="center", va="center", color="white", fontsize=9)
        left = [current + value for current, value in zip(left, values)]

    for index, (_, representative, _, eligible) in enumerate(stage_records):
        axis.text(left[index] + max(left) * 0.015, index, f"계측 합계 {left[index]:.2f}s", va="center", fontsize=9)
        if not eligible:
            axis.text(0, index - 0.36, "오류 기준 초과 run", color="#B91C1C", fontsize=8)
    axis.set_yticks(y_positions, [record[0]["label"] for record in stage_records])
    axis.invert_yaxis()
    axis.set_xlim(left=0)
    axis.set_xlabel("동일 대표 run의 단계별 평균 절대시간 합계 (초)")
    axis.set_title("최적화가 진행될수록 병목의 중심이 다른 단계로 이동했다")
    axis.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.28), frameon=False)
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=대표 run 1/stage · source=backend events · 평균 단계값만 누적",
    )
    path = output_dir / "04-pipeline-evolution.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_optimization_effects(registry, rows, output_dir, plt) -> str:
    stages_by_id = {stage["id"]: stage for stage in registry["stages"]}
    comparisons = []
    for stage in measured_stages(registry):
        parent_id = stage.get("compared_to")
        if not parent_id or parent_id not in stages_by_id:
            continue
        parent = stages_by_id[parent_id]
        parent_eligible = target_rows(rows, parent_id, eligible_only=True)
        parent_evidence = target_rows(rows, parent_id, eligible_only=False)
        child_rows = target_rows(rows, stage["id"], eligible_only=True)
        if not child_rows or not (parent_eligible or parent_evidence):
            continue
        metrics = []
        for metric in stage.get("focus_metrics", []):
            before = report_data.median_metric(parent_eligible or parent_evidence, metric)
            after = report_data.median_metric(child_rows, metric)
            if before is not None and after is not None:
                metrics.append((metric, before, after))
        if metrics:
            comparisons.append((parent, stage, metrics, bool(parent_eligible)))

    fig, axes = plt.subplots(len(comparisons), 1, figsize=(12, max(4.2, 3.8 * len(comparisons))), squeeze=False)
    for axis, (parent, stage, metrics, parent_valid) in zip(axes[:, 0], comparisons):
        y_positions = list(range(len(metrics)))
        for y, (metric, before, after) in zip(y_positions, metrics):
            axis.plot([before / 1000, after / 1000], [y, y], color="#CBD5E1", linewidth=3, zorder=1)
            axis.scatter(before / 1000, y, color=parent["color"], s=95, label=parent["label"] if y == 0 else None, zorder=2)
            axis.scatter(after / 1000, y, color=stage["color"], s=95, label=stage["label"] if y == 0 else None, zorder=2)
            delta = (before - after) / before * 100 if before else 0
            suffix = f"{delta:+.1f}%" if parent_valid else "참고 비교"
            axis.text(max(before, after) / 1000, y + 0.18, suffix, ha="right", fontsize=9)
        axis.set_yticks(y_positions, [METRIC_LABELS.get(metric, metric) for metric, _, _ in metrics])
        axis.invert_yaxis()
        axis.set_xlim(left=0)
        axis.set_xlabel("독립 stage p95 (초)")
        axis.set_title(f"{parent['label']} → {stage['label']}: {stage['change']}", loc="left", fontsize=12)
        axis.legend(frameon=False, loc="lower right")
        if not parent_valid:
            axis.text(0.99, 0.95, "이전 단계가 오류 기준을 초과해 개선율 확정에 사용하지 않음", transform=axis.transAxes, ha="right", va="top", color="#B91C1C", fontsize=8)
    fig.suptitle("각 구조 변경은 목표로 삼은 backend 병목을 직접 줄였다", y=1.01)
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=1/3/3 · source=backend events · 각 stage p95는 독립 계산",
    )
    path = output_dir / "05-optimization-effects.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_current_bottleneck(registry, rows, output_dir, plt) -> str:
    latest = latest_measured_stage_with_data(registry, rows)
    eligible = target_rows(rows, latest["id"], eligible_only=True)
    representative = report_data.representative_row(eligible)
    if representative is None:
        raise ValueError("Latest measured stage has no eligible target run")

    pipeline = [(label, sum(value_of(representative, f"{key}_avg") or 0 for key in keys)) for label, keys in PIPELINE_GROUPS]
    scoring = component_values(representative, SCORING_COMPONENTS, "avg")
    prefetch = component_values(representative, PREFETCH_COMPONENTS, "avg")
    panels = [
        ("전체 파이프라인", pipeline, PIPELINE_COLORS),
        ("Scoring 내부", scoring, None),
        ("Prefetch 내부", group_small_components(prefetch, 7), None),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(17, 6.8))
    for axis, (title, values, color_map) in zip(axes, panels):
        values = sorted([(label, value) for label, value in values if value > 0], key=lambda item: item[1])
        labels = [label for label, _ in values]
        seconds = [value / 1000 for _, value in values]
        colors = [color_map.get(label, "#64748B") for label in labels] if color_map else ["#64748B"] * len(labels)
        bars = axis.barh(labels, seconds, color=colors)
        axis.set_xlim(left=0)
        axis.set_xlabel("평균 시간 (초)")
        axis.set_title(title)
        for bar, value in zip(bars, seconds):
            axis.text(value, bar.get_y() + bar.get_height() / 2, f" {value:.2f}s", va="center", fontsize=9)
    scoring_top = max(scoring, key=lambda item: item[1])[0] if scoring else "scoring"
    fig.suptitle(f"{latest['label']}의 다음 분석 지점은 {scoring_top}이다", y=1.02)
    add_footer(
        fig,
        f"target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=대표 run {representative['run_id']} · source=backend events · 패널별 축 독립",
    )
    path = output_dir / "06-current-bottleneck-drilldown.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_repeat_stability(registry, rows, output_dir, plt) -> str:
    stages = measured_stages(registry)
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    for index, stage in enumerate(stages):
        evidence = target_rows(rows, stage["id"], eligible_only=False)
        if not evidence:
            continue
        p95_values = [float(row["latency_p95_ms"]) / 1000 for row in evidence]
        errors = [float(row.get("error_rate") or 0) * 100 for row in evidence]
        for offset, (value, row) in enumerate(zip(p95_values, evidence)):
            jitter = (offset - (len(evidence) - 1) / 2) * 0.06
            marker = "o" if row["error_gate_passed"] else "x"
            axes[0].scatter(index + jitter, value, color=stage["color"], marker=marker, s=65, zorder=3)
        median = statistics.median(p95_values)
        axes[0].vlines(index, min(p95_values), max(p95_values), color=stage["color"], linewidth=3, alpha=0.65)
        axes[0].scatter(index, median, color=stage["color"], edgecolor="white", linewidth=1.5, s=145, zorder=4)
        axes[0].text(index, max(p95_values), f"n={len(p95_values)}\n중앙값 {median:.2f}s", ha="center", va="bottom", fontsize=9)
        axes[1].bar(index, max(errors), color=stage["color"], width=0.58)
        axes[1].text(index, max(errors), f"{max(errors):.2f}%", ha="center", va="bottom", fontsize=9)
    axes[0].set_ylabel("클라이언트 p95 (초)")
    axes[0].set_ylim(bottom=0)
    axes[0].set_title("대표값과 함께 개별 run을 공개해 반복 편차를 숨기지 않았다")
    axes[1].axhline(float(registry["comparison"]["max_error_rate"]) * 100, color="#B91C1C", linestyle="--", linewidth=1.2, label="오류 기준")
    axes[1].set_ylabel("최대 오류율 (%)")
    axes[1].set_ylim(bottom=0)
    axes[1].set_xticks(range(len(stages)), [stage["label"] for stage in stages], rotation=12)
    axes[1].legend(frameon=False, loc="upper right")
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=1/3/3 · source=k6 · 범위=min~max · 큰 점=중앙값",
    )
    path = output_dir / "07-repeat-stability.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_resource_guardrails(registry, rows, output_dir, plt) -> str:
    records = []
    for stage in measured_stages(registry):
        target = target_rows(rows, stage["id"], eligible_only=True) or target_rows(rows, stage["id"], eligible_only=False)
        representative = report_data.representative_row(target)
        if representative and representative.get("resource_data_available"):
            records.append((stage, representative))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    labels = [stage["label"] for stage, _ in records]
    colors = [stage["color"] for stage, _ in records]
    cpu = [value_of(row, "resource_backend_cpu_percent_p95") or 0 for _, row in records]
    memory = [value_of(row, "resource_backend_mem_used_mib_p95") or 0 for _, row in records]
    for axis, values, title, ylabel in (
        (axes[0], cpu, "Backend CPU p95", "CPU (%)"),
        (axes[1], memory, "Backend memory p95", "Memory (MiB)"),
    ):
        bars = axis.bar(labels, values, color=colors)
        axis.set_ylim(bottom=0)
        axis.set_ylabel(ylabel)
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=15)
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.1f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("응답 개선과 함께 서버 자원 사용량을 guardrail로 확인했다", y=1.02)
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=대표 run 1/stage · source=docker stats · 인과가 아닌 guardrail",
    )
    path = output_dir / "resource-guardrails.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_run_coverage(registry, rows, output_dir, pd, plt, sns) -> str:
    datasets = [1000, 5000, 10000, 80000]
    vus_values = [1, 3, 5, 8, 10]
    stages = measured_stages(registry)
    labels = [f"{dataset}/{vus}" for dataset in datasets for vus in vus_values]
    values = []
    annotations = []
    for stage in stages:
        value_row = []
        annotation_row = []
        for dataset in datasets:
            for vus in vus_values:
                cell = [
                    row for row in rows
                    if row["implementation_stage"] == stage["id"]
                    and row["complete"]
                    and int(row["dataset"]) == dataset
                    and int(row["vus"]) == vus
                ]
                valid = sum(bool(row["error_gate_passed"]) for row in cell)
                value_row.append(valid)
                annotation_row.append(f"{valid}/{len(cell)}" if cell else "-")
        values.append(value_row)
        annotations.append(annotation_row)
    frame = pd.DataFrame(values, index=[stage["label"] for stage in stages], columns=labels)
    fig, axis = plt.subplots(figsize=(17, max(3.5, len(stages) * 1.1)))
    sns.heatmap(frame, annot=annotations, fmt="", cmap="Blues", vmin=0, linewidths=0.5, cbar_kws={"label": "오류 기준 통과 run 수"}, ax=axis)
    axis.set_xlabel("dataset / VUS")
    axis.set_ylabel("")
    axis.set_title("단계별 측정 커버리지와 오류 기준 통과 run 수")
    add_footer(
        fig,
        "target=1천/5천/1만/8만(actual 79,952) · VUS=1/3/5/8/10 · 3m · full-personalized · query=all · cold · source=manifest+comparability",
    )
    path = output_dir / "run-coverage.png"
    save_figure(fig, path, plt)
    return path.as_posix()


def save_stage_detail_graphs(repo_root, registry, rows, details_root, plt) -> dict[str, str]:
    outputs: dict[str, str] = {}
    stage_map = {stage["id"]: stage for stage in registry["stages"]}
    if "baseline-v1" in stage_map and "opt1-es-retrieval" in stage_map:
        output = details_root / "opt1-es-retrieval" / "backend-latency-ecdf.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        save_backend_ecdf(
            repo_root,
            rows,
            stage_map["baseline-v1"],
            stage_map["opt1-es-retrieval"],
            [("intent_parse_ms", "의도 분석"), ("candidate_pool_ms", "후보 추출")],
            output,
            plt,
        )
        outputs["opt1_ecdf"] = output.as_posix()
    for stage in measured_stages(registry):
        stage_id = stage["id"]
        if stage_id == "opt1-es-retrieval" or not stage.get("compared_to"):
            continue
        parent = stage_map.get(stage["compared_to"])
        if parent is None:
            continue
        output = details_root / stage_id / "scoring-latency-ecdf.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        save_backend_ecdf(
            repo_root,
            rows,
            parent,
            stage,
            [
                ("scoring_ms", "전체 scoring"),
                ("scoring_data_prefetch_ms", "데이터 사전 조회"),
                ("score_loop_ms", "점수 반복"),
            ],
            output,
            plt,
        )
        outputs[f"{stage_id}_scoring_ecdf"] = output.as_posix()
        breakdown = details_root / stage_id / "scoring-p95-breakdown.png"
        save_component_before_after(
            rows,
            parent,
            stage,
            SCORING_COMPONENTS,
            breakdown,
            plt,
        )
        outputs[f"{stage_id}_scoring_breakdown"] = breakdown.as_posix()
    return outputs


def save_backend_ecdf(repo_root, rows, before_stage, after_stage, metrics, output, plt) -> None:
    before_rows = target_rows(rows, before_stage["id"], eligible_only=True) or target_rows(rows, before_stage["id"], eligible_only=False)
    after_rows = target_rows(rows, after_stage["id"], eligible_only=True)
    before = report_data.representative_row(before_rows)
    after = report_data.representative_row(after_rows)
    if before is None or after is None:
        return
    events = {
        before_stage["label"]: legacy_analysis.load_pipeline_events(repo_root / before["run_dir"] / "backend" / "backend.log"),
        after_stage["label"]: legacy_analysis.load_pipeline_events(repo_root / after["run_dir"] / "backend" / "backend.log"),
    }
    colors = {before_stage["label"]: before_stage["color"], after_stage["label"]: after_stage["color"]}
    fig, axes = plt.subplots(1, len(metrics), figsize=(6 * len(metrics), 4.8), squeeze=False)
    for axis, (metric, title) in zip(axes[0], metrics):
        for label, stage_events in events.items():
            values = sorted(
                float(event[metric]) / 1000
                for event in stage_events
                if isinstance(event.get(metric), (int, float))
            )
            if not values:
                continue
            y = [(index + 1) / len(values) for index in range(len(values))]
            axis.step(values, y, where="post", color=colors[label], label=f"{label} (n={len(values)})", linewidth=2)
        axis.set_xlabel("Backend 단계 시간 (초)")
        axis.set_ylabel("누적 요청 비율" if axis is axes[0][0] else "")
        axis.set_xlim(left=0)
        axis.set_ylim(0, 1.01)
        axis.set_title(title)
        axis.legend(frameon=False)
    fig.suptitle(f"{before_stage['label']} → {after_stage['label']} 요청별 지연 분포", y=1.02)
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=대표 run 1/stage · source=backend raw request events · client latency와 구분",
    )
    save_figure(fig, output, plt)


def save_component_before_after(rows, before_stage, after_stage, components, output, plt) -> None:
    before_rows = target_rows(rows, before_stage["id"], eligible_only=True) or target_rows(rows, before_stage["id"], eligible_only=False)
    after_rows = target_rows(rows, after_stage["id"], eligible_only=True)
    records = []
    for key, label in components:
        metric = f"{key}_p95"
        before = report_data.median_metric(before_rows, metric)
        after = report_data.median_metric(after_rows, metric)
        if before is not None and after is not None:
            records.append((label, before / 1000, after / 1000))
    fig, axis = plt.subplots(figsize=(10.5, max(4.5, len(records) * 0.8)))
    for y, (label, before, after) in enumerate(records):
        axis.plot([before, after], [y, y], color="#CBD5E1", linewidth=3)
        axis.scatter(before, y, color=before_stage["color"], s=100, label=before_stage["label"] if y == 0 else None)
        axis.scatter(after, y, color=after_stage["color"], s=100, label=after_stage["label"] if y == 0 else None)
        axis.text(max(before, after), y + 0.18, f"{(before - after) / before * 100:+.1f}%", ha="right", fontsize=9)
    axis.set_yticks(range(len(records)), [record[0] for record in records])
    axis.invert_yaxis()
    axis.set_xlim(left=0)
    axis.set_xlabel("독립 stage p95 (초)")
    axis.set_title("사전 계산 적용 후 scoring 하위 단계가 함께 감소했다")
    axis.legend(frameon=False)
    add_footer(
        fig,
        "target=8만(actual 79,952) · VUS10 · 3m · full-personalized · query=all · cold · repeat=3/stage · source=backend events · stage p95 중앙값",
    )
    save_figure(fig, output, plt)


def write_case_study(main_doc, registry, rows, outputs, output_root) -> None:
    stages = measured_stages(registry)
    latest = latest_measured_stage_with_data(registry, rows)
    stage_map = {stage["id"]: stage for stage in registry["stages"]}
    parent = stage_map.get(latest.get("compared_to"))
    latest_rows = target_rows(rows, latest["id"], eligible_only=True)
    parent_rows = target_rows(rows, parent["id"], eligible_only=True) if parent else []
    comparison_rows = build_metric_comparison(parent_rows, latest_rows)
    baseline = stages[0]
    baseline_evidence = target_rows(rows, baseline["id"], eligible_only=False)
    baseline_error = report_data.median_metric(baseline_evidence, "error_rate") or 0
    stage_summary_lines: list[str] = []
    for stage in stages[1:]:
        detail_doc = Path(stage["detail_doc"]).name
        stage_summary_lines.extend(
            [
                f"### {stage['label']}",
                "",
                f"{stage['change']}. {stage.get('tradeoff', '')} 설계 근거는 [{stage['label']} 상세 설계](./{detail_doc}), 측정 근거는 [{stage['label']} 결과](./results/recommendation/details/{stage['id']}/README.md)에 정리했다.",
                "",
            ]
        )

    lines = [
        "<!-- Generated by scripts/perf/generate_recommendation_performance_report.py. -->",
        "# 8만 상품 개인화 추천 파이프라인 성능 최적화",
        "",
        "79,952개 상품을 대상으로 저장 프로필, 스킨 테스트, 행동, 리뷰를 함께 계산하는 추천 요청을 계측하고 병목을 구조적으로 제거한 기록이다.",
        "",
        "## 한눈에 보는 결과",
        "",
        f"아래 값은 `{parent['label'] if parent else '-'} → {latest['label']}`의 동일 조건 반복 run 중앙값이다.",
        "",
        "| 지표 | 이전 | 이후 | 변화 |",
        "|---|---:|---:|---:|",
    ]
    for label, before, after, change, unit in comparison_rows:
        lines.append(f"| {label} | {format_value(before, unit)} | {format_value(after, unit)} | {change} |")
    lines.extend(
        [
            "",
            "> Baseline 8만/VUS10 실행은 오류율 기준을 초과했다. 성능 붕괴를 보여주는 문제 재현 자료로만 사용하며 확정 개선율 계산에서는 제외한다.",
            "",
            "## 문제와 측정 기준",
            "",
            "상품 수와 동시 사용자를 함께 늘렸을 때 어느 구간에서 추천이 무너지는지 확인하고, client p95와 backend 단계 계측을 분리해 병목을 찾았다.",
            "",
            f"- 기준: `{registry['comparison']['actual_product_count']:,}`개 상품, `{registry['comparison']['user_type']}`, VUS `{registry['comparison']['vus']}`, `{registry['comparison']['duration']}`, `{registry['comparison']['cache_state']}` cache",
            f"- 오류 gate: `{float(registry['comparison']['max_error_rate']) * 100:.0f}%` 이하",
            "- client latency: k6 recommendation trend",
            "- backend latency: `recommendation_pipeline_completed` 단계 계측",
            "- 상세 환경: [벤치마크 환경](./benchmark-environment.md), [실행 방법](./benchmark-run.md)",
            "",
            "![상품 수와 VUS별 성능 지형](./results/recommendation/main/01-scale-latency-heatmaps.png)",
            "",
            "## Baseline에서 확인한 최초 병목",
            "",
            f"Baseline 8만/VUS10의 오류율은 `{baseline_error * 100:.2f}%`였다. 아래 Pareto는 성공 요청의 평균 단계 시간으로 병목 위치를 설명하며, 실패 요청을 숨긴 성공 지표로 사용하지 않는다.",
            "",
            "![Baseline 파이프라인 Pareto](./results/recommendation/main/02-baseline-pipeline-pareto.png)",
            "",
            "## 최적화 타임라인",
            "",
            "구현 단계는 발견된 병목 이름이 아니라 해당 run에서 적용된 코드 변경을 뜻한다. 병목은 매 단계의 전체 계측값에서 다시 발견한다.",
            "",
            "![최적화 타임라인](./results/recommendation/main/03-optimization-timeline.png)",
            "",
            "![파이프라인 병목 이동](./results/recommendation/main/04-pipeline-evolution.png)",
            "",
            "## 단계별 기술 선택과 직접 효과",
            "",
            *stage_summary_lines,
            "![최적화별 목표 지표 변화](./results/recommendation/main/05-optimization-effects.png)",
            "",
            "## 현재 병목과 다음 최적화",
            "",
            "최신 단계에서도 전체 시간이 사라진 것은 아니다. 아래 확대 그래프는 동일 대표 run의 평균값을 사용해 다음 조사 대상을 보여준다.",
            "",
            "![현재 병목 확대](./results/recommendation/main/06-current-bottleneck-drilldown.png)",
            "",
            "다음 구현 단계인 bulk prefetch는 후보 점수 데이터의 순차 조회를 통합하는 작업이다. 아직 registry에 검증된 측정 run이 없으므로 결과를 0이나 예상치로 그리지 않는다. 설계는 [Opt3 bulk prefetch](./recommendation-bulk-prefetch.md)에 기록한다.",
            "",
            "## 반복 안정성과 한계",
            "",
            "![반복 실행 안정성](./results/recommendation/main/07-repeat-stability.png)",
            "",
            "자원 사용량과 run 수집 범위는 메인 결론과 분리해 [resource guardrail](./results/recommendation/appendix/resource-guardrails.png), [run coverage](./results/recommendation/appendix/run-coverage.png)에서 확인한다.",
            "",
            "- Baseline target run은 오류 gate를 넘었으므로 문제 재현 전용이다.",
            "- Opt2는 8만/VUS10 반복 측정만 있어 상품 수×VUS 전체 matrix 비교에는 포함하지 않았다.",
            "- 수집 manifest의 `git_sha`가 `unknown`이라 구현 단계 배치는 registry와 측정 문서 근거로 관리한다.",
            "- 최상위 loose run은 구현 단계가 증명될 때까지 `unassigned`로 남긴다.",
            "- CPU와 메모리는 인과 지표가 아니라 과부하 여부를 확인하는 guardrail로만 사용한다.",
            "",
            "## 재현",
            "",
            "```powershell",
            "python scripts/perf/generate_recommendation_performance_report.py",
            "```",
            "",
            "새 최적화 단계는 `scripts/perf/recommendation-performance-report.json`에 구현 변경, 비교 대상, 입력 run 경로와 상세 문서를 등록한 뒤 같은 명령을 다시 실행한다. 계측만 바뀐 run은 새 단계로 만들지 않고 로그 필드에 따라 `measurement_schema`만 자동 분류한다.",
            "",
            "입력 run, 제외 사유, 대표 run과 원본 해시는 [provenance.json](./results/recommendation/data/provenance.json), [comparability.csv](./results/recommendation/data/comparability.csv)에서 확인할 수 있다.",
            "",
        ]
    )
    main_doc.parent.mkdir(parents=True, exist_ok=True)
    main_doc.write_text("\n".join(lines), encoding="utf-8")


def write_stage_details(registry, rows, outputs, output_root) -> None:
    stage_map = {stage["id"]: stage for stage in registry["stages"]}
    for stage in measured_stages(registry):
        stage_id = stage["id"]
        if not stage.get("compared_to"):
            continue
        parent = stage_map.get(stage.get("compared_to"))
        child_rows = target_rows(rows, stage_id, eligible_only=True)
        parent_rows = target_rows(rows, parent["id"], eligible_only=True) if parent else []
        parent_evidence = target_rows(rows, parent["id"], eligible_only=False) if parent else []
        if not child_rows:
            continue
        detail_dir = output_root / "details" / stage_id
        detail_dir.mkdir(parents=True, exist_ok=True)
        comparison = build_metric_comparison(parent_rows or parent_evidence, child_rows)
        parent_valid = bool(parent_rows)
        lines = [
            "<!-- Generated by scripts/perf/generate_recommendation_performance_report.py. -->",
            f"# {stage['label']} 측정 결과",
            "",
            f"## 관측과 선택",
            "",
            f"- 적용 변경: {stage['change']}",
            f"- 비교 대상: {parent['label'] if parent else '-'}",
            f"- 조건: 79,952개 / full-personalized / VUS10 / 3분 / cold cache",
            f"- 상세 설계: [문서 보기](../../../../{Path(stage['detail_doc']).name})",
            "",
            "## 관측",
            "",
            stage.get("observation", "측정 결과에서 병목을 관측했다."),
            "",
            "## 원인",
            "",
            stage.get("cause", "상세 설계 문서에서 원인을 다룬다."),
            "",
            "## 검토한 대안",
            "",
            stage.get("alternatives", "상세 설계 문서에서 대안을 다룬다."),
            "",
            "## 기술 선택과 트레이드오프",
            "",
            stage.get("tradeoff", "상세 설계 문서에서 트레이드오프를 다룬다."),
            "",
            "## 구현 구조",
            "",
            stage.get("implementation", stage["change"]),
            "",
            "## 동일 조건 결과",
            "",
            "| 지표 | 이전 | 이후 | 변화 |",
            "|---|---:|---:|---:|",
        ]
        for label, before, after, change, unit in comparison:
            lines.append(f"| {label} | {format_value(before, unit)} | {format_value(after, unit)} | {change if parent_valid else '참고 비교'} |")
        if not parent_valid:
            lines.extend(["", "> 이전 단계가 오류 gate를 초과해 확정 개선율로 사용하지 않는다."])
        lines.extend(["", "## 요청별 분포", ""])
        if stage_id == "opt1-es-retrieval":
            lines.extend(
                [
                    "![의도 분석과 후보 추출 ECDF](./backend-latency-ecdf.png)",
                    "",
                    "```mermaid",
                    "flowchart LR",
                    "  A[사용자 고민] --> B[Python 브랜드 alias 전수 검사]",
                    "  B --> C[후보 조건 생성]",
                    "  C --> D[Elasticsearch 후보 추출]",
                    "  A -. Opt1 .-> E[경량 의미 구조화]",
                    "  E --> F[Elasticsearch field boost 후보 추출]",
                    "  F --> G[개인화 scoring]",
                    "```",
                ]
            )
        elif stage_id == "opt2-precomputed-features":
            lines.extend(
                [
                    "![Scoring 하위 단계 ECDF](./scoring-latency-ecdf.png)",
                    "",
                    "![Scoring p95 전후 비교](./scoring-p95-breakdown.png)",
                    "",
                    "```mermaid",
                    "flowchart LR",
                    "  A[추천 요청] --> B[상품 성분·효능 반복 계산]",
                    "  A --> C[행동 로그 반복 집계]",
                    "  B --> D[Scoring]",
                    "  C --> D",
                    "  E[배치 rollup] --> F[상품 feature read model]",
                    "  E --> G[사용자 preference profile]",
                    "  A -. Opt2 .-> F",
                    "  A -. Opt2 .-> G",
                    "  F --> H[Scoring]",
                    "  G --> H",
                    "```",
                ]
            )
        elif stage_id == "opt3-bulk-prefetch":
            lines.extend(
                [
                    "![Scoring 하위 단계 ECDF](./scoring-latency-ecdf.png)",
                    "",
                    "![Scoring p95 전후 비교](./scoring-p95-breakdown.png)",
                    "",
                    "```mermaid",
                    "flowchart LR",
                    "  A[추천 후보 ID 묶음] --> B1[성분·효능 loader]",
                    "  A --> B2[피부·리뷰 loader]",
                    "  A --> B3[행동·가격 loader]",
                    "  B1 --> C[Python 결과 조립]",
                    "  B2 --> C",
                    "  B3 --> C",
                    "  A -. Opt3 .-> D[단일 bulk JOIN 조회]",
                    "  D --> E[후보별 점수 입력 bundle]",
                    "  E --> F[기존 점수식]",
                    "```",
                ]
            )
        else:
            lines.extend(
                [
                    "![Scoring 하위 단계 ECDF](./scoring-latency-ecdf.png)",
                    "",
                    "![Scoring p95 전후 비교](./scoring-p95-breakdown.png)",
                ]
            )
        lines.extend(
            [
                "",
                "## 효과와 새로 드러난 병목",
                "",
                stage.get("next_bottleneck", "다음 병목은 후속 측정에서 확인한다."),
                "",
                "## 해석 범위",
                "",
                "- ECDF는 backend 완료 이벤트의 요청별 표본이며 client end-to-end 분포가 아니다.",
                "- 단계 p95는 각각 독립적으로 계산하며 합산하지 않는다.",
                "- 대표 수치는 반복 run 중앙값이고 개별 값은 메인 안정성 그래프와 normalized CSV에 남긴다.",
                "",
            ]
        )
        (detail_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def measured_stages(registry) -> list[dict[str, Any]]:
    return sorted(
        [stage for stage in registry["stages"] if stage.get("status") == "measured"],
        key=lambda stage: stage["order"],
    )


def target_rows(rows, stage_id, *, eligible_only) -> list[dict[str, Any]]:
    result = [
        row for row in rows
        if row["implementation_stage"] == stage_id and row["condition_matches"] and row["complete"]
    ]
    if eligible_only:
        result = [row for row in result if row["headline_eligible"]]
    return sorted(result, key=report_data.row_sort_key)


def latest_measured_stage_with_data(registry, rows) -> dict[str, Any]:
    candidates = [
        stage for stage in measured_stages(registry)
        if target_rows(rows, stage["id"], eligible_only=True)
    ]
    if not candidates:
        raise ValueError("No measured stage has eligible target-condition runs")
    return candidates[-1]


def component_values(row, components, statistic) -> list[tuple[str, float]]:
    values = []
    for key, label in components:
        value = value_of(row, f"{key}_{statistic}")
        if value is not None and value > 0:
            values.append((label, value))
    return values


def group_small_components(values: list[tuple[str, float]], limit: int) -> list[tuple[str, float]]:
    ordered = sorted(values, key=lambda item: item[1], reverse=True)
    if len(ordered) <= limit:
        return ordered
    kept = ordered[: limit - 1]
    kept.append(("기타", sum(value for _, value in ordered[limit - 1 :])))
    return kept


def build_metric_comparison(before_rows, after_rows):
    metrics = [
        ("End-to-end p95", "latency_p95_ms", "ms", "decrease"),
        ("처리량", "recommendation_rps", "rps", "increase"),
        ("Scoring p95", "scoring_ms_p95", "ms", "decrease"),
        ("오류율", "error_rate", "rate", "decrease"),
    ]
    result = []
    for label, metric, unit, direction in metrics:
        before = report_data.median_metric(before_rows, metric)
        after = report_data.median_metric(after_rows, metric)
        if before is None or after is None:
            continue
        if before == 0:
            change = "유지" if after == 0 else "비교 불가"
        else:
            raw = (after - before) / before * 100
            if direction == "decrease":
                raw = -raw
            change = f"{raw:+.1f}%"
        result.append((label, before, after, change, unit))
    return result


def format_value(value: float, unit: str) -> str:
    if unit == "ms":
        return f"{value / 1000:.2f}초" if value >= 1000 else f"{value:.0f}ms"
    if unit == "rps":
        return f"{value:.2f} RPS"
    if unit == "rate":
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def value_of(row: dict[str, Any], key: str) -> float | None:
    return report_data.numeric_or_none(row.get(key))


def add_footer(fig, text: str) -> None:
    fig.text(0.5, 0.005, text, ha="center", va="bottom", fontsize=8.5, color="#475569")


def save_figure(fig, path: Path, plt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.045, 1, 0.97))
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
