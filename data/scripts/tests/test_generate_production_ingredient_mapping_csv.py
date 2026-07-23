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


HEADER = (
    "action,pending_code,raw_name,normalized_source_name,expected_connection_count,"
    "target_ingredient_code,target_name_ko,target_name_en,decision_reason,source_reference\n"
)
SUGGESTION_HEADER = (
    "pending_code,normalized_source_name,candidate_type,target_ingredient_code,"
    "target_ingredient_name,match_source\n"
)


class GenerateProductionIngredientMappingCsvTests(unittest.TestCase):
    def test_repairs_utf8_mojibake_and_compatibility_jamo(self):
        broken = b"\xed\x8c\x90\xed\x85\x8c\xeb\x86\x80".decode("latin-1")
        self.assertEqual(repair_mojibake(broken), "판테놀")
        self.assertEqual(normalize_display_name("ㅍㅏㄴ테놀???20"), "판테놀")

    def test_uses_only_production_suggestion_and_preserves_export_identity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pending = root / "pending.csv"
            suggestions = root / "suggestions.csv"
            ingredients = root / "ingredients.csv"
            output = root / "ready.csv"
            pending.write_text(
                HEADER
                + "MAP_EXISTING,ing_pending_a,Panthenol,panthenol,2,,,,,\n"
                + "MAP_EXISTING,ing_pending_b,Complex Blend,complexblend,1,,,,,\n"
                + "MAP_EXISTING,ing_pending_c,visit example.com,visitexample.com,1,,,,,\n",
                encoding="utf-8-sig",
            )
            suggestions.write_text(
                SUGGESTION_HEADER
                + "ing_pending_a,panthenol,ALIAS_EXACT_MATCH,panthenol,판테놀,ALIAS_EXACT\n"
                + "ing_pending_b,complexblend,NO_EXACT_MATCH,,,\n"
                + "ing_pending_c,visitexample.com,NO_EXACT_MATCH,,,\n",
                encoding="utf-8-sig",
            )
            ingredients.write_text(
                "ingredient_id,name_ko,name_en,description,source_url\n"
                "panthenol,판테놀,Panthenol,,\n"
                "ing_pending_a,Panthenol,,,,\n"
                "ing_pending_b,Complex Blend,,,,\n"
                "ing_pending_c,visit example.com,,,,\n",
                encoding="utf-8-sig",
            )

            summary, excluded = generate_mapping_csv(
                pending_path=pending,
                suggestions_path=suggestions,
                ingredients_path=ingredients,
                output_path=output,
                excluded_count=1,
            )

            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(summary.input_rows, 3)
        self.assertEqual(summary.output_rows, 2)
        self.assertEqual(summary.mapped_existing, 1)
        self.assertEqual(summary.created_canonical, 1)
        self.assertEqual(excluded[0].pending_code, "ing_pending_c")
        self.assertEqual(rows[0]["action"], "MAP_EXISTING")
        self.assertEqual(rows[0]["target_ingredient_code"], "panthenol")
        self.assertEqual(rows[0]["normalized_source_name"], "panthenol")
        self.assertEqual(rows[1]["action"], "CREATE_AND_MAP")
        self.assertEqual(rows[1]["target_ingredient_code"], "ing_generated_b")

    def test_overlong_normalized_source_is_prioritized_for_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pending = root / "pending.csv"
            suggestions = root / "suggestions.csv"
            output = root / "ready.csv"
            long_normalized = "a" * 256
            pending.write_text(
                HEADER
                + f"MAP_EXISTING,ing_pending_bad,Too Long,{long_normalized},1,,,,,\n"
                + "MAP_EXISTING,ing_pending_ok,Water,water,1,,,,,\n",
                encoding="utf-8-sig",
            )
            suggestions.write_text(
                SUGGESTION_HEADER
                + f"ing_pending_bad,{long_normalized},NO_EXACT_MATCH,,,\n"
                + "ing_pending_ok,water,NO_EXACT_MATCH,,,\n",
                encoding="utf-8-sig",
            )

            summary, excluded = generate_mapping_csv(
                pending_path=pending,
                suggestions_path=suggestions,
                output_path=output,
                excluded_count=1,
            )

        self.assertEqual(summary.output_rows, 1)
        self.assertEqual(excluded[0].pending_code, "ing_pending_bad")
        self.assertIn("255자 초과", excluded[0].reason)

    def test_rejects_missing_production_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pending = root / "pending.csv"
            suggestions = root / "suggestions.csv"
            pending.write_text(
                HEADER + "MAP_EXISTING,ing_pending_a,Water,water,1,,,,,\n",
                encoding="utf-8-sig",
            )
            suggestions.write_text(SUGGESTION_HEADER, encoding="utf-8-sig")

            with self.assertRaisesRegex(ValueError, "식별자가 일치하지 않습니다"):
                generate_mapping_csv(
                    pending_path=pending,
                    suggestions_path=suggestions,
                    output_path=root / "ready.csv",
                    excluded_count=0,
                )

    def test_same_pending_code_uses_one_canonical_definition(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pending = root / "pending.csv"
            suggestions = root / "suggestions.csv"
            output = root / "ready.csv"
            pending.write_text(
                HEADER
                + "MAP_EXISTING,ing_pending_a,Complex Blend,complexblend,1,,,,,\n"
                + "MAP_EXISTING,ing_pending_a,Complex  Blend,complexblend2,1,,,,,\n",
                encoding="utf-8-sig",
            )
            suggestions.write_text(
                SUGGESTION_HEADER
                + "ing_pending_a,complexblend,NO_EXACT_MATCH,,,\n"
                + "ing_pending_a,complexblend2,NO_EXACT_MATCH,,,\n",
                encoding="utf-8-sig",
            )

            generate_mapping_csv(
                pending_path=pending,
                suggestions_path=suggestions,
                output_path=output,
                excluded_count=0,
            )
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual({row["target_name_ko"] for row in rows}, {"Complex Blend"})
        self.assertEqual({row["target_ingredient_code"] for row in rows}, {"ing_generated_a"})


if __name__ == "__main__":
    unittest.main()
