from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from validate_ingredient_canonicalization_batch import validate_batch  # noqa: E402


class ValidateIngredientCanonicalizationBatchTests(unittest.TestCase):
    def test_counts_mapped_rows_and_collapsed_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ingredients = root / "ingredients.csv"
            mappings = root / "ingredient_canonical_mappings.csv"
            product_ingredients = root / "product_ingredients.csv"
            ingredients.write_text(
                "ingredient_id,name_ko,name_en,description,source_url\n"
                "canonical_one,정식,Canonical,exact,\n"
                "ing_pending_a,대기A,Pending A,pending,\n"
                "ing_pending_b,대기B,Pending B,pending,\n"
                "ing_pending_c,대기C,Pending C,pending,\n",
                encoding="utf-8",
            )
            mappings.write_text(
                "source_ingredient_id,source_ingredient_name,canonical_id,mapping_type,confidence,source\n"
                "ing_pending_a,,canonical_one,official_exact,high,test\n"
                "ing_pending_b,,canonical_one,official_exact,high,test\n",
                encoding="utf-8",
            )
            with product_ingredients.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["product_id", "ingredient_id", "ingredient_name"],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"product_id": "p1", "ingredient_id": "ing_pending_a", "ingredient_name": "A"},
                        {"product_id": "p1", "ingredient_id": "ing_pending_b", "ingredient_name": "B"},
                        {"product_id": "p1", "ingredient_id": "ing_pending_c", "ingredient_name": "C"},
                        {"product_id": "p2", "ingredient_id": "canonical_one", "ingredient_name": "Canonical"},
                    ]
                )

            stats = validate_batch(
                ingredients_path=ingredients,
                mappings_path=mappings,
                product_ingredients_path=product_ingredients,
            )

        self.assertEqual(stats.canonical_count, 1)
        self.assertEqual(stats.mapped_source_rows, 2)
        self.assertEqual(stats.already_canonical_rows, 1)
        self.assertEqual(stats.unmapped_pending_rows, 1)
        self.assertEqual(stats.duplicate_effective_pairs, 1)
        self.assertEqual(stats.unique_effective_pairs, 3)
        self.assertEqual(stats.affected_product_count, 1)


if __name__ == "__main__":
    unittest.main()
