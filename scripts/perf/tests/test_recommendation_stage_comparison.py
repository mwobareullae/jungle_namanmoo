from __future__ import annotations

import unittest

from scripts.perf import generate_recommendation_stage_comparison as comparison


class RecommendationStageComparisonTests(unittest.TestCase):
    def test_baseline_problem_evidence_is_kept_but_failed_optimized_run_is_removed(self) -> None:
        rows = [
            self._row("baseline-v1", "baseline", error_gate_passed=False),
            self._row("opt1-es-retrieval", "opt1-failed", error_gate_passed=False),
            self._row("opt1-es-retrieval", "opt1-valid", error_gate_passed=True),
        ]

        selected = comparison.select_comparable_rows(rows)

        self.assertEqual([row["run_id"] for row in selected["baseline-v1"]], ["baseline"])
        self.assertEqual(
            [row["run_id"] for row in selected["opt1-es-retrieval"]],
            ["opt1-valid"],
        )

    def test_opt3_requires_bulk_prefetch_measurement_schema(self) -> None:
        stage_rows = {
            stage_id: [self._row(stage_id, stage_id)]
            for stage_id in comparison.STAGE_IDS
        }
        stage_rows["opt3-bulk-prefetch"][0]["measurement_schema"] = "scoring-detail-v3"

        with self.assertRaisesRegex(SystemExit, "bulk-prefetch-v4"):
            comparison.validate_stage_rows(stage_rows)

    def test_transition_rows_report_exact_latency_and_throughput_changes(self) -> None:
        summaries = [
            self._summary("baseline-v1", p95=52_000.0, avg=37_000.0, backend_p95=50_000.0, rps=0.25),
            self._summary("opt1-es-retrieval", p95=13_000.0, avg=9_000.0, backend_p95=12_000.0, rps=1.0),
            self._summary("opt2-precomputed-features", p95=8_000.0, avg=6_000.0, backend_p95=7_000.0, rps=1.5),
            self._summary("opt3-bulk-prefetch", p95=7_500.0, avg=5_700.0, backend_p95=6_800.0, rps=1.65),
        ]

        transitions = comparison.build_transition_rows(summaries)

        self.assertEqual(transitions[0]["e2e_p95_reduction_ms"], 39_000.0)
        self.assertEqual(transitions[1]["e2e_avg_reduction_ms"], 3_000.0)
        self.assertAlmostEqual(transitions[2]["e2e_p95_reduction_pct"], 6.25)
        self.assertAlmostEqual(transitions[2]["rps_gain_pct"], 10.0)

    def test_pipeline_markdown_keeps_regression_sign(self) -> None:
        metrics = []
        deltas = []
        for component, label in comparison.PIPELINE_COMPONENTS:
            for stage_index, stage_id in enumerate(comparison.STAGE_IDS):
                metrics.append(
                    {
                        "stage_id": stage_id,
                        "component": component,
                        "component_label": label,
                        "avg_ms": 100.0 - stage_index * 10.0,
                    }
                )
            for optimization, reduction in (("Opt1", 10.0), ("Opt2", 10.0), ("Opt3", -5.0)):
                deltas.append(
                    {
                        "optimization": optimization,
                        "component": component,
                        "avg_reduction_ms": reduction,
                    }
                )

        markdown_rows = comparison.build_pipeline_markdown_rows(metrics, deltas)

        self.assertEqual(len(markdown_rows), len(comparison.PIPELINE_COMPONENTS))
        self.assertIn("-5.00 ms", markdown_rows[0])
        self.assertIn("+30.00 ms", markdown_rows[0])

    @staticmethod
    def _row(
        stage_id: str,
        run_id: str,
        *,
        error_gate_passed: bool = True,
    ) -> dict[str, object]:
        return {
            "implementation_stage": stage_id,
            "run_id": run_id,
            "complete": True,
            "condition_matches": True,
            "error_gate_passed": error_gate_passed,
            "measurement_schema": "bulk-prefetch-v4",
            "started_at": "2026-07-15T00:00:00+09:00",
        }

    @staticmethod
    def _summary(
        stage_id: str,
        *,
        p95: float,
        avg: float,
        backend_p95: float,
        rps: float,
    ) -> dict[str, object]:
        return {
            "stage_id": stage_id,
            "latency_p95_ms": p95,
            "latency_avg_ms": avg,
            "duration_ms_p95": backend_p95,
            "recommendation_rps": rps,
        }


if __name__ == "__main__":
    unittest.main()
