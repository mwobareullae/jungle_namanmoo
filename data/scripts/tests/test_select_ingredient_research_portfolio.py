from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from select_ingredient_research_portfolio import build_portfolio  # noqa: E402


class SelectIngredientResearchPortfolioTests(unittest.TestCase):
    def test_keeps_runtime_and_uses_best_paper_not_paper_count(self):
        roles = [
            self._role("runtime", 1, "effect_calming"),
            self._role("strong", 10_000, ""),
            self._role("many_weak", 20_000, ""),
        ]
        screening = [
            self._screen("runtime", "effect_calming", "current", "", ""),
            self._screen("strong", "effect_calming", "high", "2", "90"),
            self._screen("many_weak", "effect_calming", "high", "8", "10", pmid="2"),
            self._screen("many_weak", "effect_moisture_barrier", "high", "8", "10", pmid="3"),
        ]

        portfolio, pairs = build_portfolio(roles, screening, target_count=2)

        selected = [row["ingredient_id"] for row in portfolio if row["selected_for_portfolio"] == "Y"]
        self.assertEqual(selected, ["runtime", "strong"])
        self.assertEqual(len(pairs), 2)
        self.assertEqual(portfolio[1]["best_signal_score"], 90)

    def test_keeps_every_candidate_tied_at_operational_target_boundary(self):
        roles = [
            self._role("a", 100, ""),
            self._role("b", 100, ""),
            self._role("c", 100, ""),
        ]
        screening = [
            self._screen(ingredient_id, "effect_calming", "high", "2", "90")
            for ingredient_id in ("a", "b", "c")
        ]

        portfolio, _ = build_portfolio(roles, screening, target_count=2)

        selected = [row["ingredient_id"] for row in portfolio if row["selected_for_portfolio"] == "Y"]
        self.assertEqual(selected, ["a", "b", "c"])

    @staticmethod
    def _role(ingredient_id: str, product_count: int, current_effect_ids: str) -> dict[str, str]:
        return {
            "ingredient_id": ingredient_id,
            "name_ko": ingredient_id,
            "name_en": ingredient_id,
            "product_count": str(product_count),
            "current_effect_ids": current_effect_ids,
            "role_effect_candidate": "Y",
        }

    @staticmethod
    def _screen(
        ingredient_id: str,
        effect_id: str,
        strength: str,
        tier: str,
        signal: str,
        *,
        pmid: str = "1",
    ) -> dict[str, str]:
        return {
            "ingredient_id": ingredient_id,
            "effect_id": effect_id,
            "effect_name": effect_id,
            "selection_policy": "existing_runtime" if strength == "current" else "paper",
            "signal_strength": strength,
            "signal_functions": "SOOTHING",
            "best_evidence_tier": tier,
            "best_signal_score": signal or "0",
            "best_relation_scope": "title_exact" if tier else "",
            "best_applicability": "human_topical" if tier else "",
            "best_pmid": pmid if tier else "",
            "best_title": "Paper" if tier else "",
            "screening_status": "existing_runtime" if strength == "current" else f"evidence_tier_{tier}",
            "review_status": "existing_runtime" if strength == "current" else "candidate_unverified",
        }


if __name__ == "__main__":
    unittest.main()
