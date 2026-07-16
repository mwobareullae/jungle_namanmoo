from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.perf import analyze_benchmark_results as analysis


class BenchmarkMetricExtractionTests(unittest.TestCase):
    def test_recommendation_rps_excludes_setup_login_requests(self) -> None:
        summary = {
            "metrics": {
                "http_req_duration{type:recommendation}": {
                    "avg": 100.0,
                    "med": 90.0,
                    "p(90)": 140.0,
                    "p(95)": 150.0,
                    "max": 200.0,
                },
                "http_reqs": {"count": 60, "rate": 0.3},
                "iterations": {"count": 50, "rate": 0.25},
                "http_req_failed": {"value": 1 / 60, "passes": 1, "fails": 59},
                "checks": {"value": 0.98, "passes": 98, "fails": 2},
            }
        }

        result = analysis.extract_k6_metrics(summary)

        self.assertEqual(result["rps"], 0.25)
        self.assertEqual(result["recommendation_request_count"], 50)
        self.assertEqual(result["total_http_request_count"], 60)
        self.assertEqual(result["auth_request_count"], 10)
        self.assertEqual(result["http_failed_count"], 1)
        self.assertEqual(result["recommendation_http_failed_rate"], 0.02)
        self.assertEqual(result["check_failed_rate"], 0.02)

    def test_pipeline_breakdown_includes_context_and_run_save(self) -> None:
        stage_keys = [key for key, _ in analysis.PIPELINE_STAGES]
        self.assertIn("user_context_load_ms", stage_keys)
        self.assertIn("skin_test_context_load_ms", stage_keys)
        self.assertIn("behavior_context_load_ms", stage_keys)
        self.assertIn("run_save_ms", stage_keys)

        row = {
            f"{key}_avg": float(index)
            for index, (key, _) in enumerate(analysis.PIPELINE_STAGES, start=1)
        }
        records = analysis.build_stage_records(
            row,
            analysis.PIPELINE_STAGES,
            statistic="avg",
        )
        self.assertEqual(len(records), len(analysis.PIPELINE_STAGES))

    def test_stage_breakdown_selects_requested_statistic(self) -> None:
        row = {
            "intent_parse_ms_avg": 120.0,
            "intent_parse_ms_p95": 240.0,
        }
        stages = [("intent_parse_ms", "intent")]

        average = analysis.build_stage_records(row, stages, statistic="avg")
        p95 = analysis.build_stage_records(row, stages, statistic="p95")

        self.assertEqual(average[0]["value"], 120.0)
        self.assertEqual(p95[0]["value"], 240.0)

    def test_representative_row_uses_headline_median_p95(self) -> None:
        rows = [
            {"run_id": "headline-low", "dataset": 80000, "vus": 10, "latency_p95_ms": 7000.0},
            {"run_id": "headline-mid", "dataset": 80000, "vus": 10, "latency_p95_ms": 7400.0},
            {"run_id": "headline-high", "dataset": 80000, "vus": 10, "latency_p95_ms": 7900.0},
            {"run_id": "later-outlier", "dataset": 80000, "vus": 10, "latency_p95_ms": 12000.0},
        ]

        selected = analysis.representative_analysis_row(
            rows,
            dataset=80000,
            vus=10,
            preferred_run_ids=["headline-low", "headline-mid", "headline-high"],
        )

        self.assertEqual(selected["run_id"], "headline-mid")

    def test_execution_flow_records_preserve_parent_residuals(self) -> None:
        row = {
            "run_id": "run-1",
            "latency_avg_ms": 100.0,
            "duration_ms_avg": 80.0,
            "intent_parse_ms_avg": 20.0,
            "scoring_ms_avg": 30.0,
            "scoring_data_prefetch_ms_avg": 10.0,
            "score_loop_ms_avg": 10.0,
        }

        records = analysis.build_execution_flow_records(row)
        http_children = analysis.execution_flow_children(records, "end_to_end")
        pipeline_children = analysis.execution_flow_children(records, "backend_pipeline")

        self.assertAlmostEqual(sum(item["value_ms"] for item in http_children), 100.0)
        self.assertAlmostEqual(sum(item["value_ms"] for item in pipeline_children), 80.0)
        outside = next(item for item in http_children if item["component_id"] == "outside_pipeline")
        residual = next(
            item
            for item in pipeline_children
            if item["source_metric"] == "derived_parent_minus_children"
        )
        self.assertEqual(outside["value_ms"], 20.0)
        self.assertEqual(residual["value_ms"], 30.0)
        self.assertEqual(outside["e2e_share_percent"], 20.0)

    def test_execution_flow_adds_snapshot_load_without_overlapping_fallback(self) -> None:
        row = {
            "run_id": "opt4-run",
            "latency_avg_ms": 200.0,
            "duration_ms_avg": 180.0,
            "scoring_ms_avg": 120.0,
            "scoring_data_prefetch_ms_avg": 100.0,
            "prefetch_snapshot_load_ms_avg": 40.0,
            "prefetch_candidate_bundle_ms_avg": 20.0,
            "prefetch_effect_features_ms_avg": 10.0,
            "scoring_snapshot_fallback_ms_avg": 60.0,
        }

        records = analysis.build_execution_flow_records(row)
        prefetch_children = analysis.execution_flow_children(
            records,
            "scoring_data_prefetch_ms",
        )
        child_ids = {record["component_id"] for record in prefetch_children}

        self.assertIn("prefetch_snapshot_load_ms", child_ids)
        self.assertNotIn("scoring_snapshot_fallback_ms", child_ids)
        self.assertAlmostEqual(
            sum(record["value_ms"] for record in prefetch_children),
            100.0,
        )

    def test_snapshot_read_model_metrics_calculate_coverage(self) -> None:
        row = {
            "run_id": "opt4-run",
            "scoring_snapshot_load_ms_avg": 120.0,
            "scoring_snapshot_load_ms_p95": 180.0,
            "scoring_snapshot_fallback_ms_avg": 12.0,
            "scoring_snapshot_fallback_ms_p95": 20.0,
            "scoring_snapshot_hit_count_avg": 495.0,
            "scoring_snapshot_miss_count_avg": 5.0,
            "scoring_snapshot_parse_error_count_avg": 1.0,
            "scoring_snapshot_parse_error_count_p95": 2.0,
        }

        metrics = analysis.build_snapshot_read_model_metrics(row)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["snapshot_candidate_count_avg"], 500.0)
        self.assertEqual(metrics["snapshot_hit_rate"], 0.99)
        self.assertEqual(metrics["snapshot_miss_rate"], 0.01)
        self.assertEqual(metrics["snapshot_parse_error_count_p95"], 2.0)
        markdown = "\n".join(analysis.snapshot_read_model_markdown(metrics))
        self.assertIn("snapshot hit rate: **99.00%**", markdown)
        self.assertIn("다시 더하지 않는다", markdown)

    def test_snapshot_read_model_metrics_require_snapshot_instrumentation(self) -> None:
        self.assertIsNone(
            analysis.build_snapshot_read_model_metrics(
                {"scoring_data_prefetch_ms_avg": 100.0}
            )
        )

    def test_scoring_drilldown_lists_materialization_and_full_loop(self) -> None:
        scoring_keys = [key for key, _ in analysis.SCORING_STAGES]
        loop_keys = [key for key, _ in analysis.SCORE_LOOP_DETAIL_STAGES]

        self.assertIn("score_detail_materialization_ms", scoring_keys)
        self.assertIn("score_loop_contribution_build_ms", loop_keys)
        self.assertIn("score_loop_functional_axis_ms", loop_keys)
        self.assertIn("score_loop_search_price_market_axis_ms", loop_keys)
        self.assertIn("score_loop_final_score_ms", loop_keys)

    def test_grouped_stage_shares_keep_total_and_limit_segments(self) -> None:
        stages = [
            ("stage_a", "A"),
            ("stage_b", "B"),
            ("stage_c", "C"),
            ("stage_d", "D"),
            ("stage_e", "E"),
        ]
        row = {
            "stage_a_avg": 70.0,
            "stage_b_avg": 20.0,
            "stage_c_avg": 5.0,
            "stage_d_avg": 3.0,
            "stage_e_avg": 2.0,
        }

        records = analysis.build_grouped_share_records(
            row,
            stages,
            statistic="avg",
            max_segments=3,
            min_share_percent=4.0,
        )

        self.assertEqual([record["stage"] for record in records], ["A", "B", "other (3 stages)"])
        self.assertEqual(sum(record["value"] for record in records), 100.0)
        self.assertEqual(sum(record["share_percent"] for record in records), 100.0)

    def test_intent_detail_records_break_down_llm_without_double_counting(self) -> None:
        row = {
            "intent_parse_ms_avg": 1000.0,
            "intent_repository_load_ms_avg": 10.0,
            "intent_rule_parse_ms_avg": 20.0,
            "intent_llm_call_ms_avg": 300.0,
            "intent_llm_prompt_load_ms_avg": 1.0,
            "intent_llm_schema_load_ms_avg": 2.0,
            "intent_llm_request_build_ms_avg": 3.0,
            "intent_llm_http_ms_avg": 280.0,
            "intent_llm_response_parse_ms_avg": 4.0,
            "intent_llm_schema_validate_ms_avg": 5.0,
            "intent_llm_merge_ms_avg": 6.0,
            "intent_purchase_parse_ms_avg": 600.0,
        }

        records = analysis.build_intent_detail_records(row, statistic="avg")

        values = {record["stage"]: record["value"] for record in records}
        self.assertEqual(values["LLM HTTP wait"], 280.0)
        self.assertEqual(values["LLM other"], 5.0)
        self.assertEqual(values["intent other"], 64.0)
        self.assertAlmostEqual(sum(values.values()), 1000.0)

    def test_purchase_parser_detail_records_break_down_internal_timings(self) -> None:
        row = {
            "intent_purchase_parse_ms_avg": 1000.0,
            "intent_purchase_normalize_ms_avg": 1.0,
            "intent_purchase_price_ms_avg": 2.0,
            "intent_purchase_category_ms_avg": 7.0,
            "intent_purchase_brand_alias_load_ms_avg": 390.0,
            "intent_purchase_brand_match_ms_avg": 590.0,
        }

        records = analysis.build_purchase_parser_detail_records(row, statistic="avg")

        values = {record["stage"]: record["value"] for record in records}
        self.assertEqual(values["normalize"], 1.0)
        self.assertEqual(values["price"], 2.0)
        self.assertEqual(values["category"], 7.0)
        self.assertEqual(values["brand alias load"], 390.0)
        self.assertEqual(values["brand match"], 590.0)
        self.assertEqual(values["purchase other"], 10.0)
        self.assertAlmostEqual(sum(values.values()), 1000.0)

    def test_intent_diagnostics_include_outcomes_and_ai_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "backend.log"
            events = [
                {
                    "event": "recommendation_pipeline_completed",
                    "intent_llm_attempted": True,
                    "intent_llm_http_attempted": True,
                    "intent_llm_used": False,
                    "intent_rule_needs_llm": True,
                    "intent_llm_outcome": "timeout",
                    "intent_llm_http_ms": 20000.0,
                },
                {
                    "event": "recommendation_pipeline_completed",
                    "intent_llm_attempted": False,
                    "intent_llm_http_attempted": False,
                    "intent_llm_used": False,
                    "intent_rule_needs_llm": False,
                    "intent_llm_outcome": "not_needed",
                    "intent_llm_http_ms": 0.0,
                },
                {
                    "event": "ai_call_failed",
                    "operation": "concern_parser",
                    "duration_ms": 20001.0,
                    "error": "timeout",
                },
            ]
            path.write_text(
                "\n".join(json.dumps(event) for event in events),
                encoding="utf-8",
            )

            result = analysis.extract_backend_metrics(path)

        self.assertEqual(result["intent_llm_attempted_true_count"], 1)
        self.assertEqual(result["intent_llm_attempted_true_rate"], 0.5)
        self.assertEqual(result["intent_llm_outcome_timeout_count"], 1)
        self.assertEqual(result["intent_llm_outcome_not_needed_count"], 1)
        self.assertEqual(result["intent_ai_call_event_count"], 1)
        self.assertEqual(result["intent_ai_call_failed_rate"], 1.0)
        self.assertEqual(result["intent_ai_call_duration_ms_avg"], 20001.0)


class BenchmarkResourceParsingTests(unittest.TestCase):
    def test_resource_timeseries_uses_elapsed_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "docker-stats.csv"
            path.write_text(
                "timestamp,name,cpu_percent,mem_usage,mem_percent\n"
                "2026-07-13T20:34:46+00:00,mwobareullae-backend,100%,1GiB / 2GiB,50%\n"
                "2026-07-13T20:34:49+00:00,mwobareullae-elasticsearch,20%,1GiB / 2GiB,50%\n",
                encoding="utf-8",
            )

            records = analysis.load_resource_timeseries_records(path)

        self.assertEqual([record["elapsed_seconds"] for record in records], [0.0, 3.0])
        self.assertEqual([record["service"] for record in records], ["backend", "elasticsearch"])


if __name__ == "__main__":
    unittest.main()
