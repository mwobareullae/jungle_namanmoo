from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from discover_new_evidence import PaperMetadata  # noqa: E402
from screen_effect_review_candidates import (  # noqa: E402
    PairCandidate,
    assess_paper_candidate,
    is_human_topical_focused,
    screen_candidates,
)


class FakeClient:
    request_count = 0
    retry_count = 0

    def __init__(self, pmids, papers):
        self.pmids = pmids
        self.papers = papers

    def search(self, query, *, window_start, window_end, retmax):
        self.request_count += 1
        return list(self.pmids)

    def fetch(self, pmids):
        self.request_count += 1
        return {pmid: self.papers[pmid] for pmid in pmids}


class ScreenEffectReviewCandidatesTests(unittest.TestCase):
    def test_human_topical_title_focused_paper_qualifies(self):
        paper = PaperMetadata(
            pmid="1",
            title="Topical Sodium Lactate Improves Skin Hydration",
            publication_types=("Clinical Trial",),
            abstract="Twenty adult volunteers applied the lotion to the forearm.",
        )

        self.assertTrue(is_human_topical_focused(paper, ["Sodium Lactate"]))
        assessment = assess_paper_candidate(paper, ["Sodium Lactate"])
        self.assertEqual(assessment.evidence_tier, 3)
        self.assertEqual(assessment.relation_scope, "title_exact")

    def test_formulation_mention_in_abstract_is_retained_with_limitation(self):
        paper = PaperMetadata(
            pmid="1",
            title="A Moisturizer for Atopic Dermatitis",
            publication_types=("Clinical Trial",),
            abstract="Patients applied a cream containing butylene glycol.",
        )

        assessment = assess_paper_candidate(paper, ["Butylene Glycol"])
        self.assertEqual(assessment.evidence_tier, 3)
        self.assertEqual(assessment.relation_scope, "abstract_exact")
        self.assertEqual(assessment.applicability, "combination_or_formulation")

    def test_formulation_language_from_audit_is_not_treated_as_single_ingredient(self):
        for marker in ("enriched", "adjuvant", "loaded", "3-in-1", "multi-modal"):
            with self.subTest(marker=marker):
                paper = PaperMetadata(
                    pmid="1",
                    title=f"A {marker} topical cream study",
                    publication_types=("Randomized Controlled Trial",),
                    abstract="Adult participants applied a Centella Asiatica cream to the skin.",
                )
                assessment = assess_paper_candidate(paper, ["Centella Asiatica"])
                self.assertEqual(assessment.applicability, "combination_or_formulation")

    def test_oral_or_injectable_title_does_not_qualify_as_topical(self):
        oral = PaperMetadata(
            pmid="1",
            title="Histidine Supplementation in Adults With Atopic Dermatitis",
            publication_types=("Clinical Trial",),
            abstract="Patients also used a topical cream during the study.",
        )
        injectable = PaperMetadata(
            pmid="2",
            title="Injectable Hyaluronic Acid for Facial Rejuvenation",
            publication_types=("Clinical Trial",),
            abstract="Adult subjects received treatment to the face.",
        )

        self.assertFalse(is_human_topical_focused(oral, ["Histidine"]))
        self.assertFalse(is_human_topical_focused(injectable, ["Hyaluronic Acid"]))

    def test_review_and_adult_animal_study_do_not_qualify(self):
        review = PaperMetadata(
            pmid="1",
            title="Topical Sulfur for Acne",
            publication_types=("Review",),
            abstract="Randomized clinical trials in patients used topical cream preparations.",
        )
        animal = PaperMetadata(
            pmid="2",
            title="Topical Sodium Lactate in Adult Mice",
            publication_types=("Journal Article",),
            abstract="Adult mice received topical lotion on the skin.",
        )

        self.assertFalse(is_human_topical_focused(review, ["Sulfur"]))
        self.assertEqual(assess_paper_candidate(review, ["Sulfur"]).evidence_tier, 8)
        self.assertFalse(is_human_topical_focused(animal, ["Sodium Lactate"]))

    def test_animal_signal_wins_over_ambiguous_subject_wording(self):
        paper = PaperMetadata(
            pmid="3",
            title="Topical Geraniol in Mice With Atopic Dermatitis",
            publication_types=("Journal Article",),
            abstract=(
                "The subjects received geraniol lotion on the skin and inflammation decreased."
            ),
        )

        assessment = assess_paper_candidate(paper, ["Geraniol"])

        self.assertEqual(assessment.evidence_tier, 6)
        self.assertEqual(assessment.evidence_kind, "animal")
        self.assertFalse(is_human_topical_focused(paper, ["Geraniol"]))

    def test_direct_signal_is_searched_and_retained_as_cosing_only_without_paper(self):
        candidate = PairCandidate(
            ingredient_id="alpha_arbutin",
            name_en="Alpha-Arbutin",
            effect_id="effect_brightening",
            signal_strength="high",
            signal_functions=("BLEACHING",),
            selection_policy="direct_cosing_signal",
        )
        client = FakeClient([], {})

        rows = screen_candidates(
            candidates=[candidate],
            ingredient_terms={"alpha_arbutin": ["Alpha-Arbutin"]},
            client=client,
            as_of=date(2026, 7, 12),
            retmax_per_pair=20,
        )

        self.assertEqual(rows[0]["selected_for_paper_review"], "Y")
        self.assertEqual(rows[0]["screening_status"], "cosing_only")
        self.assertEqual(client.request_count, 1)

    def test_conditional_signal_requires_qualified_paper(self):
        candidate = PairCandidate(
            ingredient_id="sodium_lactate",
            name_en="Sodium Lactate",
            effect_id="effect_exfoliation",
            signal_strength="high",
            signal_functions=("KERATOLYTIC",),
            selection_policy="human_topical_pubmed_required",
        )
        paper = PaperMetadata(
            pmid="1",
            title="Topical Sodium Lactate and Skin Roughness",
            publication_types=("Clinical Trial",),
            abstract="Adult subjects applied the lotion to each forearm.",
        )
        client = FakeClient(["1"], {"1": paper})

        rows = screen_candidates(
            candidates=[candidate],
            ingredient_terms={"sodium_lactate": ["Sodium Lactate"]},
            client=client,
            as_of=date(2026, 7, 12),
            retmax_per_pair=20,
        )

        self.assertEqual(rows[0]["selected_for_paper_review"], "Y")
        self.assertEqual(rows[0]["human_topical_pmids"], "1")
        self.assertEqual(rows[0]["best_evidence_tier"], "3")

    def test_conditional_signal_keeps_abstract_exact_formulation_hit(self):
        candidate = PairCandidate(
            ingredient_id="butylene_glycol",
            name_en="Butylene Glycol",
            effect_id="effect_moisture_barrier",
            signal_strength="high",
            signal_functions=("HUMECTANT",),
            selection_policy="human_topical_pubmed_required",
        )
        paper = PaperMetadata(
            pmid="1",
            title="A Combination Moisturizer",
            publication_types=("Clinical Trial",),
            abstract="Patients applied a cream containing butylene glycol.",
        )
        client = FakeClient(["1"], {"1": paper})

        rows = screen_candidates(
            candidates=[candidate],
            ingredient_terms={"butylene_glycol": ["Butylene Glycol"]},
            client=client,
            as_of=date(2026, 7, 12),
            retmax_per_pair=20,
        )

        self.assertEqual(rows[0]["selected_for_paper_review"], "Y")
        self.assertEqual(rows[0]["screening_status"], "evidence_tier_3")
        self.assertEqual(rows[0]["best_relation_scope"], "abstract_exact")
        self.assertEqual(rows[0]["best_applicability"], "combination_or_formulation")


if __name__ == "__main__":
    unittest.main()
