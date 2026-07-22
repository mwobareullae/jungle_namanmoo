from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.agent.evaluate_agent_models import (
    DEFAULT_CASES_PATH,
    build_execution_plan,
    evaluate_case_response,
    extract_trace_metrics,
    load_fixture,
    _missing_trace_is_fatal,
    render_report,
    summarize_rows,
)


class AgentModelEvaluationTests(unittest.TestCase):
    def test_fixture_has_unique_17_case_ids(self) -> None:
        fixture = load_fixture(DEFAULT_CASES_PATH)

        self.assertEqual(len(fixture["cases"]), 17)
        self.assertEqual(len({case["id"] for case in fixture["cases"]}), 17)
        self.assertEqual(
            fixture["cases"][-1]["id"],
            "demo-bulk-wishlist",
        )

    def test_execution_plan_alternates_model_order_between_repeats(self) -> None:
        cases = [
            {"id": "one"},
            {"id": "two"},
        ]

        plan = build_execution_plan(cases, ["model-a", "model-b"], repeat=2)

        self.assertEqual(
            [(item["case_id"], item["model"], item["repeat"]) for item in plan],
            [
                ("one", "model-a", 1),
                ("one", "model-b", 1),
                ("two", "model-b", 1),
                ("two", "model-a", 1),
                ("one", "model-b", 2),
                ("one", "model-a", 2),
                ("two", "model-a", 2),
                ("two", "model-b", 2),
            ],
        )

    def test_response_validation_checks_tool_and_resolved_arguments(self) -> None:
        case = {
            "expect": {
                "tool_name": "refine_product_results",
                "requires_confirmation": False,
                "argument_equals": {"max_price": 30000},
                "argument_includes": {"required_ingredient_names": ["나이아신아마이드"]},
            }
        }
        response = {
            "tool_name": "refine_product_results",
            "requires_confirmation": False,
            "items": [],
        }
        trace = {
            "tool_calls": [
                {
                    "tool_name": "refine_product_results",
                    "resolved_arguments": {
                        "max_price": 30000,
                        "required_ingredient_names": ["나이아신아마이드"],
                    },
                }
            ]
        }

        result = evaluate_case_response(case, response=response, trace=trace, status_code=200)

        self.assertTrue(result["structural_pass"])
        self.assertTrue(result["constraint_pass"])
        self.assertEqual(result["status"], "passed")

    def test_response_validation_reads_filters_from_deterministic_fast_path(self) -> None:
        case = {
            "expect": {
                "tool_name": "refine_product_results",
                "requires_confirmation": False,
                "argument_equals": {"max_price": 30000},
            }
        }
        response = {
            "tool_name": "refine_product_results",
            "requires_confirmation": False,
            "ui_action": {"payload": {"filters": {"max_price": 30000}}},
        }

        result = evaluate_case_response(case, response=response, trace={"tool_calls": []}, status_code=200)

        self.assertTrue(result["structural_pass"])
        self.assertTrue(result["constraint_pass"])
        self.assertEqual(result["status"], "passed")

    def test_trace_metrics_extracts_model_cost_and_timing(self) -> None:
        metrics = extract_trace_metrics(
            {
                "agent": {
                    "model": "gpt-5.4-nano-2026-03-17",
                    "model_source": "local_header_override",
                    "instructions_bytes": 100,
                    "selected_tool_count": 2,
                    "selected_tool_schema_bytes": 200,
                    "input_bytes": 300,
                    "runner_result": {
                        "usage_breakdown": {
                            "input_tokens": 10,
                            "cached_input_tokens": 1,
                            "output_tokens": 2,
                            "reasoning_tokens": 0,
                            "total_tokens": 12,
                        },
                        "cost_estimate": {"estimated_cost_usd": 0.00001, "estimate_status": "estimated"},
                    },
                },
                "timings_ms": {"route_total_ms": 123.4, "agent_model_and_orchestration_ms": 90.1},
                "tool_calls": [{"tool_name": "create_recommendation"}],
            }
        )

        self.assertEqual(metrics["actual_model"], "gpt-5.4-nano-2026-03-17")
        self.assertTrue(metrics["model_called"])
        self.assertEqual(metrics["route_total_ms"], 123.4)
        self.assertEqual(metrics["estimated_cost_usd"], 0.00001)
        self.assertEqual(metrics["tool_call_count"], 1)

    def test_trace_metrics_marks_successful_direct_tool_path_as_not_called(self) -> None:
        metrics = extract_trace_metrics({"route": {"outcome": "succeeded"}, "agent": {}})

        self.assertFalse(metrics["model_called"])
        self.assertEqual(metrics["model_source"], "not_called")

    def test_missing_trace_is_fatal_only_for_successful_response(self) -> None:
        self.assertTrue(
            _missing_trace_is_fatal(
                {"http_status": 200, "trace_available": False},
                allow_missing_trace=False,
            )
        )
        self.assertFalse(
            _missing_trace_is_fatal(
                {"http_status": 504, "trace_available": False},
                allow_missing_trace=False,
            )
        )
        self.assertFalse(
            _missing_trace_is_fatal(
                {"http_status": None, "trace_available": False},
                allow_missing_trace=False,
            )
        )

    def test_summary_and_report_include_model_metrics(self) -> None:
        rows = [
            {
                "requested_model": "gpt-5.5",
                "group": "recommendation",
                "http_status": 200,
                "model_called": True,
                "model_source": "local_header_override",
                "structural_pass": True,
                "constraint_pass": True,
                "client_roundtrip_ms": 100.0,
                "route_total_ms": 90.0,
                "agent_model_and_orchestration_ms": 70.0,
                "agent_tool_execution_ms": 10.0,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "estimated_cost_usd": 0.001,
                "validation_status": "needs_manual_review",
                "scenario_id": "case-a",
            }
        ]

        summaries = summarize_rows(rows)
        report = render_report(
            rows=rows,
            summaries=summaries,
            manifest={
                "run_id": "unit-test",
                "configuration": {"models": ["gpt-5.5"], "repeat": 1},
            },
        )

        self.assertEqual(summaries[0]["model_called_count"], 1)
        self.assertIn("gpt-5.5", report)
        self.assertIn("model-summary.csv", report)


if __name__ == "__main__":
    unittest.main()
