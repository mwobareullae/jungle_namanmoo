from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts.perf import build_benchmark_dataset as builder


class BenchmarkDatasetBuilderTests(unittest.TestCase):
    def test_copies_llm_prompt_and_schema_support_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            output_root = root / "output"
            source_dir.mkdir()

            (source_dir / "products.csv").write_text(
                "product_id,brand_name,product_name\n"
                "prod_001,brand-a,product-a\n",
                encoding="utf-8",
            )
            (source_dir / "product_prices.csv").write_text(
                "product_id,price\n"
                "prod_001,1000\n",
                encoding="utf-8",
            )
            (source_dir / "prompts").mkdir()
            (source_dir / "prompts" / "concern_parser_system_prompt.md").write_text(
                "system prompt",
                encoding="utf-8",
            )
            (source_dir / "schemas").mkdir()
            (source_dir / "schemas" / "concern_parser_output_schema.openai.json").write_text(
                '{"name":"concern_parser_output"}',
                encoding="utf-8",
            )

            product_headers, product_rows = builder.read_rows(builder.product_files(source_dir))
            with contextlib.redirect_stdout(io.StringIO()):
                builder.build_dataset(
                    source_dir=source_dir,
                    output_root=output_root,
                    size=1,
                    product_headers=product_headers,
                    product_rows=product_rows,
                    overwrite=False,
                    allow_shortfall=False,
                )

            dataset_dir = output_root / "benchmark-1"
            self.assertEqual(
                (dataset_dir / "prompts" / "concern_parser_system_prompt.md").read_text(
                    encoding="utf-8",
                ),
                "system prompt",
            )
            self.assertTrue(
                (
                    dataset_dir
                    / "schemas"
                    / "concern_parser_output_schema.openai.json"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
