from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from build_ingredient_first_paper_catalog import (  # noqa: E402
    build_catalog,
    build_ingredient_skin_query,
    extract_outcomes,
    select_top_ingredients,
)
from discover_new_evidence import PaperMetadata  # noqa: E402
from screen_effect_review_candidates import assess_paper_candidate  # noqa: E402


class FakeClient:
    request_count = 0
    retry_count = 0

    def search(self, query, *, window_start, window_end, retmax, sort="pub_date"):
        self.request_count += 1
        return ["1", "2", "3", "4"]

    def fetch(self, pmids):
        self.request_count += 1
        return {
            "1": PaperMetadata(
                pmid="1",
                title="Topical niacinamide improves skin barrier function",
                publication_types=("Clinical Trial",),
                abstract="Adults applied niacinamide cream. RESULTS: Skin hydration improved and transepidermal water loss decreased.",
            ),
            "2": PaperMetadata(
                pmid="2",
                title="Topical niacinamide supports wound healing",
                publication_types=("Clinical Trial",),
                abstract="RESULTS: Niacinamide treatment accelerated skin wound healing.",
            ),
            "3": PaperMetadata(
                pmid="3",
                title="Niacinamide antioxidant mechanisms in keratinocytes",
                abstract="Niacinamide reduced oxidative stress in skin keratinocyte cell culture.",
            ),
            "4": PaperMetadata(
                pmid="4",
                title="Niacinamide analytical reference method",
                abstract="The assay showed improved laboratory precision.",
            ),
        }


class RoleClient(FakeClient):
    def fetch(self, pmids):
        self.request_count += 1
        return {
            "1": PaperMetadata(
                pmid="1",
                title="Topical butylene glycol improves skin hydration",
                publication_types=("Clinical Trial",),
                abstract="Butylene glycol reduced dry skin in adult volunteers.",
            ),
            "2": PaperMetadata(
                pmid="2",
                title="A butylene glycol combination moisturizer for dry skin",
                publication_types=("Clinical Trial",),
                abstract=(
                    "Patients applied a cream containing butylene glycol. "
                    "RESULTS: The formulation improved skin hydration."
                ),
            ),
            "3": PaperMetadata(
                pmid="3",
                title="Butylene glycol contact dermatitis and skin irritation",
                abstract="Patch test safety findings were reported.",
            ),
            "4": PaperMetadata(
                pmid="4",
                title="Butylene glycol analytical reference method",
                abstract="The laboratory assay improved measurement precision.",
            ),
        }


class BuildIngredientFirstPaperCatalogTests(unittest.TestCase):
    def test_selects_top_ingredients_by_product_usage(self):
        rows = [
            {"ingredient_id": "b", "product_count": "5"},
            {"ingredient_id": "a", "product_count": "10"},
            {"ingredient_id": "c", "product_count": "1"},
        ]

        selected = select_top_ingredients(rows, target_count=2)

        self.assertEqual([row["ingredient_id"] for row in selected], ["a", "b"])

    def test_query_uses_ingredient_and_skin_terms_without_effect_axis(self):
        query = build_ingredient_skin_query(["Niacinamide", "Nicotinamide"])

        self.assertIn('"Niacinamide"[Title/Abstract]', query)
        self.assertIn('"skin"[Title/Abstract]', query)
        self.assertNotIn("effect_moisture_barrier", query)

    def test_outcomes_map_existing_new_and_mechanism_after_paper_selection(self):
        papers = FakeClient().fetch([])
        existing = extract_outcomes(
            papers["1"],
            assess_paper_candidate(papers["1"], ["Niacinamide"]),
            ["Niacinamide"],
        )
        new_effect = extract_outcomes(
            papers["2"],
            assess_paper_candidate(papers["2"], ["Niacinamide"]),
            ["Niacinamide"],
        )
        mechanism = extract_outcomes(
            papers["3"],
            assess_paper_candidate(papers["3"], ["Niacinamide"]),
            ["Niacinamide"],
        )

        self.assertTrue(any(row["mapping_status"] == "mapped_existing_effect" for row in existing))
        self.assertTrue(any(row["new_effect_candidate"] == "wound_healing" for row in new_effect))
        self.assertTrue(all(row["mapping_status"] == "mechanism_only" for row in mechanism))

    def test_mixed_method_paper_keeps_human_clinical_outcome(self):
        paper = PaperMetadata(
            pmid="12100180",
            title="The effect of niacinamide on reducing cutaneous pigmentation",
            publication_types=("Randomized Controlled Trial",),
            abstract=(
                "Niacinamide inhibited melanosome transfer in a coculture model. "
                "RESULTS: In the clinical study, topical niacinamide significantly "
                "decreased hyperpigmentation and increased skin lightness compared "
                "with vehicle alone."
            ),
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Niacinamide"]),
            ["Niacinamide"],
        )

        clinical = [
            row
            for row in rows
            if "hyperpigmentation" in row["evidence_span"].casefold()
        ]
        self.assertTrue(clinical)
        self.assertEqual(clinical[0]["mapping_status"], "mapped_existing_effect")
        self.assertEqual(clinical[0]["direction"], "positive")

    def test_food_skin_and_formulation_mentions_are_not_direct_outcomes(self):
        food = PaperMetadata(
            pmid="5",
            title="Sodium lactate film for beef bologna",
            abstract=(
                "Sodium lactate in chicken skin gelatin improved antimicrobial "
                "food packaging performance."
            ),
        )
        formulation = PaperMetadata(
            pmid="6",
            title="Compound heparin sodium allantoin gel improves skin redness",
            abstract="The compound formulation reduced facial skin erythema.",
        )

        food_rows = extract_outcomes(
            food,
            assess_paper_candidate(food, ["Sodium lactate"]),
            ["Sodium lactate"],
        )
        formulation_rows = extract_outcomes(
            formulation,
            assess_paper_candidate(formulation, ["Allantoin"]),
            ["Allantoin"],
        )

        self.assertTrue(food_rows)
        self.assertTrue(formulation_rows)
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in food_rows))
        self.assertTrue(
            all(row["ingredient_outcome_relation"] == "formulation_limited" for row in formulation_rows)
        )

    def test_constituent_list_does_not_create_new_effect_candidate(self):
        paper = PaperMetadata(
            pmid="7",
            title="Snail mucin and skin wound healing",
            publication_types=("Review",),
            abstract=(
                "Snail mucin may improve skin wound healing due to bioactive "
                "compounds like allantoin and glycolic acid."
            ),
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Allantoin"]),
            ["Allantoin"],
        )

        self.assertTrue(rows)
        self.assertTrue(all(row["new_effect_candidate"] == "" for row in rows))
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in rows))

    def test_measured_ingredient_level_is_not_treated_as_applied_ingredient(self):
        paper = PaperMetadata(
            pmid="8",
            title="A moisturizer for sensitive skin",
            abstract=(
                "RESULTS: The moisturizer increased hyaluronic acid levels and "
                "improved skin barrier function."
            ),
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Hyaluronic acid"]),
            ["Hyaluronic acid"],
        )

        self.assertTrue(rows)
        self.assertTrue(all(row["ingredient_outcome_relation"] == "contextual_mention" for row in rows))
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in rows))

    def test_exact_ingredient_as_result_subject_remains_direct(self):
        paper = PaperMetadata(
            pmid="9",
            title="A topical treatment study",
            publication_types=("Clinical Trial",),
            abstract="RESULTS: Niacinamide reduced facial skin pigmentation.",
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Niacinamide"]),
            ["Niacinamide"],
        )

        self.assertEqual(rows[0]["ingredient_outcome_relation"], "direct")
        self.assertEqual(rows[0]["mapping_status"], "mapped_existing_effect")

    def test_outcome_direction_preserves_same_effect_conflict(self):
        paper = PaperMetadata(
            pmid="901",
            title="A topical niacinamide treatment study",
            publication_types=("Clinical Trial",),
            abstract=(
                "RESULTS: Niacinamide decreased TEWL and decreased skin hydration."
            ),
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Niacinamide"]),
            ["Niacinamide"],
        )
        payload = json.loads(rows[0]["direction_by_effect_json"])

        self.assertEqual(rows[0]["direction"], "unclear")
        self.assertEqual(rows[0]["direction_conflict"], "Y")
        self.assertEqual(rows[0]["direction_policy_version"], "mwbl-effect-direction-v1")
        self.assertTrue(payload["effect_moisture_barrier"]["conflict"])

    def test_longest_exact_alias_is_not_mistaken_for_modified_form(self):
        paper = PaperMetadata(
            pmid="10",
            title="Alpha-Bisabolol reduces facial skin redness",
            abstract="Alpha-Bisabolol reduced skin erythema.",
        )

        rows = extract_outcomes(
            paper,
            assess_paper_candidate(paper, ["Bisabolol", "Alpha-Bisabolol"]),
            ["Bisabolol", "Alpha-Bisabolol"],
        )

        self.assertTrue(rows)
        self.assertTrue(
            all(row["ingredient_outcome_relation"] == "review_summary" for row in rows)
        )

    def test_component_form_and_multi_filter_sunscreen_are_limited(self):
        component = PaperMetadata(
            pmid="11",
            title="Green tea polyphenols protect skin from ultraviolet exposure",
            abstract="Green tea polyphenols improved skin photoprotection.",
        )
        sunscreen = PaperMetadata(
            pmid="12",
            title="Photoprotection review",
            publication_types=("Review",),
            abstract=(
                "Sunscreen based on titanium dioxide and zinc oxide improved "
                "UV protection on skin."
            ),
        )

        component_rows = extract_outcomes(
            component,
            assess_paper_candidate(component, ["Green tea"]),
            ["Green tea"],
        )
        sunscreen_rows = extract_outcomes(
            sunscreen,
            assess_paper_candidate(sunscreen, ["Titanium dioxide"]),
            ["Titanium dioxide"],
        )

        self.assertTrue(component_rows)
        self.assertTrue(sunscreen_rows)
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in component_rows))
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in sunscreen_rows))

    def test_greek_prefixed_derivative_and_pronoun_clause_are_not_direct(self):
        derivative = PaperMetadata(
            pmid="13",
            title="Poly (γ-glutamic acid) improves skin wound healing",
            abstract="Poly (γ-glutamic acid) accelerated skin wound healing.",
        )
        pronoun = PaperMetadata(
            pmid="14",
            title="Cellulose treatments in skin keratinocytes",
            abstract=(
                "Treatments did not affect cellulose; in addition, they showed "
                "improved antimicrobial activity toward skin keratinocytes."
            ),
        )

        derivative_rows = extract_outcomes(
            derivative,
            assess_paper_candidate(derivative, ["Glutamic acid"]),
            ["Glutamic acid"],
        )
        pronoun_rows = extract_outcomes(
            pronoun,
            assess_paper_candidate(pronoun, ["Cellulose"]),
            ["Cellulose"],
        )

        self.assertTrue(derivative_rows)
        self.assertTrue(pronoun_rows)
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in derivative_rows))
        self.assertTrue(all(row["mapping_status"] == "unclear" for row in pronoun_rows))

    def test_catalog_selects_at_most_three_useful_papers(self):
        targets, papers, outcomes, summaries, screening = build_catalog(
            ingredient_rows=[
                {
                    "ingredient_id": "niacinamide",
                    "name_ko": "나이아신아마이드",
                    "name_en": "Niacinamide",
                    "product_count": "100",
                }
            ],
            ingredient_terms={"niacinamide": ["Niacinamide"]},
            client=FakeClient(),
            as_of=date(2026, 7, 12),
            retmax_per_ingredient=50,
            max_papers_per_ingredient=3,
        )

        self.assertEqual(targets[0]["selected_paper_count"], 3)
        self.assertEqual(len(papers), 3)
        self.assertTrue(outcomes)
        self.assertEqual(summaries[0]["new_effect_candidate"], "wound_healing")
        self.assertEqual(len(screening), 4)

    def test_catalog_keeps_direct_formulation_and_safety_but_not_unrelated(self):
        _, papers, _, _, screening = build_catalog(
            ingredient_rows=[
                {
                    "ingredient_id": "butylene_glycol",
                    "name_ko": "부틸렌글라이콜",
                    "name_en": "Butylene Glycol",
                    "product_count": "100",
                }
            ],
            ingredient_terms={"butylene_glycol": ["Butylene Glycol"]},
            client=RoleClient(),
            as_of=date(2026, 7, 12),
            retmax_per_ingredient=50,
            max_papers_per_ingredient=3,
        )

        roles = {role for row in papers for role in row["evidence_roles"].split("|")}
        screened_by_pmid = {row["pmid"]: row for row in screening}
        self.assertIn("direct_effect", roles)
        self.assertIn("formulation_evidence", roles)
        self.assertIn("safety_evidence", roles)
        self.assertEqual(screened_by_pmid["4"]["review_status"], "screened_out")
        self.assertEqual(screened_by_pmid["4"]["selected_representative"], "N")


if __name__ == "__main__":
    unittest.main()
