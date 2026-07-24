from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from assess_ingredient_score_eligibility import (  # noqa: E402
    classify_outcome,
    is_clear_risk_penalty_candidate,
)
from discover_new_evidence import PaperMetadata  # noqa: E402
from screen_effect_review_candidates import PaperAssessment  # noqa: E402


def assessment(*, tier: int, applicability: str) -> PaperAssessment:
    return PaperAssessment(
        paper=PaperMetadata(pmid="1", title="Test paper"),
        evidence_tier=tier,
        evidence_kind="test",
        relation_scope="exact_ingredient",
        applicability=applicability,
        signal_score=1,
    )


def outcome(
    *,
    mapping_status: str,
    relation: str = "direct",
    direction: str = "positive",
    effect_ids: str = "effect_moisture_barrier",
    new_effect: str = "",
) -> dict[str, str]:
    return {
        "mapping_status": mapping_status,
        "ingredient_outcome_relation": relation,
        "direction": direction,
        "mapped_effect_ids": effect_ids,
        "new_effect_candidate": new_effect,
        "evidence_span": "The ingredient improved skin hydration.",
    }


class AssessIngredientScoreEligibilityTests(unittest.TestCase):
    def test_human_topical_positive_is_benefit_review_candidate(self):
        decision = classify_outcome(
            outcome(mapping_status="mapped_existing_effect"),
            assessment(tier=2, applicability="human_topical"),
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "benefit_score_candidate")

    def test_human_topical_null_is_zero_or_conflict_candidate(self):
        decision = classify_outcome(
            outcome(mapping_status="mapped_existing_effect", direction="null"),
            assessment(tier=3, applicability="human_topical"),
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "conflict_or_zero_candidate")

    def test_uncertain_trend_is_not_a_benefit_score_candidate(self):
        row = outcome(mapping_status="mapped_existing_effect")
        row["evidence_span"] = "The ingredient showed a trend to improve wrinkles."

        decision = classify_outcome(
            row,
            assessment(tier=1, applicability="human_topical"),
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "uncertain_effect_review")

    def test_uncertain_word_does_not_hide_a_statistically_supported_result(self):
        row = outcome(mapping_status="mapped_existing_effect")
        row["evidence_span"] = "The ingredient could improve skin redness."
        paper = PaperMetadata(
            pmid="4",
            title="Test paper",
            abstract="The active treatment reduced erythema (p < 0.05).",
        )
        paper_assessment = PaperAssessment(
            paper=paper,
            evidence_tier=2,
            evidence_kind="test",
            relation_scope="exact_ingredient",
            applicability="human_topical",
            signal_score=1,
        )

        decision = classify_outcome(row, paper_assessment)

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "benefit_score_candidate")

    def test_preclinical_mechanism_is_support_only(self):
        decision = classify_outcome(
            outcome(
                mapping_status="mechanism_only",
                relation="mechanism_context",
            ),
            assessment(tier=7, applicability="mechanistic"),
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "mechanism_support_candidate")

    def test_new_effect_waits_for_axis_approval(self):
        decision = classify_outcome(
            outcome(
                mapping_status="new_effect_candidate",
                effect_ids="",
                new_effect="wound_healing",
            ),
            assessment(tier=3, applicability="human_topical"),
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.category, "new_effect_axis_candidate")

    def test_negative_new_effect_is_not_a_positive_axis_candidate(self):
        decision = classify_outcome(
            outcome(
                mapping_status="new_effect_candidate",
                direction="null",
                effect_ids="",
                new_effect="antimicrobial_skin",
            ),
            assessment(tier=3, applicability="human_topical"),
        )

        self.assertIsNone(decision)

    def test_formulation_limited_result_is_not_score_candidate(self):
        decision = classify_outcome(
            outcome(
                mapping_status="mapped_existing_effect",
                relation="formulation_limited",
            ),
            assessment(tier=2, applicability="human_topical"),
        )

        self.assertIsNone(decision)

    def test_preclinical_direct_effect_is_not_standalone_benefit(self):
        decision = classify_outcome(
            outcome(mapping_status="mapped_existing_effect"),
            assessment(tier=7, applicability="mechanistic"),
        )

        self.assertIsNone(decision)

    def test_only_clear_human_topical_adverse_title_is_risk_candidate(self):
        adverse = PaperMetadata(
            pmid="2",
            title="Allergic contact dermatitis from propylene glycol",
        )
        generic_safety = PaperMetadata(
            pmid="3",
            title="Safety assessment of propylene glycol in cosmetics",
        )

        self.assertTrue(
            is_clear_risk_penalty_candidate(
                adverse,
                assessment(tier=4, applicability="human_topical"),
            )
        )
        self.assertFalse(
            is_clear_risk_penalty_candidate(
                generic_safety,
                assessment(tier=4, applicability="human_topical"),
            )
        )


if __name__ == "__main__":
    unittest.main()
