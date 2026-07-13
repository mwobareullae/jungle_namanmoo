from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from simulate_business_effect_score_impact import (  # noqa: E402
    DEFAULT_INGREDIENT_EFFECT_WEIGHT,
    _scenario_summary,
    effect_component,
)


class SimulateBusinessEffectScoreImpactTests(unittest.TestCase):
    def test_uses_top_three_decay_and_caps_component(self):
        self.assertEqual(effect_component([8.0]), 0.08)
        self.assertAlmostEqual(effect_component([8.0, 8.0, 8.0]), 0.14)
        self.assertAlmostEqual(effect_component([100.0, 100.0, 100.0, 100.0]), 1.2)

    def test_runtime_guard_excludes_unapproved_candidate_scores(self):
        current = {("existing", "effect_calming"): 8.0}
        product_scores = {
            "p1": {
                "effect_calming": {
                    "existing": 8.0,
                    "candidate": 8.0,
                }
            }
        }

        guarded = _scenario_summary(
            current_scores=current,
            scenario_scores=current,
            product_scores=product_scores,
            total_products=1,
        )
        counterfactual = _scenario_summary(
            current_scores=current,
            scenario_scores={**current, ("candidate", "effect_calming"): 8.0},
            product_scores=product_scores,
            total_products=1,
        )

        self.assertEqual(DEFAULT_INGREDIENT_EFFECT_WEIGHT, 0.26)
        self.assertEqual(guarded["changed_products"], 0)
        self.assertEqual(counterfactual["changed_products"], 1)
        self.assertEqual(
            counterfactual["effect_summary"]["effect_calming"]["max_total_point_delta"],
            1.04,
        )


if __name__ == "__main__":
    unittest.main()
