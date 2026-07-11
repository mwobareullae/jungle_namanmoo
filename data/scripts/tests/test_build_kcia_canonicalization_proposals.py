from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_kcia_canonicalization_proposals import (  # noqa: E402
    KciaIngredient,
    analyze_inventory_matches,
    build_official_index,
    build_proposals,
    disambiguate_canonical_id,
    normalize_match,
    slugify,
)


class BuildKciaCanonicalizationProposalsTests(unittest.TestCase):
    def test_official_index_matches_standard_and_legacy_names(self):
        record = KciaIngredient(
            code="9",
            standard_name_ko="리날룰",
            standard_name_en="Linalool",
            old_names_ko="구명칭|옛명칭",
            old_names_en="Old Name",
        )

        index = build_official_index([record])

        self.assertEqual(index[normalize_match("LINALOOL")], (record,))
        self.assertEqual(index[normalize_match("옛명칭")], (record,))
        self.assertEqual(slugify(record), "linalool")

    def test_slugify_caps_database_identifier_length(self):
        record = KciaIngredient(
            code="12345",
            standard_name_ko="긴성분명",
            standard_name_en="A Very Long Ingredient Name " * 8,
            old_names_ko="",
            old_names_en="",
        )

        ingredient_id = slugify(record)

        self.assertLessEqual(len(ingredient_id), 64)
        self.assertTrue(ingredient_id.endswith("_kcia_12345"))
        disambiguated = disambiguate_canonical_id(ingredient_id, record)
        self.assertLessEqual(len(disambiguated), 64)
        self.assertTrue(disambiguated.endswith("_kcia_12345"))

    def test_builds_only_exact_review_proposals_and_counts_unique_codes(self):
        records = [
            KciaIngredient("1", "페녹시에탄올", "Phenoxyethanol", "", ""),
            KciaIngredient("2", "토코페롤", "Tocopherol", "", ""),
            KciaIngredient("3", "정제수", "Water", "", ""),
            KciaIngredient("4", "아세틸헥사펩타이드-8", "Acetyl Hexapeptide-8", "", ""),
        ]
        inventory_rows = [
            self._inventory("1", "p1", "Phenoxyethanol", "canonical_review_required"),
            self._inventory("2", "p2", "Tocopherol", "canonical_review_required"),
            self._inventory("3", "p3", "Water", "merge_existing", "water"),
            self._inventory("4", "p4", "Unknown Blend", "canonical_review_required"),
            self._inventory("5", "p5", "Acetyl Hexapeptide-8", "merge_existing", "peptides"),
        ]
        ingredients = [
            {
                "ingredient_id": "water",
                "name_ko": "정제수",
                "name_en": "Water",
            },
            {
                "ingredient_id": "peptides",
                "name_ko": "펩타이드",
                "name_en": "Peptides",
            },
        ]
        aliases = [
            {"alias": "Water", "canonical_id": "water"},
            {"alias": "Acetyl Hexapeptide-8", "canonical_id": "peptides"},
        ]

        rows, stats = build_proposals(
            inventory_rows,
            records,
            ingredients,
            aliases,
            target_canonical_count=4,
            source_sha256="abc",
        )

        by_id = {row["source_ingredient_id"]: row for row in rows}
        self.assertEqual(by_id["p1"]["proposed_action"], "create_canonical")
        self.assertEqual(by_id["p1"]["selected_for_target"], "Y")
        self.assertEqual(by_id["p2"]["proposed_action"], "create_canonical")
        self.assertEqual(by_id["p2"]["selected_for_target"], "Y")
        self.assertEqual(by_id["p3"]["proposed_action"], "merge_existing")
        self.assertEqual(by_id["p4"]["proposed_action"], "manual_review")
        self.assertEqual(by_id["p5"]["proposed_action"], "create_canonical")
        self.assertEqual(by_id["p5"]["related_scoring_family_ids"], "peptides")
        self.assertEqual(stats["current_canonical_count"], 2)
        self.assertEqual(stats["selected_new_canonical"], 2)
        self.assertEqual(stats["projected_canonical_count"], 4)

    def test_variant_conflict_is_not_automatically_mapped(self):
        first = KciaIngredient("1", "첫성분", "First Ingredient", "", "")
        second = KciaIngredient("2", "둘성분", "Second Ingredient", "", "")
        row = self._inventory("1", "p1", "First Ingredient", "canonical_review_required")
        row["row_count"] = "10"
        row["observed_names_json"] = (
            '[{"name":"First Ingredient","count":9},'
            '{"name":"Second Ingredient","count":1}]'
        )

        record, matched_rows, ratio, conflicts, ambiguous = analyze_inventory_matches(
            row, build_official_index([first, second])
        )

        self.assertEqual(record, first)
        self.assertEqual(matched_rows, 10)
        self.assertEqual(ratio, 1.0)
        self.assertEqual(conflicts, {"2"})
        self.assertFalse(ambiguous)

    @staticmethod
    def _inventory(
        rank: str,
        source_id: str,
        name: str,
        status: str,
        existing_id: str = "",
    ) -> dict[str, str]:
        return {
            "rank": rank,
            "source_ingredient_id": source_id,
            "dominant_name": name,
            "row_count": "10",
            "product_count": "10",
            "existing_canonical_id": existing_id,
            "triage_status": status,
            "triage_note": "",
        }


if __name__ == "__main__":
    unittest.main()
