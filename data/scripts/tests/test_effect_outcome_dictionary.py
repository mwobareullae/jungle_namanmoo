from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingredient_first_paper_catalog import (  # noqa: E402
    EXISTING_EFFECT_MAPPING_TERMS,
)
from discover_new_evidence import EFFECT_TERMS  # noqa: E402
from effect_outcome_dictionary import (  # noqa: E402
    APPROVED_DISCOVERY_TERMS,
    APPROVED_MAPPING_TERMS,
    BANNED_STANDALONE_MAPPING_TERMS,
    EFFECT_IDS,
    EFFECT_OUTCOME_ENTRIES,
    build_validation_report,
    match_effect_ids,
    match_outcome_terms,
    normalize_phrase,
)
from search_missing_effect_evidence import EXPANDED_EFFECT_TERMS  # noqa: E402


class EffectOutcomeDictionaryTests(unittest.TestCase):
    def test_dictionary_covers_six_effects_and_validates(self):
        report = build_validation_report(entries=EFFECT_OUTCOME_ENTRIES)

        self.assertEqual(report["validation_status"], "passed")
        self.assertEqual(report["effect_count"], 6)
        self.assertEqual(set(report["entries_by_effect"]), set(EFFECT_IDS))
        self.assertGreater(report["approved_mapping_entry_count"], 0)
        self.assertGreater(report["standalone_blocked_entry_count"], 0)
        self.assertFalse(report["runtime_scoring_changed"])

    def test_all_collectors_use_the_same_reviewed_dictionary(self):
        self.assertEqual(EFFECT_TERMS, APPROVED_DISCOVERY_TERMS)
        self.assertEqual(EXPANDED_EFFECT_TERMS, APPROVED_DISCOVERY_TERMS)
        self.assertEqual(EXISTING_EFFECT_MAPPING_TERMS, APPROVED_MAPPING_TERMS)

    def test_high_confidence_metrics_map_to_expected_effects(self):
        cases = {
            "Melasma patients had a lower melanin index and higher CIELAB lightness.": {
                "effect_brightening"
            },
            "Niacinamide decreased hyperpigmented spots and increased skin lightness.": {
                "effect_brightening"
            },
            "Acne inflammatory lesion count decreased after treatment.": {
                "effect_acne_sebum"
            },
            "Facial sebum production decreased after topical treatment.": {
                "effect_acne_sebum"
            },
            "The acne GAGS score decreased after treatment.": {
                "effect_acne_sebum"
            },
            "Wrinkle depth decreased while skin elasticity increased.": {
                "effect_wrinkle"
            },
            "Fine lines and wrinkles decreased while facial elasticity improved.": {
                "effect_wrinkle"
            },
            "TEWL decreased and stratum corneum hydration increased.": {
                "effect_moisture_barrier"
            },
            "Skin moisturization and skin capacitance increased.": {
                "effect_moisture_barrier"
            },
            "The erythema index and itch severity both decreased.": {
                "effect_calming"
            },
            "Facial red blotchiness decreased after topical treatment.": {
                "effect_calming"
            },
            "The CIELAB a star value decreased after topical treatment.": {
                "effect_calming"
            },
            "The desquamation index changed after topical treatment.": {
                "effect_exfoliation"
            },
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(set(match_effect_ids(text)), expected)

    def test_ambiguous_abbreviations_require_context(self):
        self.assertNotIn("effect_acne_sebum", match_effect_ids("IGA decreased."))
        self.assertIn(
            "effect_acne_sebum",
            match_effect_ids("The acne IGA decreased after treatment."),
        )
        self.assertNotIn("effect_brightening", match_effect_ids("ITA increased."))
        self.assertIn(
            "effect_brightening",
            match_effect_ids("The skin color ITA increased."),
        )

    def test_instruments_methods_and_mechanisms_do_not_map_alone(self):
        blocked_texts = (
            "Mexameter measurements were collected.",
            "PRIMOS images were obtained.",
            "D-Squame samples were collected.",
            "Tape stripping was performed on the stratum corneum.",
            "Tyrosinase and collagen synthesis were measured.",
        )

        for text in blocked_texts:
            with self.subTest(text=text):
                self.assertEqual(match_effect_ids(text), [])

    def test_matching_uses_token_boundaries_and_longest_overlap(self):
        self.assertEqual(
            match_effect_ids("Skin irritation score decreased."),
            ["effect_calming"],
        )
        self.assertEqual(
            match_effect_ids("Skin capacitance increased."),
            ["effect_moisture_barrier"],
        )

        lesion_matches = match_outcome_terms(
            "The non-inflammatory lesion count decreased."
        )
        barrier_matches = match_outcome_terms("Skin barrier function improved.")

        self.assertEqual(
            [entry.term for entry in lesion_matches],
            ["non-inflammatory lesion count"],
        )
        self.assertEqual(
            [entry.term for entry in barrier_matches],
            ["skin barrier function"],
        )

    def test_every_approved_term_is_reachable_with_its_required_context(self):
        for entry in EFFECT_OUTCOME_ENTRIES:
            if entry.mapping_use != "Y":
                continue
            text = " ".join((entry.term, *entry.required_context_terms))
            with self.subTest(effect_id=entry.effect_id, term=entry.term):
                self.assertIn(entry.effect_id, match_effect_ids(text))

    def test_overlapping_approved_terms_prefer_the_longest_expression(self):
        approved = [
            entry for entry in EFFECT_OUTCOME_ENTRIES if entry.mapping_use == "Y"
        ]
        checked = 0
        for longer in approved:
            longer_tokens = normalize_phrase(longer.term).split()
            for shorter in approved:
                if longer is shorter:
                    continue
                shorter_tokens = normalize_phrase(shorter.term).split()
                width = len(shorter_tokens)
                if width >= len(longer_tokens):
                    continue
                if not any(
                    longer_tokens[index : index + width] == shorter_tokens
                    for index in range(len(longer_tokens) - width + 1)
                ):
                    continue
                text = " ".join((longer.term, *longer.required_context_terms))
                matched_terms = {entry.term for entry in match_outcome_terms(text)}
                with self.subTest(longer=longer.term, shorter=shorter.term):
                    self.assertIn(longer.term, matched_terms)
                    self.assertNotIn(shorter.term, matched_terms)
                checked += 1

        self.assertGreater(checked, 0)

    def test_broad_context_terms_are_never_approved_for_mapping(self):
        mapping_terms = {
            term.casefold()
            for terms in APPROVED_MAPPING_TERMS.values()
            for term in terms
        }

        self.assertTrue(BANNED_STANDALONE_MAPPING_TERMS.isdisjoint(mapping_terms))

    def test_exfoliation_direction_stays_parameter_specific(self):
        exfoliation_entries = [
            entry
            for entry in EFFECT_OUTCOME_ENTRIES
            if entry.effect_id == "effect_exfoliation" and entry.mapping_use == "Y"
        ]

        self.assertTrue(exfoliation_entries)
        self.assertTrue(
            all(entry.positive_direction == "parameter_specific" for entry in exfoliation_entries)
        )

    def test_blocked_terms_are_explicit_internal_guardrails(self):
        blocked_entries = [
            entry for entry in EFFECT_OUTCOME_ENTRIES if entry.mapping_use == "N"
        ]

        self.assertTrue(blocked_entries)
        self.assertTrue(
            all(entry.source_type == "internal_guardrail" for entry in blocked_entries)
        )
        self.assertTrue(
            all(
                entry.source_reference == "POLICY:effect-outcome-v1"
                for entry in blocked_entries
            )
        )

    def test_dictionary_effect_ids_exist_in_runtime_and_concern_contracts(self):
        repo_root = SCRIPT_DIR.parents[1]
        with (repo_root / "data/ingredient_effect.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            runtime_effect_ids = {row["effect_id"] for row in csv.DictReader(handle)}
        with (repo_root / "data/concern_to_effect.json").open(encoding="utf-8") as handle:
            concern_effect_ids = {row["effect_id"] for row in json.load(handle)}

        self.assertTrue(set(EFFECT_IDS).issubset(runtime_effect_ids))
        self.assertTrue(set(EFFECT_IDS).issubset(concern_effect_ids))


if __name__ == "__main__":
    unittest.main()
