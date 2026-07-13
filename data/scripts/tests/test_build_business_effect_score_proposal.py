from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_business_effect_score_proposal import provisional_score  # noqa: E402


class BuildBusinessEffectScoreProposalTests(unittest.TestCase):
    def test_caps_candidate_scores_by_tier_and_applicability(self):
        self.assertEqual(
            provisional_score(
                {
                    "effect_id": "effect_calming",
                    "best_evidence_tier": "2",
                    "best_applicability": "human_topical",
                }
            ),
            (8.0, "paper_candidate_tier_2", ""),
        )
        self.assertEqual(
            provisional_score(
                {
                    "effect_id": "effect_calming",
                    "best_evidence_tier": "2",
                    "best_applicability": "combination_or_formulation",
                }
            )[0],
            0.0,
        )
        self.assertEqual(
            provisional_score(
                {
                    "effect_id": "effect_calming",
                    "best_evidence_tier": "2",
                    "best_applicability": "route_mismatch",
                }
            )[0],
            0.0,
        )
        self.assertEqual(provisional_score({"signal_strength": "high"})[0], 0.0)
        self.assertEqual(provisional_score({"signal_strength": "medium"})[0], 0.0)

    def test_brightening_requires_human_topical_tier_one_to_three(self):
        animal = provisional_score(
            {
                "effect_id": "effect_brightening",
                "best_evidence_tier": "6",
                "best_applicability": "mechanistic",
            }
        )
        clinical = provisional_score(
            {
                "effect_id": "effect_brightening",
                "best_evidence_tier": "3",
                "best_applicability": "human_topical",
            }
        )

        self.assertEqual(animal, (0.0, "screening_only_tier_6", "brightening_human_clinical_required"))
        self.assertEqual(clinical, (8.0, "paper_candidate_tier_3", ""))


if __name__ == "__main__":
    unittest.main()
