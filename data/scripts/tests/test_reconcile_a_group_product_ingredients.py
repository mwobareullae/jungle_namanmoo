from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from reconcile_a_group_product_ingredients import (  # noqa: E402
    PRODUCT_INGREDIENT_FIELDS,
    load_alias_lookup,
    read_product_ingredient_rows,
    reconcile_rows,
    write_product_ingredients,
)


class ReconcileProductIngredientsTests(unittest.TestCase):
    def test_canonical_filter_only_applies_selected_alias_targets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            alias_path = Path(tmp_dir) / "ingredient_aliases.csv"
            alias_path.write_text(
                "alias,canonical_id,alias_type,confidence,source\n"
                "글라브리딘,glabridin,ko,high,test\n"
                "글루코노락톤,gluconolactone,ko,high,test\n"
                "감초추출물,licorice_extract,ko,high,test\n",
                encoding="utf-8",
            )

            alias_lookup = load_alias_lookup(
                alias_path,
                {"glabridin", "gluconolactone"},
            )
            rows = [
                self._row("prod_1", "ing_pending_glabridin", "글라브리딘"),
                self._row("prod_2", "licorice_extract", "감초추출물"),
                self._row("prod_3", "pha", "글루코노락톤"),
            ]

            output, review, stats = reconcile_rows(rows, alias_lookup)

        ids_by_product = {row["product_id"]: row["ingredient_id"] for row in output}
        self.assertEqual(ids_by_product["prod_1"], "glabridin")
        self.assertEqual(ids_by_product["prod_2"], "licorice_extract")
        self.assertEqual(ids_by_product["prod_3"], "gluconolactone")
        self.assertEqual(stats["matched_rows"], 2)
        self.assertEqual(review, [])

    def test_split_writer_keeps_rows_in_their_original_shards(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            shard_dir = data_dir / "product_ingredients"
            shard_dir.mkdir(parents=True)
            alias_path = data_dir / "ingredient_aliases.csv"
            alias_path.write_text(
                "alias,canonical_id,alias_type,confidence,source\n"
                "글라브리딘,glabridin,ko,high,test\n"
                "Glabridin,glabridin,inci,high,test\n",
                encoding="utf-8",
            )
            first_path = shard_dir / "product_ingredients_000.csv"
            second_path = shard_dir / "product_ingredients_001.csv"
            self._write_rows(
                first_path,
                [self._row("prod_1", "ing_pending_ko", "글라브리딘")],
            )
            self._write_rows(
                second_path,
                [
                    self._row("prod_1", "ing_pending_en", "Glabridin"),
                    self._row("prod_2", "unrelated", "Other"),
                ],
            )

            product_path = data_dir / "product_ingredients.csv"
            rows = read_product_ingredient_rows(product_path)
            alias_lookup = load_alias_lookup(alias_path, {"glabridin"})
            output, _, stats = reconcile_rows(rows, alias_lookup)
            write_product_ingredients(product_path, PRODUCT_INGREDIENT_FIELDS, output)

            first_rows = read_product_ingredient_rows(first_path)
            second_rows = read_product_ingredient_rows(second_path)

        self.assertEqual(first_rows[0]["ingredient_id"], "glabridin")
        self.assertEqual([row["product_id"] for row in second_rows], ["prod_2"])
        self.assertEqual(stats["collapsed_rows"], 1)

    def test_single_file_writer_ignores_internal_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            product_path = Path(tmp_dir) / "product_ingredients.csv"
            self._write_rows(
                product_path,
                [self._row("prod_1", "glabridin", "글라브리딘")],
            )
            rows = read_product_ingredient_rows(product_path)

            write_product_ingredients(product_path, PRODUCT_INGREDIENT_FIELDS, rows)
            reloaded = read_product_ingredient_rows(product_path)

        self.assertEqual(reloaded[0]["ingredient_id"], "glabridin")

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
        import csv

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=PRODUCT_INGREDIENT_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
