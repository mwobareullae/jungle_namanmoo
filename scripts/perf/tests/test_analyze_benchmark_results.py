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
