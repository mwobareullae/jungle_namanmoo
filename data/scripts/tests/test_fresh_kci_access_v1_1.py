from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fresh_kci_access_v1_1 import build_rows, robots_allows  # noqa: E402
from fresh_pubmed_search_v1_1 import TermProvenance  # noqa: E402


ROBOTS = """User-agent: googlebot
Allow: /

User-agent: *
Disallow: /
"""


class FreshKciAccessV11Tests(unittest.TestCase):
    def test_robots_blocks_configured_non_google_collector(self) -> None:
        self.assertFalse(robots_allows(ROBOTS))

    def test_access_row_is_explicit_and_not_a_false_zero_hit(self) -> None:
        rows = build_rows(
            [{"ingredient_rank": "1", "ingredient_id": "niacinamide", "name_ko": "나이아신아마이드"}],
            {"niacinamide": [TermProvenance("Niacinamide", "canonical_name_en")]},
            ROBOTS,
            "2026-07-13T00:00:00Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_status"], "access_unavailable")
        self.assertEqual(rows[0]["raw_hit_count"], "")
        self.assertEqual(rows[0]["returned_count"], 0)
        self.assertEqual(rows[0]["rerun_required"], "N")
        self.assertEqual(rows[0]["runtime_score_change"], "none")


if __name__ == "__main__":
    unittest.main()
