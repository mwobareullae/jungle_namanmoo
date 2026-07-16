from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.perf import generate_recommendation_performance_report as renderer
from scripts.perf import recommendation_performance_report_data as report_data


COMPARISON = {
    "dataset": 80000,
    "actual_product_count": 79952,
    "vus": 10,
    "duration": "3m",
    "user_type": "full-personalized",
    "query_id": "all",
    "cache_state": "cold",
    "max_error_rate": 0.01,
}

MEASURED_STAGE = {
    "id": "opt2-precomputed-features",
    "label": "Opt2 precomputed features",
    "order": 2,
    "color": "#0F766E",
    "status": "measured",
}


class PerformanceReportDataTests(unittest.TestCase):
    def test_supplemental_run_roots_are_collected_without_stage_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_dir = repo_root / "perf-runs" / "sweeps" / "opt3" / "recommendation-test"
            run_dir.mkdir(parents=True)
            registry = {
                "stages": [],
                "comparison": {},
                "loose_run_root": "perf-runs",
                "supplemental_run_roots": ["perf-runs/sweeps"],
            }

            with (
                mock.patch.object(
                    report_data.legacy_analysis,
                    "find_run_dirs",
                    return_value=[run_dir],
                ),
                mock.patch.object(
                    report_data,
                    "build_report_row",
                    return_value={
                        "run_id": "recommendation-test",
                        "implementation_stage": "unassigned",
                    },
                ) as build_row,
            ):
                rows = report_data.collect_report_rows(repo_root, registry)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["implementation_stage"], "unassigned")
        self.assertIsNone(build_row.call_args.args[2])

    def test_implementation_stage_is_independent_from_measurement_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_dir, k6_path = self._make_run(repo_root)
            parsed = self._parsed_row(
                product_feature_load_ms_avg=12.0,
                prefetch_candidate_bundle_ms_avg=4.0,
            )

            with (
                mock.patch.object(report_data.legacy_analysis, "find_k6_summary", return_value=k6_path),
                mock.patch.object(report_data.legacy_analysis, "build_run_row", return_value=parsed),
            ):
                row = report_data.build_report_row(
                    repo_root,
                    run_dir,
                    MEASURED_STAGE,
                    COMPARISON,
                )

        self.assertEqual(row["implementation_stage"], "opt2-precomputed-features")
        self.assertEqual(row["measurement_schema"], "bulk-prefetch-v4")
        self.assertTrue(row["headline_eligible"])

    def test_incomplete_or_unassigned_run_is_excluded_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_dir, k6_path = self._make_run(repo_root, k6_result_present=False)
            with (
                mock.patch.object(report_data.legacy_analysis, "find_k6_summary", return_value=k6_path),
                mock.patch.object(
                    report_data.legacy_analysis,
                    "build_run_row",
                    return_value=self._parsed_row(),
                ),
            ):
                row = report_data.build_report_row(
                    repo_root,
                    run_dir,
                    None,
                    COMPARISON,
                )

        self.assertFalse(row["headline_eligible"])
        self.assertIn("unassigned_stage", row["exclusion_reason"])
        self.assertIn("incomplete_run", row["exclusion_reason"])

    def test_error_gate_rejects_fast_but_failing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_dir, k6_path = self._make_run(repo_root)
            parsed = self._parsed_row(
                recommendation_http_failed_rate=0.02,
                check_failed_rate=0.0,
            )
            with (
                mock.patch.object(report_data.legacy_analysis, "find_k6_summary", return_value=k6_path),
                mock.patch.object(report_data.legacy_analysis, "build_run_row", return_value=parsed),
            ):
                row = report_data.build_report_row(
                    repo_root,
                    run_dir,
                    MEASURED_STAGE,
                    COMPARISON,
                )

        self.assertFalse(row["error_gate_passed"])
        self.assertFalse(row["headline_eligible"])
        self.assertTrue(row["problem_evidence_eligible"])
        self.assertIn("error_rate_exceeds_0.01", row["exclusion_reason"])

    def test_representative_run_uses_median_and_missing_stays_unavailable(self) -> None:
        rows = [
            {"run_id": "slow", "latency_p95_ms": 300.0},
            {"run_id": "fast", "latency_p95_ms": 100.0},
            {"run_id": "middle", "latency_p95_ms": 200.0},
        ]

        representative = report_data.representative_row(rows)

        self.assertEqual(representative["run_id"], "middle")
        self.assertEqual(report_data.median_metric(rows, "missing_metric"), None)
        self.assertEqual(report_data.median_metric([{"metric": ""}], "metric"), None)

    def test_measurement_schema_uses_available_fields_only(self) -> None:
        self.assertEqual(report_data.infer_measurement_schema({}), "pipeline-v1")
        self.assertEqual(
            report_data.infer_measurement_schema({"intent_purchase_brand_match_ms_avg": 0.0}),
            "intent-detail-v2",
        )
        self.assertEqual(
            report_data.infer_measurement_schema({"product_feature_load_ms_avg": 0.0}),
            "scoring-detail-v3",
        )
        self.assertEqual(
            report_data.infer_measurement_schema({"prefetch_candidate_bundle_ms_avg": 0.0}),
            "bulk-prefetch-v4",
        )

    def test_public_normalized_csv_drops_credentials_and_keeps_missing_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.csv"
            public = report_data.public_metrics_row(
                {
                    "run_id": "run-1",
                    "latency_p95_ms": None,
                    "setup_data": "sensitive payload",
                    "auth_cookie": "mwbl_session=secret",
                    "password": "secret",
                }
            )
            report_data.write_csv_rows(output, [public], ["run_id", "latency_p95_ms"])
            with output.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["run_id"], "run-1")
        self.assertEqual(row["latency_p95_ms"], "")
        self.assertNotIn("setup_data", row)
        self.assertNotIn("auth_cookie", row)
        self.assertNotIn("password", row)

    def test_new_measured_stage_gets_detail_document_without_code_branch(self) -> None:
        registry = {
            "stages": [
                {
                    "id": "baseline",
                    "label": "Baseline",
                    "order": 0,
                    "status": "measured",
                    "compared_to": None,
                },
                {
                    "id": "opt4-example",
                    "label": "Opt4 example",
                    "order": 4,
                    "status": "measured",
                    "compared_to": "baseline",
                    "change": "새 구현 적용",
                    "observation": "새 병목을 관측했다.",
                    "cause": "반복 작업이 원인이었다.",
                    "alternatives": "캐시 대안을 검토했다.",
                    "tradeoff": "최신성 관리가 필요하다.",
                    "implementation": "bulk 경로로 통합했다.",
                    "next_bottleneck": "다음 병목은 저장 구간이다.",
                    "detail_doc": "docs/performance/opt4-example.md",
                },
            ]
        }
        common = {
            "condition_matches": True,
            "complete": True,
            "headline_eligible": True,
            "error_rate": 0.0,
            "latency_p95_ms": 1000.0,
            "recommendation_rps": 1.0,
            "scoring_ms_p95": 500.0,
        }
        rows = [
            {**common, "run_id": "before", "implementation_stage": "baseline"},
            {**common, "run_id": "after", "implementation_stage": "opt4-example"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            renderer.write_stage_details(registry, rows, {}, output_root)
            detail = output_root / "stages" / "opt4-example" / "README.md"
            content = detail.read_text(encoding="utf-8")

        self.assertIn("# Opt4 example 측정 결과", content)
        self.assertIn("bulk 경로로 통합했다.", content)
        self.assertIn("다음 병목은 저장 구간이다.", content)

    def test_scoring_detail_graphs_are_generated_for_each_measured_stage(self) -> None:
        registry = {
            "stages": [
                {
                    "id": "baseline",
                    "label": "Baseline",
                    "order": 0,
                    "status": "measured",
                    "compared_to": None,
                },
                {
                    "id": "opt4-example",
                    "label": "Opt4 example",
                    "order": 4,
                    "status": "measured",
                    "compared_to": "baseline",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                mock.patch.object(renderer, "save_backend_ecdf") as save_ecdf,
                mock.patch.object(renderer, "save_component_before_after") as save_breakdown,
            ):
                outputs = renderer.save_stage_detail_graphs(
                    root,
                    registry,
                    [],
                    root / "stages",
                    mock.sentinel.plt,
                )

        self.assertTrue(
            save_ecdf.call_args.args[5].as_posix().endswith(
                "stages/opt4-example/scoring-latency-ecdf.png"
            )
        )
        self.assertTrue(
            save_breakdown.call_args.args[4].as_posix().endswith(
                "stages/opt4-example/scoring-p95-breakdown.png"
            )
        )
        self.assertIn("opt4-example_scoring_ecdf", outputs)
        self.assertIn("opt4-example_scoring_breakdown", outputs)

    def test_opt3_detail_document_uses_bulk_prefetch_flow(self) -> None:
        registry = {
            "stages": [
                {
                    "id": "opt2-precomputed-features",
                    "label": "Opt2",
                    "order": 2,
                    "status": "measured",
                    "compared_to": None,
                },
                {
                    "id": "opt3-bulk-prefetch",
                    "label": "Opt3",
                    "order": 3,
                    "status": "measured",
                    "compared_to": "opt2-precomputed-features",
                    "change": "bulk prefetch 적용",
                    "detail_doc": "docs/performance/opt3.md",
                },
            ]
        }
        common = {
            "condition_matches": True,
            "complete": True,
            "headline_eligible": True,
            "error_rate": 0.0,
            "latency_p95_ms": 1000.0,
            "recommendation_rps": 1.0,
            "scoring_ms_p95": 500.0,
        }
        rows = [
            {**common, "run_id": "before", "implementation_stage": "opt2-precomputed-features"},
            {**common, "run_id": "after", "implementation_stage": "opt3-bulk-prefetch"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            renderer.write_stage_details(registry, rows, {}, output_root)
            content = (
                output_root / "stages" / "opt3-bulk-prefetch" / "README.md"
            ).read_text(encoding="utf-8")

        self.assertIn("단일 bulk JOIN 조회", content)
        self.assertNotIn("배치 rollup", content)

    @staticmethod
    def _make_run(repo_root: Path, *, k6_result_present: bool = True) -> tuple[Path, Path]:
        run_dir = repo_root / "perf-runs" / "recommendation-test"
        (run_dir / "k6").mkdir(parents=True)
        (run_dir / "backend").mkdir()
        (run_dir / "resources").mkdir()
        manifest = {
            "run_id": "recommendation-test",
            "git_sha": "abc1234",
            "started_at": "2026-07-15T00:00:00+09:00",
            "finished_at": "2026-07-15T00:03:00+09:00",
            "k6_result_present": k6_result_present,
            "k6_exit_code": 0,
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        k6_path = run_dir / "k6" / "k6-summary.json"
        k6_path.write_text("{}", encoding="utf-8")
        (run_dir / "backend" / "backend.log").write_text("{}\n", encoding="utf-8")
        (run_dir / "resources" / "docker-stats.csv").write_text(
            "timestamp,name,cpu_percent,mem_usage,mem_percent\n",
            encoding="utf-8",
        )
        return run_dir, k6_path

    @staticmethod
    def _parsed_row(**overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "dataset": "80000",
            "product_count": 79952,
            "vus": 10,
            "duration": "3m",
            "user_type": "full-personalized",
            "query_id": "all",
            "cache_state": "cold",
            "pipeline_event_count": 10,
            "recommendation_http_failed_rate": 0.0,
            "check_failed_rate": 0.0,
            "latency_p95_ms": 1000.0,
        }
        row.update(overrides)
        return row


if __name__ == "__main__":
    unittest.main()
