from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from select_ingredient_canonicalization_coverage_batch import (  # noqa: E402
    select_coverage_batch,
)


class SelectIngredientCanonicalizationCoverageBatchTests(unittest.TestCase):
    def test_selects_safe_rows_by_rank_until_target_is_met(self):
        rows = [
            self._row("1", "40", "official_exact", "create_canonical", "high", "100"),
            self._row("2", "50", "no_official_exact_match", "manual_review", "low", ""),
            self._row("3", "25", "official_exact", "merge_existing", "high", "200"),
            self._row("4", "30", "official_exact", "create_canonical", "high", "300"),
        ]

        selected, stats = select_coverage_batch(
            rows,
            total_product_ingredient_rows=200,
            effective_canonical_rows=95,
            target_coverage_pct=75,
        )

        self.assertEqual([row["selected_for_target"] for row in selected], ["Y", "N", "Y", "N"])
        self.assertEqual(stats.selected_rows, 2)
        self.assertEqual(stats.selected_source_rows, 65)
        self.assertEqual(stats.selected_new_canonical, 1)
        self.assertEqual(stats.last_selected_rank, 3)
        self.assertEqual(stats.projected_coverage_pct, 80.0)
        self.assertEqual(selected[3]["review_status"], "candidate_unverified")

    @staticmethod
    def _row(
        rank: str,
        row_count: str,
        status: str,
        action: str,
        confidence: str,
        code: str,
    ) -> dict[str, str]:
        return {
            "rank": rank,
            "row_count": row_count,
            "official_match_status": status,
            "proposed_action": action,
            "proposal_confidence": confidence,
            "proposed_canonical_id": f"canonical_{rank}" if code else "",
            "kcia_ingredient_code": code,
            "selected_for_target": "Y",
            "review_status": "accepted_auto_exact",
        }


if __name__ == "__main__":
    unittest.main()
