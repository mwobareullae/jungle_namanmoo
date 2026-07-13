from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_legacy_scale_500_scoring import (  # noqa: E402
    build_scoring,
    legacy_axis_floors,
    official_prior_score,
    read_csv,
)


DATA_DIR = Path(__file__).resolve().parents[2]


class LegacyScale500ScoringTests(unittest.TestCase):
    def test_official_prior_uses_legacy_axis_and_global_floors(self) -> None:
        floors = {
            "effect_moisture_barrier": 32,
            "effect_calming": 33,
        }
        self.assertEqual(
            official_prior_score(
                {
                    "effect_id": "effect_moisture_barrier",
                    "signal_strength": "high",
                },
                axis_floors=floors,
                global_floor=30,
            ),
            32,
        )
        self.assertEqual(
            official_prior_score(
                {
                    "effect_id": "effect_moisture_barrier",
                    "signal_strength": "medium",
                },
                axis_floors=floors,
                global_floor=30,
            ),
            30,
        )

    def test_real_frozen_cohort_build_preserves_legacy_and_activates_new_scores(self) -> None:
        current_effects = read_csv(
            DATA_DIR / "reconciliation/legacy_scale_500/baseline_ingredient_effect_34.csv"
        )
        current_evidence = read_csv(
            DATA_DIR / "reconciliation/legacy_scale_500/baseline_ingredient_evidence_34.csv"
        )
        outputs = build_scoring(
            current_effect_rows=current_effects,
            current_evidence_rows=current_evidence,
            cohort_rows=read_csv(
                DATA_DIR / "reconciliation/ingredient_evidence_adjudication_466.csv"
            ),
            ingredient_metadata_rows=read_csv(
                DATA_DIR / "reconciliation/ingredient_role_review.csv"
            ),
            screening_rows=read_csv(
                DATA_DIR / "reconciliation/ingredient_effect_pubmed_screening.csv"
            ),
            paper_override_rows=read_csv(
                DATA_DIR / "reconciliation/legacy_scale_500_paper_overrides.csv"
            ),
        )
        effect_rows, evidence_rows, pair_rows, ingredient_rows, summary = outputs

        self.assertEqual(effect_rows[:72], current_effects)
        self.assertEqual(evidence_rows[:72], current_evidence)
        self.assertEqual(
            [{key: str(value) for key, value in row.items()} for row in effect_rows],
            read_csv(DATA_DIR / "ingredient_effect.csv"),
        )
        self.assertEqual(
            [{key: str(value) for key, value in row.items()} for row in evidence_rows],
            read_csv(DATA_DIR / "ingredient_evidence.csv"),
        )
        self.assertEqual(len(ingredient_rows), 500)
        self.assertEqual(summary["score_active_ingredient_count"], 187)
        self.assertEqual(summary["new_score_active_ingredient_count"], 153)
        self.assertEqual(summary["effect_pair_count"], 245)
        self.assertEqual(summary["new_effect_pair_count"], 173)
        self.assertEqual(summary["official_function_prior_pair_count"], 144)
        self.assertEqual(summary["new_paper_evidence_row_count"], 35)
        self.assertFalse(summary["human_approval_gate_used"])
        self.assertFalse(summary["full_text_gate_used"])

        evidence_pairs = {
            (row["ingredient_id"], row["effect_id"])
            for row in evidence_rows
        }
        official_only_pairs = {
            (row["ingredient_id"], row["effect_id"])
            for row in pair_rows
            if row["score_origin"] == "official_function_prior"
        }
        effect_pairs = {
            (row["ingredient_id"], row["effect_id"])
            for row in effect_rows
        }
        self.assertEqual(effect_pairs - evidence_pairs, official_only_pairs)
        self.assertTrue(all(int(row["effect_score"]) > 0 for row in effect_rows))

    def test_legacy_axis_floors_match_current_runtime(self) -> None:
        floors = legacy_axis_floors(
            read_csv(
                DATA_DIR / "reconciliation/legacy_scale_500/baseline_ingredient_effect_34.csv"
            )
        )
        self.assertEqual(
            floors,
            {
                "effect_brightening": 43,
                "effect_moisture_barrier": 32,
                "effect_acne_sebum": 40,
                "effect_wrinkle": 42,
                "effect_calming": 33,
                "effect_exfoliation": 30,
            },
        )

    def test_paper_override_cannot_authorize_external_claim_use(self) -> None:
        paper_overrides = read_csv(
            DATA_DIR / "reconciliation/legacy_scale_500_paper_overrides.csv"
        )
        paper_overrides[0] = {
            **paper_overrides[0],
            "external_claim_use": "allowed",
        }

        with self.assertRaisesRegex(ValueError, "separate from external claims"):
            build_scoring(
                current_effect_rows=read_csv(
                    DATA_DIR
                    / "reconciliation/legacy_scale_500/baseline_ingredient_effect_34.csv"
                ),
                current_evidence_rows=read_csv(
                    DATA_DIR
                    / "reconciliation/legacy_scale_500/baseline_ingredient_evidence_34.csv"
                ),
                cohort_rows=read_csv(
                    DATA_DIR / "reconciliation/ingredient_evidence_adjudication_466.csv"
                ),
                ingredient_metadata_rows=read_csv(
                    DATA_DIR / "reconciliation/ingredient_role_review.csv"
                ),
                screening_rows=read_csv(
                    DATA_DIR / "reconciliation/ingredient_effect_pubmed_screening.csv"
                ),
                paper_override_rows=paper_overrides,
            )


if __name__ == "__main__":
    unittest.main()
