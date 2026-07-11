from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingredient_role_inventory import (  # noqa: E402
    CosingRecord,
    apply_mapping,
    build_rows,
    candidate_query_names,
    effect_signals,
    load_current_risks,
    load_cosing_cache,
    validate_generated_rows,
    write_cosing_cache,
)


class BuildIngredientRoleInventoryTests(unittest.TestCase):
    def test_effect_signals_exclude_broad_claims(self):
        signals = effect_signals(["SKIN CONDITIONING", "ANTIOXIDANT"])

        self.assertEqual(signals, {})

    def test_effect_signals_keep_direct_and_emollient_signals(self):
        signals = effect_signals(
            ["BLEACHING", "HUMECTANT", "SKIN CONDITIONING - EMOLLIENT"]
        )

        self.assertEqual(signals["effect_brightening"][0], "high")
        self.assertEqual(signals["effect_moisture_barrier"][0], "high")

    def test_emollient_alone_is_medium_moisture_signal(self):
        signals = effect_signals(["SKIN CONDITIONING - EMOLLIENT"])

        self.assertEqual(
            signals["effect_moisture_barrier"],
            ("medium", ("SKIN CONDITIONING - EMOLLIENT",)),
        )

    def test_query_names_include_parenthetical_variant(self):
        names = candidate_query_names("Avena Sativa (Oat) Kernel Extract")

        self.assertEqual(
            names,
            ("AVENA SATIVA (OAT) KERNEL EXTRACT", "AVENA SATIVA KERNEL EXTRACT"),
        )

    def test_exact_name_mapping_precedes_wildcard_mapping(self):
        result = apply_mapping(
            "broad",
            "Exact Name",
            {("broad", "exactname"): "exact"},
            {"broad": "fallback"},
        )

        self.assertEqual(result, "exact")

    def test_risk_flag_uses_wildcard_canonical_mapping(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "risk_flags.csv"
            path.write_text(
                "ingredient_id,risk_type\n"
                "ing_pending_a,irritation\n",
                encoding="utf-8",
            )
            risks = load_current_risks(path, {"ing_pending_a": "canonical_a"})

        self.assertEqual(risks["canonical_a"], {"irritation"})

    def test_validation_rejects_scored_new_watchlist_pair(self):
        roles = [{"ingredient_id": "ingredient_a"}]
        watch = [
            {
                "ingredient_id": "ingredient_a",
                "effect_id": "effect_calming",
                "pair_status": "new_watchlist_proposal",
                "review_status": "candidate_unverified",
                "score_change": "none",
                "current_effect_score": "50",
            }
        ]

        with self.assertRaises(ValueError):
            validate_generated_rows(roles, watch, current_pair_count=0)

    def test_cosing_cache_round_trip(self):
        import tempfile

        records = {
            "GLYCERIN": CosingRecord(
                inci_name="GLYCERIN",
                functions=("HUMECTANT",),
                restrictions=(),
                sccs_opinions=(),
                substance_ids=("123",),
            )
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "cache.csv"
            write_cosing_cache(path, records, "2026-07-12")
            loaded, fetched_on = load_cosing_cache(path)

        self.assertEqual(loaded, records)
        self.assertEqual(fetched_on, "2026-07-12")

    def test_cosing_cache_load_collapses_metadata_whitespace(self):
        import csv
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "cache.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "fetched_on",
                        "source_url",
                        "inci_name",
                        "functions_json",
                        "restrictions_json",
                        "sccs_opinions_json",
                        "substance_ids_json",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "fetched_on": "2026-07-12",
                        "source_url": "https://example.com",
                        "inci_name": "TEST INCI",
                        "functions_json": json.dumps(["SKIN  CONDITIONING"]),
                        "restrictions_json": json.dumps(["III/61\r\nrestricted"]),
                        "sccs_opinions_json": json.dumps([]),
                        "substance_ids_json": json.dumps([" 123 "]),
                    }
                )

            loaded, _ = load_cosing_cache(path)

        self.assertEqual(loaded["TEST INCI"].functions, ("SKIN CONDITIONING",))
        self.assertEqual(loaded["TEST INCI"].restrictions, ("III/61 restricted",))
        self.assertEqual(loaded["TEST INCI"].substance_ids, ("123",))

    def test_pubmed_screening_filters_unselected_cosing_signal(self):
        ingredients = [
            {"ingredient_id": "selected", "name_ko": "선택", "name_en": "Selected"},
            {"ingredient_id": "rejected", "name_ko": "제외", "name_en": "Rejected"},
        ]
        records = {
            "SELECTED": CosingRecord("SELECTED", ("HUMECTANT",), (), (), ()),
            "REJECTED": CosingRecord("REJECTED", ("HUMECTANT",), (), (), ()),
        }

        roles, watch = build_rows(
            ingredients,
            records,
            Counter({"selected": 2, "rejected": 1}),
            {"selected": 2, "rejected": 1},
            {},
            {},
            "2026-07-12",
            {("selected", "effect_moisture_barrier"): "human_topical_pubmed_candidate"},
        )

        by_id = {row["ingredient_id"]: row for row in roles}
        self.assertEqual(by_id["selected"]["role_effect_candidate"], "Y")
        self.assertEqual(by_id["selected"]["classification_status"], "candidate_unverified")
        self.assertEqual(by_id["rejected"]["role_effect_candidate"], "N")
        self.assertEqual(by_id["rejected"]["classification_status"], "not_selected")
        self.assertEqual(
            [(row["ingredient_id"], row["effect_id"]) for row in watch],
            [("selected", "effect_moisture_barrier")],
        )


if __name__ == "__main__":
    unittest.main()
