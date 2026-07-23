from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from generate_production_ingredient_mapping_csv import (  # noqa: E402
    generate_mapping_csv,
    normalize_display_name,
    repair_mojibake,
)


class GenerateProductionIngredientMappingCsvTests(unittest.TestCase):
    def test_repairs_utf8_mojibake_and_compatibility_jamo(self):
        broken = b"\xed\x8c\x90\xed\x85\x8c\xeb\x86\x80".decode("latin-1")
        self.assertEqual(repair_mojibake(broken), "판테놀")
        self.assertEqual(repair_mojibake("PÃªche"), "Pêche")
        self.assertEqual(repair_mojibake("AÃ§aÃ­"), "Açaí")
        self.assertEqual(
            normalize_display_name("\u314d\u314f\u3134테놀???20"),
            "판테놀",
        )

    def test_generates_ready_csv_and_excludes_requested_count(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pending = root / "pending.csv"
            ingredients = root / "ingredients.csv"
            aliases = root / "aliases.csv"
            output = root / "ready.csv"
            pending.write_text(
                "action,pending_code,raw_name,normalized_source_name,expected_connection_count,target_ingredient_code,target_name_ko,target_name_en,decision_reason,source_reference\n"
                "MAP_EXISTING,ing_pending_a,Panthenol,panthenol,2,,,,,\n"
                "MAP_EXISTING,ing_pending_b,Complex Blend,complexblend,1,,,,,\n"
                "MAP_EXISTING,ing_pending_c,visit example.com,visitexample.com,1,,,,,\n",
                encoding="utf-8-sig",
            )
            ingredients.write_text(
                "ingredient_id,name_ko,name_en,description,source_url\n"
                "panthenol,판테놀,Panthenol,,\n"
                "ing_pending_a,Panthenol,,,\n"
                "ing_pending_b,Complex Blend,,,\n"
                "ing_pending_c,visit example.com,,,\n",
                encoding="utf-8-sig",
            )
            aliases.write_text(
                "alias,canonical_id,alias_type,confidence,source\n",
                encoding="utf-8-sig",
            )

            summary, excluded = generate_mapping_csv(
                pending_path=pending,
                ingredients_path=ingredients,
                aliases_path=aliases,
                output_path=output,
                excluded_count=1,
            )

            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(summary.input_rows, 3)
        self.assertEqual(summary.output_rows, 2)
        self.assertEqual(summary.excluded_rows, 1)
        self.assertEqual(excluded[0].pending_code, "ing_pending_c")
        self.assertEqual(rows[0]["action"], "MAP_EXISTING")
        self.assertEqual(rows[0]["target_ingredient_code"], "panthenol")
        self.assertEqual(rows[1]["action"], "CREATE_AND_MAP")
        self.assertEqual(rows[1]["target_ingredient_code"], "ing_generated_b")


if __name__ == "__main__":
    unittest.main()
