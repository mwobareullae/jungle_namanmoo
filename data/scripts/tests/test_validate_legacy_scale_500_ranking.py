import unittest
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_legacy_scale_500_ranking import build_summary, top3_score  # noqa: E402


class ValidateLegacyScale500RankingTest(unittest.TestCase):
    def test_top3_score_can_rank_evidence_independently_from_effect(self) -> None:
        orders = {"a": 1, "b": 2, "c": 3, "effect_only": 4}
        effect_scores = {
            "a": {"effect": 90},
            "b": {"effect": 80},
            "c": {"effect": 70},
            "effect_only": {"effect": 100},
        }
        evidence_scores = {
            "a": {"effect": 60},
            "b": {"effect": 50},
            "c": {"effect": 40},
        }

        coupled_score = top3_score(orders, effect_scores, evidence_scores, "effect")
        independent_score = top3_score(
            orders,
            evidence_scores,
            evidence_scores,
            "effect",
        )

        self.assertEqual(coupled_score, 0.425)
        self.assertEqual(independent_score, 0.95)

    def test_full_runtime_transition_is_monotonic(self) -> None:
        summary = build_summary("2026-07-14")

        self.assertEqual(summary["status"], "pass")
        self.assertEqual(
            summary["populations"]["runtime_recommendable_with_price"],
            10_164,
        )
        for axis in summary["runtime_recommendable_effect_axis_summary"]:
            self.assertEqual(axis["effect_comparison"]["worsened_count"], 0)
            self.assertEqual(axis["evidence_comparison"]["worsened_count"], 0)
            self.assertEqual(axis["combined_comparison"]["worsened_count"], 0)
            self.assertEqual(axis["combined_comparison"]["minimum_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
