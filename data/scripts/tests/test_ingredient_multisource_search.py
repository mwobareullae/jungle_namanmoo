from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from prepare_ingredient_multisource_targets import prepare_targets  # noqa: E402
from discover_new_evidence import PaperMetadata  # noqa: E402
from evaluate_ingredient_multisource_funnel import (  # noqa: E402
    CandidatePaper,
    evaluate_funnel,
    merge_candidate_papers,
)
from search_ingredient_evidence_multisource import (  # noqa: E402
    _crossref_date,
    europe_pmc_query,
    preferred_search_term,
    reconstruct_openalex_abstract,
)


class IngredientMultisourceSearchTests(unittest.TestCase):
    def test_prepare_targets_excludes_only_unconfirmed_pubmed_ingredient(self):
        targets = [
            {
                "ingredient_rank": "1",
                "ingredient_id": "a",
                "name_ko": "A",
                "name_en": "A",
                "product_count": "3",
                "raw_pubmed_hit_count": "2",
            },
            {
                "ingredient_rank": "2",
                "ingredient_id": "b",
                "name_ko": "B",
                "name_en": "B",
                "product_count": "2",
                "raw_pubmed_hit_count": "1",
            },
            {
                "ingredient_rank": "3",
                "ingredient_id": "c",
                "name_ko": "C",
                "name_en": "C",
                "product_count": "1",
                "raw_pubmed_hit_count": "0",
            },
        ]
        screening = [
            {"ingredient_id": "a", "relation_scope": "unconfirmed"},
            {"ingredient_id": "a", "relation_scope": "unconfirmed"},
            {"ingredient_id": "b", "relation_scope": "abstract_exact"},
        ]

        kept, excluded = prepare_targets(targets, screening)

        self.assertEqual([row["ingredient_id"] for row in kept], ["b", "c"])
        self.assertEqual([row["ingredient_id"] for row in excluded], ["a"])

    def test_openalex_abstract_is_reconstructed_in_word_order(self):
        abstract = reconstruct_openalex_abstract(
            {"Skin": [0], "hydration": [2], "improved": [1]}
        )

        self.assertEqual(abstract, "Skin improved hydration")

    def test_preferred_term_avoids_parenthetical_inci_when_alias_exists(self):
        term = preferred_search_term(
            {
                "name_en": "Melaleuca Alternifolia (Tea Tree) Leaf Oil",
                "search_terms": "Melaleuca Alternifolia (Tea Tree) Leaf Oil|Tea Tree Oil",
            }
        )

        self.assertEqual(term, "Tea Tree Oil")

    def test_europe_pmc_query_excludes_pubmed_and_patents(self):
        query = europe_pmc_query(
            {"search_terms": "Niacinamide|Nicotinamide"}
        )

        self.assertIn('TITLE_ABS:"Niacinamide"', query)
        self.assertIn("NOT SRC:MED", query)
        self.assertIn("NOT SRC:PAT", query)

    def test_crossref_date_ignores_null_date_parts(self):
        value = _crossref_date(
            {"published-online": {"date-parts": [[2024, None, None]]}}
        )

        self.assertEqual(value, "2024")

    def test_duplicate_pmid_and_doi_are_merged_across_sources(self):
        rows = [
            CandidatePaper(
                "niacinamide",
                ("pubmed",),
                PaperMetadata(
                    pmid="1",
                    doi="10.1000/test",
                    title="Topical niacinamide trial",
                    abstract="Long abstract text.",
                ),
            ),
            CandidatePaper(
                "niacinamide",
                ("crossref",),
                PaperMetadata(
                    pmid="",
                    doi="10.1000/test",
                    title="Topical niacinamide trial",
                ),
            ),
        ]

        merged = merge_candidate_papers(rows)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].sources, ("crossref", "pubmed"))
        self.assertEqual(merged[0].metadata.abstract, "Long abstract text.")

    def test_funnel_passes_direct_human_topical_positive_trial(self):
        target = {
            "ingredient_rank": "1",
            "ingredient_id": "niacinamide",
            "name_ko": "나이아신아마이드",
            "name_en": "Niacinamide",
            "product_count": "100",
        }
        paper = CandidatePaper(
            "niacinamide",
            ("pubmed",),
            PaperMetadata(
                pmid="2",
                title="Topical niacinamide improves skin hydration in adults",
                publication_types=("Randomized Controlled Trial",),
                abstract=(
                    "Adults applied niacinamide cream in a randomized trial. "
                    "RESULTS: Skin hydration significantly improved (p < 0.05)."
                ),
            ),
        )

        ingredients, _, funnel, summary = evaluate_funnel(
            targets=[target],
            candidates=[paper],
            ingredient_terms={"niacinamide": ["Niacinamide"]},
        )

        self.assertEqual(ingredients[0]["final_score_candidate"], "Y")
        self.assertEqual(summary["final_score_candidate_count"], 1)
        self.assertEqual(funnel[-1]["remaining_ingredient_count"], 1)

    def test_combination_product_fails_before_effect_scoring(self):
        target = {
            "ingredient_rank": "1",
            "ingredient_id": "niacinamide",
            "name_ko": "나이아신아마이드",
            "name_en": "Niacinamide",
            "product_count": "100",
        }
        paper = CandidatePaper(
            "niacinamide",
            ("crossref",),
            PaperMetadata(
                pmid="",
                doi="10.1000/combo",
                title="A niacinamide combination cream for dry skin",
                publication_types=("Clinical Trial",),
                abstract=(
                    "Patients applied a multi-ingredient niacinamide cream. "
                    "RESULTS: The formulation improved skin hydration."
                ),
            ),
        )

        ingredients, _, _, _ = evaluate_funnel(
            targets=[target],
            candidates=[paper],
            ingredient_terms={"niacinamide": ["Niacinamide"]},
        )

        self.assertEqual(
            ingredients[0]["first_failed_filter"],
            "not_combination_product",
        )

    def test_preprint_cannot_be_a_standalone_score_candidate(self):
        target = {
            "ingredient_rank": "1",
            "ingredient_id": "niacinamide",
            "name_ko": "나이아신아마이드",
            "name_en": "Niacinamide",
            "product_count": "100",
        }
        paper = CandidatePaper(
            "niacinamide",
            ("europe_pmc",),
            PaperMetadata(
                pmid="5",
                title="Topical niacinamide improves skin hydration in adults",
                publication_types=("Preprint",),
                abstract=(
                    "Adults applied niacinamide cream. RESULTS: Skin hydration "
                    "significantly improved (p < 0.05)."
                ),
            ),
        )

        ingredients, _, _, _ = evaluate_funnel(
            targets=[target],
            candidates=[paper],
            ingredient_terms={"niacinamide": ["Niacinamide"]},
        )

        self.assertEqual(
            ingredients[0]["first_failed_filter"],
            "standalone_evidence_tier",
        )


if __name__ == "__main__":
    unittest.main()
