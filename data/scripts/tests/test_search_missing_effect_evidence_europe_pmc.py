from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from search_missing_effect_evidence_europe_pmc import (  # noqa: E402
    EuropePmcPaper,
    build_europe_pmc_query,
    search_europe_pmc_pairs,
)


class FakeClient:
    request_count = 0
    retry_count = 0

    def search(self, query, *, page_size):
        self.request_count += 1
        return 2, [
            EuropePmcPaper(
                source="PPR",
                source_id="PPR1",
                pmid="",
                pmcid="",
                doi="10.1000/test",
                title="Topical sodium lactate for dry skin",
                abstract="Sodium lactate increased skin hydration after topical application.",
                publication_types=("Preprint",),
            ),
            EuropePmcPaper(
                source="AGR",
                source_id="AGR1",
                pmid="",
                pmcid="",
                doi="",
                title="Sodium lactate in sausage production",
                abstract="Moisture retention increased in food.",
                publication_types=("Journal Article",),
            ),
        ]


class SearchMissingEffectEvidenceEuropePmcTests(unittest.TestCase):
    def test_query_excludes_pubmed_source(self):
        query = build_europe_pmc_query(
            ["Sodium Lactate"],
            ["effect_moisture_barrier"],
        )

        self.assertIn('TITLE_ABS:"Sodium Lactate"', query)
        self.assertIn("NOT SRC:MED", query)
        self.assertIn("NOT SRC:PAT", query)

    def test_non_pubmed_exact_skin_effect_candidate_is_retained(self):
        rows = search_europe_pmc_pairs(
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
            page_size=100,
        )

        self.assertEqual(rows[0]["matched_paper_count"], 1)
        self.assertEqual(rows[0]["best_paper_key"], "DOI:10.1000/test")
        self.assertEqual(rows[0]["review_status"], "candidate_unverified")


if __name__ == "__main__":
    unittest.main()
