from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from effect_direction_dictionary import (  # noqa: E402
    DIRECTION_POLICY_VERSION,
    EFFECT_DIRECTION_CUES,
    assess_generic_direction,
    assess_outcome_directions,
    build_validation_report,
    match_direction_cues,
    summarize_direction_assessments,
)


class EffectDirectionDictionaryTests(unittest.TestCase):
    def test_dictionary_validates_and_covers_all_cue_types(self):
        report = build_validation_report(cues=EFFECT_DIRECTION_CUES)

        self.assertEqual(report["validation_status"], "passed")
        self.assertEqual(report["policy_version"], DIRECTION_POLICY_VERSION)
        self.assertEqual(
            set(report["entries_by_cue_type"]),
            {"increase", "decrease", "improvement", "worsening", "null", "uncertain"},
        )
        self.assertFalse(report["runtime_scoring_changed"])

    def test_long_null_and_uncertain_phrases_override_embedded_change_words(self):
        null_matches = match_direction_cues("TEWL did not decrease.")
        uncertain_matches = match_direction_cues("The treatment may improve skin hydration.")

        self.assertEqual([match.cue.cue_type for match in null_matches], ["null"])
        self.assertEqual(
            [match.cue.cue_type for match in uncertain_matches],
            ["uncertain"],
        )

    def test_increase_and_decrease_are_compared_with_metric_benefit_direction(self):
        cases = {
            "TEWL decreased.": "positive",
            "TEWL increased.": "negative",
            "Skin hydration increased.": "positive",
            "Skin hydration decreased.": "negative",
            "The CIELAB a star value decreased.": "positive",
            "The CIELAB a star value increased.": "negative",
            "Skin irritation score decreased.": "positive",
            "Skin irritation score increased.": "negative",
            "There was a greater reduction in TEWL.": "positive",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                assessments = assess_outcome_directions(text)
                self.assertTrue(assessments)
                self.assertEqual(assessments[0].direction, expected)

    def test_null_and_hedged_results_do_not_become_positive(self):
        cases = {
            "There was no significant difference in TEWL.": "null",
            "TEWL was not significantly lower.": "null",
            "The treatment may improve skin hydration.": "unclear",
            "There was a trend toward lower wrinkle depth.": "unclear",
            "TEWL showed a decreasing trend.": "unclear",
            "TEWL may be lower after treatment.": "unclear",
            "Skin hydration showed comparable improvement to placebo.": "null",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                assessments = assess_outcome_directions(text)
                self.assertTrue(assessments)
                self.assertEqual(assessments[0].direction, expected)

    def test_parameter_specific_exfoliation_never_auto_promotes(self):
        for text in (
            "The desquamation index improved.",
            "The desquamation index decreased.",
            "The desquamation index increased.",
        ):
            with self.subTest(text=text):
                assessment = assess_outcome_directions(text)[0]
                self.assertEqual(assessment.direction, "unclear")
                self.assertEqual(assessment.reason, "parameter_specific_manual_review")

    def test_recovery_time_uses_decrease_direction_not_recovery_increase_direction(self):
        assessments = assess_outcome_directions("Skin barrier recovery time decreased.")

        self.assertEqual(len(assessments), 1)
        self.assertEqual(assessments[0].outcome_term, "barrier recovery time")
        self.assertEqual(assessments[0].expected_direction, "decrease")
        self.assertEqual(assessments[0].direction, "positive")

    def test_multiple_outcomes_preserve_effect_level_conflict(self):
        assessments = assess_outcome_directions(
            "TEWL decreased and skin hydration decreased."
        )
        overall, conflict, payload = summarize_direction_assessments(assessments)
        decoded = json.loads(payload)

        self.assertEqual(overall, "unclear")
        self.assertTrue(conflict)
        self.assertEqual(
            decoded["effect_moisture_barrier"]["direction"],
            "unclear",
        )
        self.assertTrue(decoded["effect_moisture_barrier"]["conflict"])

    def test_generic_direction_only_accepts_explicit_benefit_or_harm(self):
        self.assertEqual(assess_generic_direction("Wound healing improved."), "positive")
        self.assertEqual(assess_generic_direction("Symptoms worsened."), "negative")
        self.assertEqual(assess_generic_direction("Wound healing increased."), "unclear")
        self.assertEqual(assess_generic_direction("No improvement was observed."), "null")

    def test_review_regression_sentences(self):
        cases = {
            "TEWL decreased significantly after 4 weeks.": "positive",
            "Skin hydration increased significantly (p<0.01).": "positive",
            "There was no significant difference in TEWL between groups.": "null",
            "The active cream may improve skin hydration.": "unclear",
            "TEWL showed no significant decrease compared with vehicle.": "null",
            "Melanin index was not significantly decreased at week 8.": "null",
            "Skin hydration was not improved in the treated group.": "null",
            "Wrinkle depth was not significantly improved versus placebo.": "null",
            "The treatment had no significant effect on erythema index.": "null",
            "The cream significantly reduced erythema index; further studies are needed.": "positive",
            "Our findings suggested that X significantly reduced TEWL (p=0.003).": "positive",
            "The cream was applied to the lower arm; TEWL was measured weekly.": "unclear",
            "In subjects with impaired barrier function, hydration improved.": "positive",
            "A higher concentration was used; TEWL decreased.": "positive",
            "Skin hydration was significantly enhanced after 8 weeks.": "positive",
            "Erythema index fell markedly in the treated group.": "positive",
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                assessments = assess_outcome_directions(text)
                actual, _, _ = summarize_direction_assessments(
                    assessments,
                    fallback_text=text,
                )
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
