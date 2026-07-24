from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingredient_canonicalization_inventory import (  # noqa: E402
    build_inventory,
    load_mapping_keys,
)
from reconcile_a_group_product_ingredients import PRODUCT_INGREDIENT_FIELDS  # noqa: E402


class BuildIngredientCanonicalizationInventoryTests(unittest.TestCase):
    def test_ranks_pending_ids_and_keeps_only_safe_automatic_labels(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            shard_dir = data_dir / "product_ingredients"
            shard_dir.mkdir(parents=True)
            aliases_path = data_dir / "ingredient_aliases.csv"
            aliases_path.write_text(
                "alias,canonical_id,alias_type,confidence,source\n"
                "정제수,water,ko,high,test\n",
                encoding="utf-8",
            )
            mappings_path = data_dir / "ingredient_canonical_mappings.csv"
            mappings_path.write_text(
                "source_ingredient_id,source_ingredient_name,canonical_id,mapping_type,confidence,source\n"
                "ing_pending_mapped,,mapped,official_exact,high,test\n"
                "ing_pending_split,Exact Name,exact_name,exact_name_override,high,test\n",
                encoding="utf-8",
            )
            self._write_rows(
                shard_dir / "product_ingredients_000.csv",
                [
                    self._row("p1", "ing_pending_water", "정제수"),
                    self._row("p2", "ing_pending_water", "정제수"),
                    self._row("p3", "ing_pending_new", "Tocopherol"),
                    self._row("p4", "ing_pending_noise", "1"),
                    self._row("p5", "water", "Water"),
                    self._row("p6", "ing_pending_mapped", "Mapped"),
                    self._row("p7", "ing_pending_split", "Exact Name"),
                    self._row("p8", "ing_pending_split", "Unmapped Name"),
                ],
            )

            mapped_source_ids, mapped_source_names = load_mapping_keys(mappings_path)

            rows, stats = build_inventory(
                data_dir / "product_ingredients.csv",
                aliases_path,
                limit=10,
                mapped_source_ids=mapped_source_ids,
                mapped_source_names=mapped_source_names,
            )

        by_id = {row["source_ingredient_id"]: row for row in rows}
        self.assertEqual(rows[0]["source_ingredient_id"], "ing_pending_water")
        self.assertEqual(by_id["ing_pending_water"]["triage_status"], "merge_existing")
        self.assertEqual(by_id["ing_pending_water"]["existing_canonical_id"], "water")
        self.assertEqual(by_id["ing_pending_new"]["triage_status"], "canonical_review_required")
        self.assertEqual(by_id["ing_pending_noise"]["triage_status"], "reject_noise_candidate")
        self.assertNotIn("ing_pending_mapped", by_id)
        self.assertEqual(by_id["ing_pending_split"]["row_count"], "1")
        self.assertEqual(by_id["ing_pending_split"]["dominant_name"], "Unmapped Name")
        self.assertEqual(
            json.loads(by_id["ing_pending_water"]["observed_names_json"]),
            [{"name": "정제수", "count": 2}],
        )
        self.assertEqual(stats["total_rows"], 8)
        self.assertEqual(stats["selected_rows"], 5)

    @staticmethod
    def _row(product_id: str, ingredient_id: str, ingredient_name: str) -> dict[str, str]:
        return {
            "product_id": product_id,
            "ingredient_id": ingredient_id,
            "ingredient_name": ingredient_name,
            "content_confidence": "unknown",
            "display_order": "1",
            "concentration_text": "",
            "concentration_value": "",
            "concentration_unit": "",
            "concentration_confidence": "unknown",
            "normalized_concentration_value": "",
            "normalized_concentration_unit": "",
        }

    @staticmethod
    def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=PRODUCT_INGREDIENT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
