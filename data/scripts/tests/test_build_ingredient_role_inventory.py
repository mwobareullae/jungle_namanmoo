from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingredient_role_inventory import (  # noqa: E402
    CosingRecord,
    apply_mapping,
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


if __name__ == "__main__":
    unittest.main()
