from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.perf import inventory_benchmark_runs as inventory


class BenchmarkRunInventoryTests(unittest.TestCase):
    def test_identical_duplicate_runs_are_collapsed_for_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for parent in (root / "original", root / "archive"):
                run_dir = parent / "recommendation-1000-test-20260715-000000"
                run_dir.mkdir(parents=True)
                (run_dir / "manifest.json").write_text(
                    json.dumps({"run_id": "run-1"}),
                    encoding="utf-8",
                )
                (run_dir / "backend.log").write_text("same", encoding="utf-8")

            before = inventory.build_inventory(root)
            self.assertEqual(before["manifest_count"], 2)
            self.assertEqual(before["unique_run_count"], 1)
            self.assertTrue(before["duplicates"][0]["content_identical"])

            for path in (root / "archive").rglob("*"):
                if path.is_file():
                    path.unlink()
            for path in sorted((root / "archive").rglob("*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            (root / "archive").rmdir()

            after = inventory.build_inventory(root)
            result = inventory.verify_inventory(before, after)

        self.assertTrue(result["verified"])
        self.assertEqual(result["actual_unique_run_count"], 1)

    def test_changed_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "manifest.json").write_text(
                json.dumps({"run_id": "run-1"}),
                encoding="utf-8",
            )
            log_path = run_dir / "backend.log"
            log_path.write_text("before", encoding="utf-8")
            before = inventory.build_inventory(root)

            log_path.write_text("after", encoding="utf-8")
            after = inventory.build_inventory(root)
            result = inventory.verify_inventory(before, after)

        self.assertFalse(result["verified"])
        self.assertEqual(result["changed_run_ids"], ["run-1"])


if __name__ == "__main__":
    unittest.main()
