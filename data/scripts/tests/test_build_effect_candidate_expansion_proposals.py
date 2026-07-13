from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_effect_candidate_expansion_proposals import build_expansion_rows  # noqa: E402
from build_ingredient_role_inventory import CosingRecord  # noqa: E402


class BuildEffectCandidateExpansionProposalsTests(unittest.TestCase):
    def test_selects_exact_effect_candidates_until_target(self):
        proposals = [
            self._proposal("1", "pending_a", "candidate_a", "Candidate A", "100"),
            self._proposal("2", "pending_b", "candidate_b", "Candidate B", "200"),
            self._proposal("3", "pending_c", "candidate_c", "Candidate C", "300"),
        ]
        records = {
            "CANDIDATE A": self._record("CANDIDATE A", "HUMECTANT"),
            "CANDIDATE B": self._record(
                "CANDIDATE B", "SKIN CONDITIONING - EMOLLIENT"
            ),
            "CANDIDATE C": self._record("CANDIDATE C", "PRESERVATIVE"),
        }

        rows, stats = build_expansion_rows(
            proposals,
            records,
            current_candidate_count=1,
            target_candidate_count=2,
        )

        selected = [row for row in rows if row["selected_for_target"] == "Y"]
        self.assertEqual([row["proposed_canonical_id"] for row in selected], ["candidate_a"])
        self.assertEqual(stats["available_effect_candidates"], 2)
        self.assertEqual(stats["projected_effect_candidate_count"], 2)
        self.assertTrue(all(not row.get("effect_score") for row in rows))

    def test_selects_all_source_rows_for_same_canonical(self):
        proposals = [
            self._proposal("1", "pending_a", "candidate_a", "Candidate A", "100"),
            self._proposal("2", "pending_a2", "candidate_a", "Candidate A", "50"),
        ]
        records = {"CANDIDATE A": self._record("CANDIDATE A", "SOOTHING")}

        rows, stats = build_expansion_rows(
            proposals,
            records,
            current_candidate_count=0,
            target_candidate_count=1,
        )

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["selected_for_target"] == "Y" for row in rows))
        self.assertEqual(stats["selected_new_effect_candidates"], 1)
        self.assertEqual(stats["selected_source_rows"], 2)

    @staticmethod
    def _proposal(
        rank: str,
        source_id: str,
        canonical_id: str,
        name_en: str,
        product_count: str,
    ) -> dict[str, str]:
        return {
            "rank": rank,
            "source_ingredient_id": source_id,
            "dominant_name": name_en,
            "row_count": product_count,
            "product_count": product_count,
            "kcia_ingredient_code": rank,
            "kcia_standard_name_ko": canonical_id,
            "kcia_standard_name_en": name_en,
            "kcia_old_names_ko": "",
            "kcia_old_names_en": "",
            "official_match_status": "official_exact",
            "official_matched_row_count": product_count,
            "official_match_ratio": "1.000000",
            "official_conflict_codes": "",
            "proposed_action": "create_canonical",
            "proposed_canonical_id": canonical_id,
            "related_scoring_family_ids": "",
            "selected_for_target": "Y",
            "proposal_confidence": "high",
            "review_status": "accepted_auto_exact",
            "proposal_note": "test",
            "source_document_date": "2026-06-30",
            "source_document_sha256": "abc",
        }

    @staticmethod
    def _record(name: str, function: str) -> CosingRecord:
        return CosingRecord(
            inci_name=name,
            functions=(function,),
            restrictions=(),
            sccs_opinions=(),
            substance_ids=(name,),
        )


if __name__ == "__main__":
    unittest.main()
