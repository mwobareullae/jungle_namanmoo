from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.agent.evaluate_agent_models import (
    AgentEvaluationProfile,
    DEFAULT_CASES_PATH,
    ROUTER_SPECIALIST_CASES_PATH,
    build_execution_plan,
    build_profile_execution_plan,
    evaluate_case_response,
    extract_trace_metrics,
    load_fixture,
    resolve_evaluation_profiles,
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

    def test_router_specialist_fixture_extends_baseline_to_thirty_cases(self) -> None:
        fixture = load_fixture(ROUTER_SPECIALIST_CASES_PATH)
        case_ids = {case["id"] for case in fixture["cases"]}

        self.assertEqual(len(fixture["cases"]), 30)
        self.assertEqual(len(case_ids), 30)
        self.assertTrue(
            {
                "pore-oily-01",
                "address-labelled-normal",
                "bulk-wishlist-rank-limit",
            }.issubset(case_ids)
        )
        self.assertEqual(
            fixture["bootstrap_request"]["concern_text"],
            "피지가 많고 모공이 넓어 고민이야",
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

    def test_profile_execution_plan_keeps_router_models_separate(self) -> None:
        profiles = resolve_evaluation_profiles(
            [],
            ["single-gpt55", "single-nano", "router-nano", "router-nano-fallback"],
        )
        plan = build_profile_execution_plan([{"id": "one"}], profiles, repeat=1)

        self.assertEqual([item["profile_id"] for item in plan], [
            "single-gpt55",
            "single-nano",
            "router-nano",
            "router-nano-fallback",
        ])
        router_headers = plan[2]["headers"]
        self.assertEqual(router_headers["X-Agent-Local-Execution-Mode"], "router_specialist")
        self.assertNotIn("X-Agent-Local-Model", router_headers)
        self.assertEqual(
            router_headers["X-Agent-Local-Router-Model"],
            "gpt-5.4-nano-2026-03-17",
        )

        custom = AgentEvaluationProfile(
            profile_id="custom-single",
            execution_mode="single",
            requested_model="test-model",
        )
        self.assertEqual(custom.request_headers()["X-Agent-Local-Model"], "test-model")

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

    def test_trace_metrics_aggregates_router_specialist_stages(self) -> None:
        metrics = extract_trace_metrics(
            {
                "route": {
                    "outcome": "succeeded",
                    "telemetry": {
                        "agent_execution_mode": "router_specialist",
                        "agent_router_route": "recommendation",
                        "agent_router_confidence": "high",
                        "agent_fallback_enabled": True,
                        "agent_fallback_used": False,
                    },
                },
                "agent": {"model": "router-nano", "model_source": "local_execution_override"},
                "agent_stages": {
                    "router": {
                        "model": "router-nano",
                        "instructions_bytes": 100,
                        "input_bytes": 200,
                        "selected_tool_count": 0,
                        "selected_tool_schema_bytes": 0,
                        "runner_attempts": [{"duration_ms": 125.0}],
                        "runner_result": {
                            "usage_breakdown": {"input_tokens": 11, "output_tokens": 2, "total_tokens": 13},
                            "cost_estimate": {"estimated_cost_usd": 0.001, "estimate_status": "estimated"},
                        },
                    },
                    "specialist": {
                        "name": "mwobarellae_recommendation_specialist",
                        "model": "specialist-nano",
                        "instructions_bytes": 300,
                        "input_bytes": 400,
                        "selected_tool_count": 1,
                        "selected_tool_schema_bytes": 500,
                        "runner_attempts": [{"duration_ms": 250.0}],
                        "runner_result": {
                            "usage_breakdown": {"input_tokens": 23, "output_tokens": 3, "total_tokens": 26},
                            "cost_estimate": {"estimated_cost_usd": 0.002, "estimate_status": "estimated"},
                        },
                    },
                },
                "timings_ms": {"route_total_ms": 500.0},
                "tool_calls": [{"tool_name": "create_recommendation"}],
            }
        )

        self.assertEqual(metrics["execution_mode"], "router_specialist")
        self.assertEqual(metrics["router_ms"], 125.0)
        self.assertEqual(metrics["specialist_ms"], 250.0)
        self.assertEqual(metrics["router_route"], "recommendation")
        self.assertEqual(metrics["specialist_tool_count"], 1)
        self.assertEqual(metrics["input_tokens"], 34)
        self.assertEqual(metrics["output_tokens"], 5)
        self.assertEqual(metrics["total_tokens"], 39)
        self.assertEqual(metrics["estimated_cost_usd"], 0.003)
        self.assertEqual(metrics["provider_model_call_count"], 2)

    def test_response_validation_accepts_expected_tool_error_and_route(self) -> None:
        case = {
            "expect": {
                "route": "bulk_wishlist",
                "tool_name": "bulk_wishlist_by_popular_ingredient",
                "error_code": "AGENT_BULK_WISHLIST_RANK_LIMIT",
                "requires_confirmation": False,
                "argument_equals": {"rank_limit": 51},
            }
        }
        response = {
            "tool_name": "bulk_wishlist_by_popular_ingredient",
            "requires_confirmation": False,
            "error": {"code": "AGENT_BULK_WISHLIST_RANK_LIMIT"},
        }
        trace = {
            "tool_calls": [
                {
                    "tool_name": "bulk_wishlist_by_popular_ingredient",
                    "resolved_arguments": {"rank_limit": 51},
                }
            ]
        }

        result = evaluate_case_response(case, response=response, trace=trace, status_code=200)

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["route_pass"])
        self.assertTrue(result["tool_pass"])
        self.assertTrue(result["safety_pass"])

    def test_response_validation_allows_expected_clarification(self) -> None:
        case = {
            "expect": {
                "route": "cart_checkout",
                "tool_name": "register_shipping_address",
                "allow_clarification": True,
            }
        }
        response = {
            "error": {"code": "AGENT_CLARIFICATION_REQUIRED"},
            "requires_confirmation": False,
        }

        result = evaluate_case_response(case, response=response, trace={}, status_code=200)

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["clarification_used"])
        self.assertTrue(result["route_pass"])
        self.assertTrue(result["tool_pass"])

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
                "provider_model_call_count": 1,
                "model_source": "local_header_override",
                "structural_pass": True,
                "constraint_pass": True,
                "route_pass": True,
                "tool_pass": True,
                "safety_pass": True,
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
        self.assertEqual(summaries[0]["provider_model_call_count"], 1)
        self.assertIn("gpt-5.5", report)
        self.assertIn("Provider model calls: 1", report)
        self.assertIn("model-summary.csv", report)


if __name__ == "__main__":
    unittest.main()
