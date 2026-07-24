from __future__ import annotations

import hashlib
import csv
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from adjudicate_ingredient_evidence_466 import (  # noqa: E402
    MANIFEST_VERSION,
    OUTCOME_RESULT_FIELDS,
    POLICY_VERSION,
    STATUS_ORDER,
    _outcome_result_row,
    build_search_run_rows,
    canonical_manifest_sha256,
    decide_paper,
    derive_ingredient_primary_status,
    load_approved_ingredient_terms,
    select_representatives,
    validate_fresh_source_inputs,
)
from discover_new_evidence import PaperMetadata  # noqa: E402
from evaluate_ingredient_multisource_funnel import (  # noqa: E402
    CandidatePaper,
    EvaluatedPaper,
)
from screen_effect_review_candidates import PaperAssessment  # noqa: E402


def _outcome(
    evidence_span: str,
    *,
    direction: str = "positive",
    mapping_status: str = "mapped_existing_effect",
    effect_id: str = "effect_moisture_barrier",
    relation: str = "direct",
) -> dict[str, str]:
    return {
        "evidence_span": evidence_span,
        "ingredient_outcome_relation": relation,
        "mapping_status": mapping_status,
        "mapped_effect_ids": effect_id if mapping_status == "mapped_existing_effect" else "",
        "new_effect_candidate": "microbiome" if mapping_status == "new_effect_candidate" else "",
        "mechanism_label": "",
        "direction": direction,
        "direction_by_effect_json": "[]",
        "direction_conflict": "N",
        "direction_policy_version": "test",
    }


def _evaluated_paper(
    *,
    ingredient_id: str = "niacinamide",
    title: str = "Randomized controlled trial of niacinamide on facial skin",
    abstract: str = "Niacinamide reduced TEWL compared with vehicle (p < 0.01).",
    publication_types: tuple[str, ...] = ("Randomized Controlled Trial",),
    tier: int = 2,
    kind: str = "human_topical_rct",
    applicability: str = "human_topical",
    outcomes: tuple[dict[str, str], ...] | None = None,
) -> EvaluatedPaper:
    paper = PaperMetadata(
        pmid="12345",
        doi="10.1000/test",
        title=title,
        journal="Test Journal",
        publication_date="2025-01-01",
        publication_types=publication_types,
        authors=("Tester A",),
        abstract=abstract,
    )
    candidate = CandidatePaper(ingredient_id, ("pubmed",), paper)
    assessment = PaperAssessment(
        paper=paper,
        evidence_tier=tier,
        evidence_kind=kind,
        relation_scope="title_exact",
        applicability=applicability,
        signal_score=90,
    )
    return EvaluatedPaper(
        candidate=candidate,
        assessment=assessment,
        outcomes=outcomes or (_outcome(abstract),),
        passed_stage_count=7,
    )


class AdjudicateIngredientEvidence466Tests(unittest.TestCase):
    def test_v11_primary_enum_separates_search_zero_results(self):
        self.assertEqual(POLICY_VERSION, "mwbl-ingredient-evidence-adjudication-v1.1")
        self.assertEqual(MANIFEST_VERSION, "mwbl-ingredient-evidence-targets-466-v1.1")
        self.assertNotIn("no_evidence_found", STATUS_ORDER)

    def test_adjudication_terms_never_invent_an_ingredient_id_fallback(self):
        terms = load_approved_ingredient_terms(
            [
                {
                    "ingredient_id": "canonical_one",
                    "name_en": "Canonical One|Official Scientific Name",
                },
                {"ingredient_id": "bht", "name_en": "BHT"},
                {"ingredient_id": "unapproved_identifier", "name_en": ""},
            ],
            [
                {
                    "canonical_id": "canonical_one",
                    "alias": "Approved INCI|Second Approved INCI",
                    "alias_type": "inci",
                    "confidence": "high",
                },
                {
                    "canonical_id": "canonical_one",
                    "alias": "Unreviewed Name",
                    "alias_type": "synonym",
                    "confidence": "medium",
                },
            ],
            {"canonical_one", "bht", "unapproved_identifier"},
        )

        self.assertEqual(
            terms["canonical_one"],
            [
                "Canonical One",
                "Official Scientific Name",
                "Approved INCI",
                "Second Approved INCI",
            ],
        )
        self.assertEqual(terms["bht"], ["BHT"])
        self.assertEqual(terms["unapproved_identifier"], [])

    def test_abstract_only_positive_is_preserved_but_demoted(self):
        decision = decide_paper(_evaluated_paper(), ("niacinamide",))

        self.assertEqual(decision.machine_signal_status, "score_candidate_positive")
        self.assertEqual(decision.primary_status, "abstract_insufficient")
        self.assertEqual(decision.score_status, "not_scoreable")
        self.assertEqual(decision.full_text_status, "not_checked")
        self.assertEqual(
            decision.verification_status,
            "abstract_only",
        )
        self.assertFalse(decision.primary_status.startswith("score_candidate_"))

    def test_automated_generator_rejects_a_claimed_full_text_state(self):
        with self.assertRaisesRegex(ValueError, "manual adjudication"):
            decide_paper(
                _evaluated_paper(),
                ("niacinamide",),
                full_text_status="checked",
            )

    def test_preprint_is_ineligible_even_with_a_positive_result(self):
        decision = decide_paper(
            _evaluated_paper(publication_types=("Preprint",)),
            ("niacinamide",),
        )

        self.assertTrue(decision.preprint_flag)
        self.assertEqual(decision.eligibility_status, "ineligible_design")
        self.assertEqual(decision.primary_status, "reject_wrong_scope")
        self.assertEqual(decision.score_status, "not_scoreable")

    def test_rejected_report_does_not_override_an_eligible_abstract_path(self):
        eligible = decide_paper(_evaluated_paper(), ("niacinamide",))
        rejected = decide_paper(
            _evaluated_paper(publication_types=("Preprint",)),
            ("niacinamide",),
        )

        self.assertEqual(
            derive_ingredient_primary_status((rejected, eligible)),
            "abstract_insufficient",
        )

    def test_case_report_is_safety_only_not_positive_efficacy(self):
        decision = decide_paper(
            _evaluated_paper(
                title="Case report of niacinamide use on facial skin",
                publication_types=("Case Reports",),
            ),
            ("niacinamide",),
        )

        self.assertTrue(decision.case_report_flag)
        self.assertTrue(decision.safety_only_flag)
        self.assertEqual(decision.eligibility_status, "ineligible_design")
        self.assertEqual(decision.applicability_status, "safety_only")
        self.assertEqual(decision.machine_signal_status, "safety_only")
        self.assertEqual(decision.primary_status, "reject_wrong_scope")

    def test_medical_and_experimental_contexts_are_limited_not_generalized(self):
        decision = decide_paper(
            _evaluated_paper(
                title="Randomized controlled trial of niacinamide in acne patients",
                abstract=(
                    "After an experimentally induced irritant challenge, niacinamide "
                    "reduced TEWL compared with vehicle (p < 0.01)."
                ),
            ),
            ("niacinamide",),
        )

        self.assertTrue(decision.medical_context_limited)
        self.assertTrue(decision.experimental_challenge_limited)
        self.assertEqual(decision.applicability_status, "medical_context_limited")

    def test_statistical_gate_is_scoped_to_each_outcome_span(self):
        first_span = "Niacinamide reduced TEWL compared with vehicle."
        second_span = (
            "Niacinamide reduced erythema index compared with vehicle (p < 0.01)."
        )
        decision = decide_paper(
            _evaluated_paper(
                abstract=f"{first_span} {second_span}",
                outcomes=(
                    _outcome(first_span),
                    _outcome(second_span, effect_id="effect_soothing"),
                ),
            ),
            ("niacinamide",),
        )

        first, second = decision.outcome_decisions
        self.assertEqual(
            first.statistical_gate_status,
            "failed_missing_p_or_ci_in_outcome_span",
        )
        self.assertFalse(first.statistical_support)
        self.assertEqual(
            second.statistical_gate_status,
            "passed_controlled_contrast_p_or_ci",
        )
        self.assertTrue(second.statistical_support)

    def test_controlled_outcome_requires_an_eligible_contrast(self):
        span = "Niacinamide reduced TEWL in the treatment group (p < 0.01)."
        decision = decide_paper(
            _evaluated_paper(abstract=span, outcomes=(_outcome(span),)),
            ("niacinamide",),
        )

        outcome = decision.outcome_decisions[0]
        self.assertEqual(outcome.statistical_gate_status, "failed_missing_eligible_contrast")
        self.assertEqual(outcome.machine_signal_status, "abstract_insufficient")

    def test_positive_direction_requires_a_supportive_p_value(self):
        span = "Niacinamide reduced TEWL compared with vehicle (p = 0.80)."
        decision = decide_paper(
            _evaluated_paper(abstract=span, outcomes=(_outcome(span),)),
            ("niacinamide",),
        )

        outcome = decision.outcome_decisions[0]
        self.assertEqual(
            outcome.statistical_gate_status,
            "failed_statistical_result_not_supportive",
        )
        self.assertEqual(outcome.estimate_direction, "positive")
        self.assertEqual(outcome.outcome_direction, "unclear")
        self.assertEqual(outcome.machine_signal_status, "abstract_insufficient")

    def test_null_direction_can_preserve_no_detectable_difference(self):
        span = "There was no difference in TEWL versus vehicle (p = 0.80)."
        decision = decide_paper(
            _evaluated_paper(
                abstract=span,
                outcomes=(_outcome(span, direction="null"),),
            ),
            ("niacinamide",),
        )

        outcome = decision.outcome_decisions[0]
        self.assertTrue(outcome.statistical_support)
        self.assertEqual(outcome.outcome_direction, "no_detectable_difference")
        self.assertEqual(outcome.machine_signal_status, "negative_or_null")

    def test_observational_support_requires_pre_post_objective_measure(self):
        span = "After 4 weeks, niacinamide reduced TEWL from baseline."
        decision = decide_paper(
            _evaluated_paper(
                title="Use test of niacinamide on facial skin",
                abstract=span,
                publication_types=("Observational Study",),
                tier=4,
                kind="human_topical_observational_or_use_test",
                outcomes=(_outcome(span),),
            ),
            ("niacinamide",),
        )

        outcome = decision.outcome_decisions[0]
        self.assertEqual(
            outcome.statistical_gate_status,
            "passed_observational_pre_post_measure",
        )
        self.assertEqual(decision.machine_signal_status, "score_candidate_supporting")
        self.assertEqual(decision.primary_status, "abstract_insufficient")
        self.assertEqual(decision.score_status, "not_scoreable")

    def test_outcome_row_uses_explicit_unknown_and_not_extracted_values(self):
        decision = decide_paper(_evaluated_paper(), ("niacinamide",))
        provenance = {
            "manifest_version": MANIFEST_VERSION,
            "manifest_sha256": "manifest",
            "ingredient_dictionary_sha256": "ingredient",
            "outcome_dictionary_sha256": "outcome",
            "direction_dictionary_sha256": "direction",
        }
        row = _outcome_result_row(
            decision,
            decision.outcome_decisions[0],
            1,
            provenance,
        )

        self.assertEqual(set(row), set(OUTCOME_RESULT_FIELDS))
        self.assertEqual(row["intervention_arm"], "not_extracted")
        self.assertEqual(row["comparator_arm"], "not_extracted")
        self.assertEqual(row["timepoint"], "not_extracted")
        self.assertEqual(row["effect_estimate"], "not_extracted")
        self.assertEqual(row["estimate_type"], "unknown")
        self.assertEqual(row["estimate_unit"], "unknown")
        self.assertEqual(row["p_value_operator"], "lt")
        self.assertEqual(row["p_value"], "0.01")
        self.assertEqual(row["score_status"], "not_scoreable")

    def test_outcome_ids_are_deterministic_and_unique_across_ingredients(self):
        first = decide_paper(_evaluated_paper(), ("niacinamide",))
        second = decide_paper(
            _evaluated_paper(ingredient_id="eugenol"),
            ("eugenol",),
        )
        provenance = {
            "manifest_version": MANIFEST_VERSION,
            "manifest_sha256": "manifest",
            "ingredient_dictionary_sha256": "ingredient",
            "outcome_dictionary_sha256": "outcome",
            "direction_dictionary_sha256": "direction",
        }

        first_row = _outcome_result_row(first, first.outcome_decisions[0], 1, provenance)
        repeated_row = _outcome_result_row(first, first.outcome_decisions[0], 1, provenance)
        second_row = _outcome_result_row(second, second.outcome_decisions[0], 1, provenance)

        self.assertEqual(first_row["outcome_result_id"], repeated_row["outcome_result_id"])
        self.assertNotEqual(first_row["outcome_result_id"], second_row["outcome_result_id"])
        self.assertEqual(first_row["outcome_id_status"], "provisional_abstract")

    def test_representatives_keep_the_best_eligible_path_first(self):
        eligible = decide_paper(_evaluated_paper(), ("niacinamide",))
        rejected = decide_paper(
            _evaluated_paper(publication_types=("Preprint",)),
            ("niacinamide",),
        )

        selected = select_representatives((rejected, eligible))

        self.assertEqual(selected[0].eligibility_status, "eligible")

    def test_manifest_sha_is_canonical_and_order_independent(self):
        rows = [
            {
                "ingredient_rank": "2",
                "ingredient_id": "b",
                "name_en": "Beta",
                "product_count": "20",
            },
            {
                "ingredient_rank": "1",
                "ingredient_id": "a",
                "name_en": "Alpha",
                "product_count": "10",
            },
        ]
        expected_bytes = (
            "ingredient_rank,ingredient_id,name_en,product_count\n"
            "1,a,Alpha,10\n"
            "2,b,Beta,20\n"
        ).encode("utf-8")

        self.assertEqual(
            canonical_manifest_sha256(rows),
            hashlib.sha256(expected_bytes).hexdigest(),
        )
        self.assertEqual(
            canonical_manifest_sha256(rows),
            canonical_manifest_sha256(list(reversed(rows))),
        )

    def test_search_run_rows_normalize_fresh_source_logs(self):
        target = {
            "ingredient_rank": "1",
            "ingredient_id": "niacinamide",
            "name_en": "Niacinamide|Vitamin B3",
            "product_count": "100",
            "search_terms": "Niacinamide",
            "search_query": "Niacinamide AND skin",
            "raw_pubmed_hit_count": "4",
            "selected_paper_count": "2",
            "searched_on": "2026-07-13",
        }
        complete_log = {
            "ingredient_id": "niacinamide",
            "search_query": "Niacinamide skin topical",
            "raw_hit_count": "1",
            "returned_count": "1",
            "request_status": "success",
            "pagination_complete": "Y",
            "query_contract_status": "approved_terms_only",
            "approved_search_terms": "Niacinamide",
            "canonical_name_en": "Niacinamide",
            "searched_at": "2026-07-13T00:00:00Z",
            "error_message": "",
        }
        rows = build_search_run_rows(
            [target],
            source_query_logs={
                "pubmed": [complete_log],
                "europe_pmc": [complete_log],
                "crossref": [complete_log],
                "openalex": [],
            },
            ingredient_terms={"niacinamide": ("Niacinamide",)},
        )
        by_source = {row["source"]: row for row in rows}

        self.assertEqual(len(rows), 6)
        self.assertEqual(by_source["pubmed"]["search_status"], "success")
        self.assertEqual(by_source["pubmed"]["searched_name"], "Niacinamide")
        self.assertEqual(by_source["europe_pmc"]["search_status"], "success")
        self.assertEqual(by_source["crossref"]["search_status"], "success")
        self.assertEqual(by_source["openalex"]["source_run_status"], "provenance_incomplete")
        self.assertEqual(by_source["openalex"]["search_status"], "not_attempted")
        self.assertEqual(by_source["kci"]["search_status"], "not_attempted")
        self.assertEqual(by_source["riss"]["search_status"], "not_attempted")
        self.assertEqual(
            by_source["pubmed"]["query_contract_status"], "approved_terms_only"
        )
        self.assertEqual(by_source["pubmed"]["rerun_required"], "N")
        self.assertEqual(
            by_source["crossref"]["query_contract_status"],
            "approved_terms_only",
        )
        self.assertEqual(by_source["crossref"]["rerun_required"], "N")

    def test_search_run_marks_truncated_retrieval_as_partial(self):
        target = {
            "ingredient_rank": "1",
            "ingredient_id": "niacinamide",
            "name_en": "Niacinamide",
            "product_count": "100",
            "search_terms": "Niacinamide",
            "search_query": "Niacinamide AND skin",
            "raw_pubmed_hit_count": "1",
            "selected_paper_count": "1",
            "searched_on": "2026-07-13",
        }
        truncated_log = {
            "ingredient_id": "niacinamide",
            "name_en": "Niacinamide",
            "search_query": "Niacinamide skin topical",
            "raw_hit_count": "10",
            "returned_count": "2",
            "request_status": "ok",
            "pagination_complete": "N",
            "query_contract_status": "approved_terms_only",
            "error_message": "",
        }

        rows = build_search_run_rows(
            [target],
            source_query_logs={
                "europe_pmc": [truncated_log],
                "crossref": [truncated_log],
                "openalex": [truncated_log],
            },
            ingredient_terms={"niacinamide": ("Niacinamide",)},
        )
        by_source = {row["source"]: row for row in rows}

        self.assertEqual(by_source["crossref"]["search_status"], "partial")
        self.assertEqual(by_source["crossref"]["pagination_complete"], "false")
        self.assertEqual(by_source["crossref"]["source_run_status"], "partial")

    def test_fresh_source_inputs_fail_closed_on_candidate_count_mismatch(self):
        log_fields = [
            "source",
            "ingredient_id",
            "search_query",
            "request_status",
            "returned_count",
            "query_contract_status",
            "review_status",
            "runtime_score_change",
        ]
        candidate_fields = [
            "source",
            "ingredient_id",
            "title",
            "review_status",
            "runtime_score_change",
        ]
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            candidate_paths = {}
            query_paths = {}
            for source in (
                "pubmed",
                "europe_pmc",
                "crossref",
                "openalex",
                "kci",
                "riss",
            ):
                candidate_path = directory / f"{source}_candidates.csv"
                query_path = directory / f"{source}_query.csv"
                candidate_paths[source] = candidate_path
                query_paths[source] = query_path
                with candidate_path.open("w", encoding="utf-8", newline="") as handle:
                    csv.DictWriter(handle, fieldnames=candidate_fields).writeheader()
                with query_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=log_fields)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "source": source,
                            "ingredient_id": "niacinamide",
                            "search_query": '"Niacinamide" skin',
                            "request_status": "success",
                            "returned_count": "1" if source == "riss" else "0",
                            "query_contract_status": "approved_terms_only",
                            "review_status": "candidate_unverified",
                            "runtime_score_change": "none",
                        }
                    )
            with self.assertRaisesRegex(ValueError, "returned_count sum"):
                validate_fresh_source_inputs(
                    manifest_ids=["niacinamide"],
                    candidate_paths=candidate_paths,
                    query_log_paths=query_paths,
                )


if __name__ == "__main__":
    unittest.main()
