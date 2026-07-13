from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from discover_new_evidence import PaperMetadata  # noqa: E402
from search_missing_effect_evidence import (  # noqa: E402
    build_expanded_query,
    search_missing_pairs,
)


class FakeClient:
    request_count = 0
    retry_count = 0

    def search(self, query, *, window_start, window_end, retmax):
        self.request_count += 1
        return ["1", "2", "3"]

    def fetch(self, pmids):
        self.request_count += 1
        return {
            "1": PaperMetadata(
                pmid="1",
                title="Sodium lactate improves dry skin",
                publication_types=("Clinical Trial",),
                abstract="Adults applied a topical lotion and skin water content increased.",
            ),
            "2": PaperMetadata(
                pmid="2",
                title="Sodium lactate analytical chemistry",
                abstract="A laboratory reference method without dermatologic outcomes.",
            ),
            "3": PaperMetadata(
                pmid="3",
                title="Sodium lactate and intestinal barrier function",
                abstract="The treatment increased intestinal hydration in mice.",
            ),
        }


class SearchMissingEffectEvidenceTests(unittest.TestCase):
    def test_query_relaxes_redundant_effect_and_skin_intersection(self):
        query = build_expanded_query(["Sodium Lactate"], ["effect_moisture_barrier"])

        self.assertIn('"Sodium Lactate"[Title/Abstract]', query)
        self.assertIn('"dry skin"[Title/Abstract]', query)
        self.assertNotIn(") AND (\"dry skin\"", query)

    def test_finds_only_exact_ingredient_and_effect_matched_paper(self):
        rows = search_missing_pairs(
            pair_rows=[
                {
                    "ingredient_id": "sodium_lactate",
                    "name_ko": "소듐락테이트",
                    "name_en": "Sodium Lactate",
                    "effect_id": "effect_moisture_barrier",
                }
            ],
            ingredient_terms={"sodium_lactate": ["Sodium Lactate"]},
            client=FakeClient(),
            as_of=date(2026, 7, 12),
            retmax_per_ingredient=100,
        )

        self.assertEqual(rows[0]["second_pass_status"], "expanded_candidate_found")
        self.assertEqual(rows[0]["best_pmid"], "1")
        self.assertEqual(rows[0]["matched_paper_count"], 1)
        self.assertEqual(rows[0]["review_status"], "candidate_unverified")
        self.assertEqual(rows[0]["score_change"], "none")


if __name__ == "__main__":
    unittest.main()
