from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from apply_ingredient_canonicalization_batch import apply_batch, read_csv  # noqa: E402


class ApplyIngredientCanonicalizationBatchTests(unittest.TestCase):
    def test_applies_exact_rows_idempotently_and_reassigns_family_alias(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ingredients = root / "ingredients.csv"
            aliases = root / "ingredient_aliases.csv"
            proposals = root / "proposals.csv"
            mappings = root / "ingredient_canonical_mappings.csv"
            alias_changes = root / "alias_changes.csv"
            ingredients.write_text(
                "ingredient_id,name_ko,name_en,description,source_url\n"
                "peptides,펩타이드,Peptides,포괄 canonical,\n"
                "ing_pending_one,원문1,Raw 1,pending,\n"
                "ing_pending_two,원문2,Raw 2,pending,\n",
                encoding="utf-8-sig",
            )
            aliases.write_text(
                "alias,canonical_id,alias_type,confidence,source\n"
                "Acetyl Hexapeptide-8,peptides,inci,high,old\n",
                encoding="utf-8",
            )
            self._write_proposals(proposals)

            first = apply_batch(
                proposals_path=proposals,
                ingredients_path=ingredients,
                aliases_path=aliases,
                mappings_path=mappings,
                alias_changes_path=alias_changes,
            )
            second = apply_batch(
                proposals_path=proposals,
                ingredients_path=ingredients,
                aliases_path=aliases,
                mappings_path=mappings,
                alias_changes_path=alias_changes,
            )

            ingredient_rows = read_csv(ingredients)
            alias_rows = read_csv(aliases)
            mapping_rows = read_csv(mappings)
        self.assertEqual(first.canonical_added, 1)
        self.assertEqual(second.canonical_added, 0)
        self.assertEqual(
            sum(row["ingredient_id"] == "acetyl_hexapeptide_8" for row in ingredient_rows),
            1,
        )
        self.assertEqual(len(mapping_rows), 4)
        self.assertTrue(all(row["canonical_id"] == "acetyl_hexapeptide_8" for row in mapping_rows))
        self.assertEqual(
            sum(row["mapping_type"] == "exact_name_override" for row in mapping_rows),
            2,
        )
        exact_alias = next(row for row in alias_rows if row["alias"] == "Acetyl Hexapeptide-8")
        self.assertEqual(exact_alias["canonical_id"], "acetyl_hexapeptide_8")

    @staticmethod
    def _write_proposals(path: Path) -> None:
        fieldnames = [
            "rank",
            "source_ingredient_id",
            "kcia_ingredient_code",
            "kcia_standard_name_ko",
            "kcia_standard_name_en",
            "kcia_old_names_ko",
            "kcia_old_names_en",
            "proposed_action",
            "proposed_canonical_id",
            "related_scoring_family_ids",
            "selected_for_target",
            "proposal_confidence",
            "review_status",
            "source_document_sha256",
        ]
        rows = []
        for rank, source_id in enumerate(("ing_pending_one", "ing_pending_two"), 1):
            rows.append(
                {
                    "rank": rank,
                    "source_ingredient_id": source_id,
                    "kcia_ingredient_code": "100",
                    "kcia_standard_name_ko": "아세틸헥사펩타이드-8",
                    "kcia_standard_name_en": "Acetyl Hexapeptide-8",
                    "kcia_old_names_ko": "",
                    "kcia_old_names_en": "",
                    "proposed_action": "create_canonical",
                    "proposed_canonical_id": "acetyl_hexapeptide_8",
                    "related_scoring_family_ids": "peptides",
                    "selected_for_target": "Y",
                    "proposal_confidence": "high",
                    "review_status": "accepted_auto_exact",
                    "source_document_sha256": "abcdef1234567890",
                }
            )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
