#!/usr/bin/env python3
"""Build the v1.1 review-only ingredient evidence adjudication ledgers.

The v1.1 contract deliberately separates search completeness, eligibility,
applicability, verification, outcome mapping/direction, and score eligibility.
Abstract-derived signals remain visible, but no abstract-only record can become
scoreable or change runtime data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from assess_ingredient_score_eligibility import UNCERTAIN_EFFECT_RE
from build_ingredient_first_paper_catalog import _term_form_is_limited
from discover_new_evidence import stable_unique
from evaluate_ingredient_multisource_funnel import (
    CandidatePaper,
    EvaluatedPaper,
    evaluate_paper,
    external_candidate,
    merge_candidate_papers,
    paper_key,
    pubmed_candidate,
    read_csv,
    write_csv,
)


POLICY_VERSION = "mwbl-ingredient-evidence-adjudication-v1.1"
MANIFEST_VERSION = "mwbl-ingredient-evidence-targets-466-v1.1"
MAX_REPRESENTATIVE_PAPERS = 3
RUNTIME_STATUS = "existing_runtime"
REVIEW_STATUS = "candidate_unverified"
FULL_TEXT_STATUS = "not_checked"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1]

# This is a display/status-priority enum, not a score-decision enum. Search
# zero-results are represented by search_status and must never enter this enum.
STATUS_ORDER = (
    "reject_wrong_scope",
    "formulation_only",
    "abstract_insufficient",
    "new_effect_candidate",
    "negative_or_null",
    "score_candidate_supporting",
    "score_candidate_positive",
)
STATUS_RANK = {status: index for index, status in enumerate(STATUS_ORDER)}
MACHINE_SIGNAL_ORDER = (
    "score_candidate_positive",
    "score_candidate_supporting",
    "negative_or_null",
    "new_effect_candidate",
    "abstract_insufficient",
    "formulation_only",
    "safety_only",
    "reject_wrong_scope",
)
MACHINE_SIGNAL_RANK = {
    status: index for index, status in enumerate(MACHINE_SIGNAL_ORDER)
}
REPRESENTATIVE_ELIGIBILITY_RANK = {
    "eligible": 0,
    "not_assessable": 1,
    "formulation_not_isolated": 2,
    "wrong_ingredient": 3,
    "wrong_route_or_site": 4,
    "ineligible_design": 5,
    "retracted": 6,
}

RETRACTED_RE = re.compile(r"\b(retracted publication|retraction of|retracted)\b", re.I)
CORRECTION_RE = re.compile(r"\b(correction|corrigendum|erratum|updated article)\b", re.I)
EXPRESSION_OF_CONCERN_RE = re.compile(r"\b(expression of concern|editorial concern)\b", re.I)
PREPRINT_RE = re.compile(r"\b(preprint|bioRxiv|medRxiv|research square)\b|10\.\d+/preprints", re.I)
CASE_REPORT_RE = re.compile(r"\b(case report|case reports|case study)\b", re.I)
MEDICAL_CONTEXT_RE = re.compile(
    r"\b(acne|atopic dermatitis|dermatitis|eczema|melasma|psoriasis|rosacea|"
    r"vitiligo|xerosis cutis|ichthyosis|urticaria|skin disease|patients? with)\b",
    re.I,
)
EXPERIMENTAL_CHALLENGE_RE = re.compile(
    r"\b(tape[- ]stripp(?:ed|ing)|sodium lauryl sulfate|SLS[- ]induced|"
    r"UV[- ]induced|ultraviolet[- ]induced|experimentally induced|"
    r"induced erythema|histamine[- ]induced|irritant challenge)\b",
    re.I,
)
ROUTE_SITE_MISMATCH_RE = re.compile(
    r"\b(oral(?:ly)?|ingestion|supplementation|inject(?:ed|ion|able)|intravenous|"
    r"ophthalmic|ocular|corneal|conjunctiv(?:a|al)|oral mucosa|buccal|vaginal|"
    r"intranasal|scalp|hair growth|hair shaft|nail plate|onychomycosis)\b",
    re.I,
)
CONTROLLED_DESIGN_RE = re.compile(
    r"\b(randomi[sz]ed|controlled|split[- ]face|split[- ]body|vehicle[- ]controlled|"
    r"placebo[- ]controlled|double[- ]blind|contralateral)\b",
    re.I,
)
ELIGIBLE_CONTRAST_RE = re.compile(
    r"\b(compared (?:with|to)|comparison (?:with|to)|versus|vs\.?|between[- ]group|"
    r"between (?:the )?groups?|than (?:the )?(?:placebo|vehicle|control)|"
    r"treatment (?:difference|effect)|group (?:difference|effect)|contralateral|"
    r"right (?:side|face|arm|leg).{0,50}(?:left|control)|"
    r"left (?:side|face|arm|leg).{0,50}(?:right|control))\b",
    re.I,
)
P_OR_CI_RE = re.compile(
    r"(?:\bp\s*(?:<|<=|=|>|>=)\s*(?:0?\.\d+|\d+(?:\.\d+)?)\b|"
    r"\b(?:90|95|99)\s*%\s*(?:CI|confidence interval)\b|"
    r"\bconfidence interval\b)",
    re.I,
)
P_VALUE_RE = re.compile(
    r"\bp\s*(?P<operator><=|>=|<|>|=)\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\b",
    re.I,
)
P_VALUE_OPERATOR_CODES = {"<": "lt", "<=": "le", "=": "eq", ">": "gt", ">=": "ge"}
PRE_POST_RE = re.compile(
    r"\b(from baseline|compared (?:with|to) baseline|pre[- /]?post|before and after|"
    r"after (?:treatment|application|use|\d+ (?:days?|weeks?|months?))|"
    r"at (?:week|day|month) \d+|over \d+ (?:days?|weeks?|months?))\b",
    re.I,
)
OBJECTIVE_OR_VALIDATED_RE = re.compile(
    r"\b(TEWL|transepidermal water loss|melanin index|erythema index|MASI|ITA|"
    r"L\*|sebum(?: output)?|lesion count|comedone count|IGA|SCORAD|EASI|"
    r"capacitance|conductance|corneometer (?:value|reading)|cutometer parameter|"
    r"wrinkle (?:depth|area|count)|elasticity|firmness|roughness|scaling|"
    r"desquamation|corneocyte cohesion|validated (?:scale|score|questionnaire))\b",
    re.I,
)

PROVENANCE_FIELDS = [
    "manifest_version",
    "manifest_sha256",
    "ingredient_dictionary_sha256",
    "outcome_dictionary_sha256",
    "direction_dictionary_sha256",
]

INGREDIENT_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "canonical_name",
    "ingredient_entity_type",
    "product_count",
    "search_status",
    "search_result_status",
    "source_status_json",
    "sources_searched",
    "sources_not_searched",
    "raw_candidate_count",
    "deduplicated_paper_count",
    "representative_paper_count",
    "eligibility_status",
    "all_eligibility_statuses",
    "verification_status",
    "all_verification_statuses",
    "applicability_status",
    "all_applicability_statuses",
    "effect_mapping_status",
    "outcome_direction",
    "score_status",
    "machine_signal_status",
    "primary_status",
    "all_statuses",
    "all_machine_signal_statuses",
    "conflicting_evidence",
    "candidate_effect_ids",
    "new_effect_candidates",
    "representative_paper_keys",
    "full_text_gate",
    "status_scope",
    "review_status",
    "runtime_score_change",
    *PROVENANCE_FIELDS,
    "policy_version",
]

PAPER_FIELDS = [
    "ingredient_id",
    "paper_key",
    "report_id",
    "study_id",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_date",
    "publication_types",
    "sources",
    "retrieval_status",
    "evidence_tier",
    "evidence_kind",
    "study_design",
    "design",
    "randomized",
    "controlled",
    "within_person",
    "comparator_type",
    "prospective",
    "design_source_span",
    "risk_of_bias_overall",
    "relation_scope",
    "raw_ingredient_term",
    "entity_match_type",
    "intervention_role",
    "ingredient_match_span",
    "ingredient_reject_reason",
    "applicability",
    "eligibility_status",
    "verification_status",
    "applicability_status",
    "route",
    "body_site",
    "skin_condition",
    "population_type",
    "challenge_model",
    "application_regimen",
    "effect_mapping_status",
    "outcome_direction",
    "score_status",
    "machine_signal_status",
    "primary_status",
    "all_statuses",
    "all_machine_signal_statuses",
    "mapped_effect_ids",
    "new_effect_candidates",
    "directions",
    "statistical_support",
    "preprint_flag",
    "case_report_flag",
    "safety_only_flag",
    "medical_context_limited",
    "experimental_challenge_limited",
    "route_site_mismatch",
    "formulation_isolation_status",
    "test_arm_components",
    "control_arm_components",
    "target_concentration_by_arm",
    "cointerventions_equal",
    "isolation_status",
    "isolation_evidence_span",
    "correction_flag",
    "retraction_flag",
    "expression_of_concern_flag",
    "duplicate_trial_status",
    "retraction_status",
    "validity_checked_at",
    "validity_source",
    "correction_id",
    "correction_impact",
    "funding",
    "conflict_of_interest",
    "full_text_status",
    "evidence_spans",
    "status_scope",
    "review_status",
    "runtime_score_change",
    *PROVENANCE_FIELDS,
    "policy_version",
]

OUTCOME_RESULT_FIELDS = [
    "ingredient_id",
    "paper_key",
    "report_id",
    "outcome_result_id",
    "outcome_id_status",
    "outcome_rank",
    "study_id",
    "comparison_id",
    "pmid",
    "doi",
    "section",
    "page_table_figure",
    "evidence_span",
    "arm_ids",
    "ingredient_outcome_relation",
    "effect_mapping_status",
    "effect_id",
    "mapped_effect_ids",
    "raw_new_effect_candidate",
    "new_effect_candidate",
    "raw_outcome_name",
    "outcome_concept_id",
    "positive_direction",
    "instrument",
    "model",
    "channel",
    "parameter",
    "unit",
    "estimate_direction",
    "outcome_direction",
    "study_design",
    "contrast_type",
    "eligible_contrast",
    "p_or_ci_in_span",
    "p_value_operator",
    "p_value",
    "ci_low",
    "ci_high",
    "alpha",
    "n_analyzed_by_arm",
    "paired_analysis",
    "multiplicity_adjusted",
    "analysis_population",
    "pre_post_comparison",
    "objective_or_validated_measure",
    "statistical_gate_status",
    "statistical_support",
    "statistical_conclusion",
    "equivalence_supported",
    "safety_signal",
    "hedge_flag",
    "hedge_span",
    "explicit_result_available",
    "intervention_arm",
    "comparator_arm",
    "timepoint",
    "estimate",
    "effect_estimate",
    "estimate_type",
    "estimate_unit",
    "eligibility_status",
    "verification_status",
    "applicability_status",
    "score_status",
    "machine_signal_status",
    "full_text_status",
    "review_status",
    "runtime_score_change",
    *PROVENANCE_FIELDS,
    "policy_version",
]

SEARCH_RUN_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "source",
    "source_role",
    "searched_name",
    "query",
    "searched_at",
    "cutoff_date",
    "raw_count",
    "retrieved_count",
    "selected_count",
    "pagination_complete",
    "search_status",
    "source_run_status",
    "failure_reason",
    "input_provenance",
    "query_contract_status",
    "rerun_required",
    "review_status",
    "runtime_score_change",
    *PROVENANCE_FIELDS,
    "policy_version",
]


@dataclass(frozen=True)
class OutcomeDecision:
    source: Mapping[str, str]
    effect_mapping_status: str
    estimate_direction: str
    outcome_direction: str
    eligible_contrast: bool
    p_or_ci_in_span: bool
    pre_post_comparison: bool
    objective_or_validated_measure: bool
    statistical_gate_status: str
    machine_signal_status: str

    @property
    def statistical_support(self) -> bool:
        return self.statistical_gate_status.startswith("passed_")


@dataclass(frozen=True)
class PaperDecision:
    item: EvaluatedPaper
    statuses: tuple[str, ...]
    machine_signal_statuses: tuple[str, ...]
    mapped_effect_ids: tuple[str, ...]
    new_effect_candidates: tuple[str, ...]
    directions: tuple[str, ...]
    statistical_support: bool
    study_design: str
    eligibility_status: str
    verification_status: str
    applicability_status: str
    effect_mapping_status: str
    outcome_direction: str
    score_status: str
    full_text_status: str
    preprint_flag: bool
    case_report_flag: bool
    safety_only_flag: bool
    medical_context_limited: bool
    experimental_challenge_limited: bool
    route_site_mismatch: bool
    formulation_isolation_status: str
    correction_flag: bool
    retraction_flag: bool
    expression_of_concern_flag: bool
    duplicate_trial_status: str
    outcome_decisions: tuple[OutcomeDecision, ...]

    @property
    def primary_status(self) -> str:
        return min(self.statuses, key=STATUS_RANK.__getitem__)

    @property
    def machine_signal_status(self) -> str:
        return min(self.machine_signal_statuses, key=MACHINE_SIGNAL_RANK.__getitem__)


def read_runtime_ingredient_ids(path: Path) -> set[str]:
    return {row["ingredient_id"] for row in read_csv(path)}


def load_approved_ingredient_terms(
    ingredient_rows: Sequence[Mapping[str, str]],
    alias_rows: Sequence[Mapping[str, str]],
    ingredient_ids: set[str],
) -> dict[str, list[str]]:
    """Load only canonical names and curated high-confidence English aliases.

    Unlike the discovery helper, this adjudication loader never manufactures a
    term from ``ingredient_id``. C03/C10 require every accepted synonym to be
    traceable to the canonical ingredient table or the approved alias table.
    """

    terms: dict[str, list[str]] = defaultdict(list)
    for row in ingredient_rows:
        ingredient_id = row.get("ingredient_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        terms[ingredient_id].extend(
            value.strip()
            for value in row.get("name_en", "").split("|")
            if value.strip().isascii() and re.search(r"[A-Za-z]", value)
        )

    allowed_alias_types = {"inci", "synonym", "en"}
    for row in alias_rows:
        ingredient_id = row.get("canonical_id", "").strip()
        if ingredient_id not in ingredient_ids:
            continue
        if row.get("confidence", "").strip().casefold() != "high":
            continue
        if row.get("alias_type", "").strip().casefold() not in allowed_alias_types:
            continue
        for alias in row.get("alias", "").split("|"):
            alias = alias.strip()
            if alias.isascii() and re.search(r"[A-Za-z]", alias):
                terms[ingredient_id].append(alias)

    return {
        ingredient_id: stable_unique(terms.get(ingredient_id, []))[:16]
        for ingredient_id in ingredient_ids
    }


def _canonical_manifest_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("ingredient_rank", "ingredient_id", "name_en", "product_count"))
    for row in sorted(rows, key=lambda value: int(value["ingredient_rank"])):
        writer.writerow(
            (
                row.get("ingredient_rank", ""),
                row.get("ingredient_id", ""),
                row.get("name_en", ""),
                row.get("product_count", ""),
            )
        )
    return output.getvalue().encode("utf-8")


def canonical_manifest_sha256(rows: Sequence[Mapping[str, str]]) -> str:
    """Hash the canonical exact review subset, independent of input row order."""

    return hashlib.sha256(_canonical_manifest_bytes(rows)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_provenance_metadata(
    data_dir: Path,
    review_targets: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    ingredient_paths = [data_dir / "ingredients.csv", data_dir / "ingredient_aliases.csv"]
    ingredient_files = [
        {"file": path.name, "sha256": _file_sha256(path)} for path in ingredient_paths
    ]
    bundle_payload = "".join(
        f"{entry['file']}:{entry['sha256']}\n" for entry in ingredient_files
    ).encode("utf-8")
    return {
        "manifest_version": MANIFEST_VERSION,
        "manifest_sha256": canonical_manifest_sha256(review_targets),
        "ingredient_dictionary_sha256": hashlib.sha256(bundle_payload).hexdigest(),
        "ingredient_dictionary_files": ingredient_files,
        "outcome_dictionary_sha256": _file_sha256(data_dir / "effect_outcome_dictionary.csv"),
        "direction_dictionary_sha256": _file_sha256(data_dir / "effect_direction_dictionary.csv"),
    }


def _provenance_columns(provenance: Mapping[str, object]) -> dict[str, object]:
    return {field: provenance.get(field, "") for field in PROVENANCE_FIELDS}


def _direct_outcomes(item: EvaluatedPaper) -> list[Mapping[str, str]]:
    return [
        row
        for row in item.outcomes
        if row.get("ingredient_outcome_relation") in {"direct", "review_summary"}
    ]


def _study_design(item: EvaluatedPaper, publication_text: str) -> str:
    kind = item.assessment.evidence_kind
    text = f"{publication_text} {item.candidate.metadata.abstract}"
    if CASE_REPORT_RE.search(text):
        return "case_report"
    if "systematic_review" in kind or re.search(
        r"\b(meta[- ]analysis|systematic review)\b", text, re.I
    ):
        return "systematic_review"
    if "rct" in kind or re.search(r"\brandomi[sz]ed\b", text, re.I):
        return "controlled_trial"
    if CONTROLLED_DESIGN_RE.search(text):
        return "controlled_trial"
    if item.assessment.evidence_tier in {3, 4}:
        return "observational_or_nonrandomized"
    return "unsupported_design"


def _mapping_status(rows: Sequence[Mapping[str, str]]) -> str:
    values = {row.get("mapping_status", "unclear") for row in rows}
    if not rows:
        return "not_mapped"
    if "mapped_existing_effect" in values:
        return "mapped_existing"
    if "new_effect_candidate" in values:
        return "new_effect_candidate"
    return "unmapped_outcome"


def _aggregate(values: Sequence[str], *, empty: str) -> str:
    present = {value for value in values if value}
    if not present:
        return empty
    if len(present) == 1:
        return next(iter(present))
    return "mixed"


def _aggregate_by_priority(
    values: Sequence[str],
    *,
    priority: Sequence[str],
    empty: str,
) -> str:
    present = set(values)
    return next((value for value in priority if value in present), empty)


def _normalize_mapping_status(value: str) -> str:
    return {
        "mapped_existing_effect": "mapped_existing",
        "new_effect_candidate": "new_effect_candidate",
        "unclear": "unmapped_outcome",
        "mechanism_only": "unmapped_outcome",
    }.get(value, "unmapped_outcome")


def _normalize_outcome_direction(value: str) -> str:
    return {
        "positive": "positive",
        "negative": "negative",
        "null": "no_detectable_difference",
        "unclear": "unclear",
    }.get(value, "not_applicable")


def _aggregate_outcome_direction(values: Sequence[str]) -> str:
    present = {value for value in values if value and value != "not_applicable"}
    if not present:
        return "not_applicable"
    if len(present) == 1:
        return next(iter(present))
    return "unclear"


def _p_value_supports_direction(span: str, direction: str) -> bool:
    """Conservatively connect an explicit p-value to the extracted direction."""

    match = P_VALUE_RE.search(span)
    if not match:
        return False
    operator = match.group("operator")
    value = float(match.group("value"))
    if direction in {"positive", "negative"}:
        if operator in {"<", "<="}:
            return value <= 0.05
        return operator == "=" and value < 0.05
    if direction == "no_detectable_difference":
        if operator in {">", ">="}:
            return value >= 0.05
        return operator == "=" and value >= 0.05
    return False


def _classify_outcome(
    row: Mapping[str, str],
    *,
    study_design: str,
    allow_signal: bool,
) -> OutcomeDecision:
    span = row.get("evidence_span", "")
    relation = row.get("ingredient_outcome_relation", "")
    raw_mapping = row.get("mapping_status", "unclear") or "unclear"
    mapping = _normalize_mapping_status(raw_mapping)
    if mapping == "new_effect_candidate" and not allow_signal:
        mapping = "unmapped_outcome"
    estimate_direction = _normalize_outcome_direction(
        row.get("direction", "unclear") or "unclear"
    )
    eligible_contrast = bool(ELIGIBLE_CONTRAST_RE.search(span))
    p_or_ci = bool(P_OR_CI_RE.search(span))
    pre_post = bool(PRE_POST_RE.search(span))
    objective_or_validated = bool(OBJECTIVE_OR_VALIDATED_RE.search(span))

    direct = relation in {"direct", "review_summary"}
    if not direct or mapping not in {"mapped_existing", "new_effect_candidate"}:
        gate = "not_applicable_not_direct_mapped_outcome"
    elif study_design in {"controlled_trial", "systematic_review"}:
        if not eligible_contrast:
            gate = "failed_missing_eligible_contrast"
        elif not p_or_ci:
            gate = "failed_missing_p_or_ci_in_outcome_span"
        elif not _p_value_supports_direction(span, estimate_direction):
            gate = "failed_statistical_result_not_supportive"
        else:
            gate = "passed_controlled_contrast_p_or_ci"
    elif study_design == "observational_or_nonrandomized":
        if not pre_post:
            gate = "failed_missing_pre_post_comparison"
        elif not objective_or_validated:
            gate = "failed_missing_objective_or_validated_measure"
        else:
            gate = "passed_observational_pre_post_measure"
    else:
        gate = "not_applicable_ineligible_design"

    direction = (
        estimate_direction
        if gate.startswith("passed_")
        else "not_applicable"
        if not direct or mapping not in {"mapped_existing", "new_effect_candidate"}
        else "unclear"
    )

    signal = "abstract_insufficient"
    if allow_signal and direct and mapping == "new_effect_candidate":
        signal = "new_effect_candidate"
    elif allow_signal and direct and mapping == "mapped_existing":
        if direction in {"negative", "no_detectable_difference"}:
            signal = "negative_or_null"
        elif direction == "positive":
            certain = not UNCERTAIN_EFFECT_RE.search(span) or p_or_ci
            if certain and gate == "passed_controlled_contrast_p_or_ci":
                signal = "score_candidate_positive"
            elif certain and gate == "passed_observational_pre_post_measure":
                signal = "score_candidate_supporting"

    return OutcomeDecision(
        source=row,
        effect_mapping_status=mapping,
        estimate_direction=estimate_direction,
        outcome_direction=direction,
        eligible_contrast=eligible_contrast,
        p_or_ci_in_span=p_or_ci,
        pre_post_comparison=pre_post,
        objective_or_validated_measure=objective_or_validated,
        statistical_gate_status=gate,
        machine_signal_status=signal,
    )


def decide_paper(
    item: EvaluatedPaper,
    ingredient_terms: Sequence[str],
    *,
    full_text_status: str = FULL_TEXT_STATUS,
) -> PaperDecision:
    if full_text_status != FULL_TEXT_STATUS:
        raise ValueError(
            "The automated v1.1 generator accepts abstract screening only; "
            "full-text verification requires the manual adjudication workflow."
        )
    metadata = item.candidate.metadata
    assessment = item.assessment
    publication_text = " ".join(
        (metadata.title, metadata.journal, *metadata.publication_types)
    )
    complete_text = f"{publication_text} {metadata.abstract}"
    preprint = bool(PREPRINT_RE.search(publication_text))
    case_report = bool(CASE_REPORT_RE.search(complete_text))
    correction = bool(CORRECTION_RE.search(publication_text))
    retracted = bool(RETRACTED_RE.search(publication_text))
    expression_of_concern = bool(EXPRESSION_OF_CONCERN_RE.search(publication_text))
    medical_limited = bool(MEDICAL_CONTEXT_RE.search(complete_text))
    challenge_limited = bool(EXPERIMENTAL_CHALLENGE_RE.search(complete_text))
    route_site_mismatch = assessment.applicability == "route_mismatch" or bool(
        ROUTE_SITE_MISMATCH_RE.search(metadata.title)
    )
    exact = (
        assessment.relation_scope != "unconfirmed"
        and not _term_form_is_limited(metadata.title, ingredient_terms)
    )
    study_design = _study_design(item, publication_text)

    if retracted:
        eligibility = "retracted"
    elif not exact:
        eligibility = "wrong_ingredient"
    elif route_site_mismatch:
        eligibility = "wrong_route_or_site"
    elif preprint or case_report:
        eligibility = "ineligible_design"
    elif assessment.applicability == "combination_or_formulation":
        eligibility = "formulation_not_isolated"
    elif (
        item.passed_stage_count < 2
        or assessment.evidence_tier > 4
        or assessment.applicability != "human_topical"
    ):
        eligibility = "ineligible_design"
    elif not metadata.abstract:
        eligibility = "not_assessable"
    else:
        eligibility = "eligible"

    if retracted or expression_of_concern:
        verification = "validity_hold"
    elif correction:
        verification = "correction_pending"
    elif not metadata.abstract:
        verification = "full_text_unavailable"
    elif full_text_status == "not_checked":
        verification = "abstract_only"
    else:
        verification = "full_text_verified"

    if case_report:
        applicability_status = "safety_only"
    elif route_site_mismatch or assessment.applicability == "combination_or_formulation":
        applicability_status = "not_applicable"
    elif medical_limited:
        applicability_status = "medical_context_limited"
    elif challenge_limited:
        applicability_status = "experimental_challenge_limited"
    elif assessment.applicability == "human_topical":
        applicability_status = "general_skin"
    else:
        applicability_status = "not_applicable"

    hard_exclusion = eligibility in {
        "wrong_ingredient",
        "wrong_route_or_site",
        "ineligible_design",
        "formulation_not_isolated",
        "retracted",
        "not_assessable",
    } or verification == "validity_hold"
    outcome_decisions = tuple(
        _classify_outcome(
            row,
            study_design=study_design,
            allow_signal=not hard_exclusion,
        )
        for row in item.outcomes
    )
    direct = _direct_outcomes(item)
    existing = [row for row in direct if row.get("mapping_status") == "mapped_existing_effect"]
    mapped_effect_ids = tuple(
        sorted(
            {
                effect_id
                for row in existing
                for effect_id in row.get("mapped_effect_ids", "").split("|")
                if effect_id
            }
        )
    )
    new_effect_candidates = tuple(
        sorted(
            {
                outcome.source.get("new_effect_candidate", "")
                for outcome in outcome_decisions
                if outcome.effect_mapping_status == "new_effect_candidate"
                and outcome.source.get("new_effect_candidate", "")
            }
        )
    )
    directions = tuple(
        sorted({row.get("direction", "unclear") for row in existing if row.get("direction")})
    )

    if case_report:
        machine_statuses = {"safety_only"}
    elif eligibility in {
        "retracted",
        "wrong_ingredient",
        "wrong_route_or_site",
        "ineligible_design",
    }:
        machine_statuses = {"reject_wrong_scope"}
    elif eligibility == "formulation_not_isolated":
        machine_statuses = {"formulation_only"}
    elif expression_of_concern:
        machine_statuses = {"abstract_insufficient"}
    else:
        machine_statuses = {
            decision.machine_signal_status
            for decision in outcome_decisions
            if decision.machine_signal_status != "abstract_insufficient"
        }
        if not machine_statuses:
            machine_statuses = {"abstract_insufficient"}

    display_statuses: set[str] = set()
    if eligibility in {"retracted", "wrong_ingredient", "wrong_route_or_site", "ineligible_design"}:
        display_statuses.add("reject_wrong_scope")
    elif eligibility == "formulation_not_isolated":
        display_statuses.add("formulation_only")
    elif verification != "full_text_verified":
        display_statuses.add("abstract_insufficient")
    else:
        display_statuses.update(
            status
            for status in machine_statuses
            if status in STATUS_RANK
        )
    if not display_statuses:
        display_statuses = {"abstract_insufficient"}
    machine_statuses_tuple = tuple(
        sorted(machine_statuses, key=MACHINE_SIGNAL_RANK.__getitem__)
    )
    statuses_tuple = tuple(sorted(display_statuses, key=STATUS_RANK.__getitem__))
    score_status = "not_scoreable"

    return PaperDecision(
        item=item,
        statuses=statuses_tuple,
        machine_signal_statuses=machine_statuses_tuple,
        mapped_effect_ids=mapped_effect_ids,
        new_effect_candidates=new_effect_candidates,
        directions=directions,
        statistical_support=any(row.statistical_support for row in outcome_decisions),
        study_design=study_design,
        eligibility_status=eligibility,
        verification_status=verification,
        applicability_status=applicability_status,
        effect_mapping_status=_aggregate_by_priority(
            [outcome.effect_mapping_status for outcome in outcome_decisions],
            priority=(
                "mapped_existing",
                "new_effect_candidate",
                "unmapped_outcome",
                "not_mapped",
            ),
            empty="not_mapped",
        ),
        outcome_direction=_aggregate_outcome_direction(
            [
                outcome.outcome_direction
                for outcome in outcome_decisions
                if outcome.effect_mapping_status == "mapped_existing"
            ]
        ),
        score_status=score_status,
        full_text_status=full_text_status,
        preprint_flag=preprint,
        case_report_flag=case_report,
        safety_only_flag=case_report,
        medical_context_limited=medical_limited,
        experimental_challenge_limited=challenge_limited,
        route_site_mismatch=route_site_mismatch,
        formulation_isolation_status="not_checked",
        correction_flag=correction,
        retraction_flag=retracted,
        expression_of_concern_flag=expression_of_concern,
        duplicate_trial_status="not_checked",
        outcome_decisions=outcome_decisions,
    )


def select_representatives(decisions: Sequence[PaperDecision]) -> list[PaperDecision]:
    ordered = sorted(
        decisions,
        key=lambda decision: (
            REPRESENTATIVE_ELIGIBILITY_RANK[decision.eligibility_status],
            MACHINE_SIGNAL_RANK[decision.machine_signal_status],
            decision.item.assessment.evidence_tier,
            0 if decision.item.candidate.metadata.abstract else 1,
            paper_key(decision.item.candidate.metadata),
        ),
    )
    selected: list[PaperDecision] = []
    seen_signals: set[str] = set()
    for decision in ordered:
        if decision.machine_signal_status in seen_signals:
            continue
        selected.append(decision)
        seen_signals.add(decision.machine_signal_status)
        if len(selected) == MAX_REPRESENTATIVE_PAPERS:
            return selected
    for decision in ordered:
        if decision in selected:
            continue
        selected.append(decision)
        if len(selected) == MAX_REPRESENTATIVE_PAPERS:
            break
    return selected


def derive_ingredient_primary_status(decisions: Sequence[PaperDecision]) -> str:
    """Choose the best usable report path without hiding rejected report rows."""

    eligible = [row for row in decisions if row.eligibility_status == "eligible"]
    if eligible:
        verified = [
            row for row in eligible if row.verification_status == "full_text_verified"
        ]
        if not verified:
            return "abstract_insufficient"
        statuses = {status for row in verified for status in row.statuses}
        return min(statuses or {"abstract_insufficient"}, key=STATUS_RANK.__getitem__)
    if any(row.eligibility_status == "not_assessable" for row in decisions):
        return "abstract_insufficient"
    if any(row.eligibility_status == "formulation_not_isolated" for row in decisions):
        return "formulation_only"
    if decisions:
        return "reject_wrong_scope"
    return "abstract_insufficient"


def _log_index(rows: Sequence[Mapping[str, str]]) -> dict[str, Mapping[str, str]]:
    return {row.get("ingredient_id", ""): row for row in rows if row.get("ingredient_id")}


def _first_log_value(row: Mapping[str, str], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field, "")).strip()
        if value:
            return value
    return ""


def _log_boolean(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if normalized in {"y", "yes", "true", "1", "complete"}:
        return True
    if normalized in {"n", "no", "false", "0", "incomplete"}:
        return False
    return None


def build_search_run_rows(
    review_targets: Sequence[Mapping[str, str]],
    *,
    source_query_logs: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    ingredient_terms: Mapping[str, Sequence[str]] | None = None,
    provenance: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Normalize one search provenance row per target ingredient and source."""

    source_query_logs = source_query_logs or {}
    ingredient_terms = ingredient_terms or {}
    provenance = provenance or {
        "manifest_version": MANIFEST_VERSION,
        "manifest_sha256": canonical_manifest_sha256(review_targets),
    }
    indexes = {source: _log_index(rows) for source, rows in source_query_logs.items()}
    roles = {
        "pubmed": "bibliographic_primary",
        "europe_pmc": "bibliographic_primary",
        "crossref": "metadata_discovery",
        "openalex": "metadata_discovery",
        "kci": "regional_bibliographic",
        "riss": "regional_bibliographic",
    }
    rows: list[dict[str, object]] = []
    for target in sorted(review_targets, key=lambda row: int(row["ingredient_rank"])):
        ingredient_id = target["ingredient_id"]
        for source in ("pubmed", "europe_pmc", "crossref", "openalex", "kci", "riss"):
            query = ""
            searched_at = "not_recorded"
            cutoff = "not_recorded"
            raw_count: object = "unknown"
            retrieved_count: object = "unknown"
            selected_count: object = "not_applicable"
            pagination_complete = "unknown"
            failure_reason = ""
            query_contract_status = "not_assessed"
            log = indexes.get(source, {}).get(ingredient_id)
            input_provenance = "fresh_v1_1_source_search"
            explicit_rerun = ""
            if log is None:
                searched_name = target.get("name_en", "")
                query_contract_status = "not_applicable_not_run"
                search_status = "not_attempted"
                source_run_status = "provenance_incomplete"
                pagination_complete = "not_applicable"
                failure_reason = f"{source} fresh v1.1 query-log row is missing"
                input_provenance = "missing_fresh_v1_1_source_log"
            else:
                searched_name = _first_log_value(
                    log, "searched_name", "canonical_name_en", "name_en"
                ) or target.get("name_en", "")
                query = _first_log_value(log, "search_query", "query")
                searched_at = _first_log_value(
                    log,
                    "searched_at",
                    "searched_at_utc",
                    "completed_at_utc",
                    "started_at_utc",
                ) or "not_recorded"
                cutoff = _first_log_value(log, "cutoff_date") or searched_at[:10]
                raw_count = _first_log_value(
                    log,
                    "raw_hit_count",
                    "total_hit_count",
                    "source_total_count",
                    "raw_count",
                ) or "0"
                retrieved_count = _first_log_value(
                    log, "returned_count", "retrieved_count"
                ) or "0"
                selected_count = _first_log_value(log, "selected_count") or "not_applicable"
                query_contract_status = _first_log_value(
                    log, "query_contract_status"
                ) or (
                    "approved_terms_only"
                    if _first_log_value(
                        log, "approved_search_terms", "approved_search_terms_json"
                    )
                    else "not_assessed"
                )
                request_status = _first_log_value(log, "request_status").casefold()
                ok = request_status in {"ok", "success", "completed", "zero_results"}
                failure_reason = _first_log_value(
                    log, "error_message", "failure_reason"
                )
                explicit_pagination = _first_log_value(
                    log, "pagination_complete", "retrieval_complete"
                )
                pagination_bool = _log_boolean(explicit_pagination)
                pagination_status = _first_log_value(log, "pagination_status").casefold()
                cap_reached = _log_boolean(_first_log_value(log, "cap_reached")) is True or (
                    "cap" in pagination_status
                )
                if pagination_bool is None:
                    try:
                        pagination_bool = int(str(raw_count)) <= int(str(retrieved_count))
                    except ValueError:
                        pagination_bool = None
                pagination_complete = (
                    "true"
                    if pagination_bool is True
                    else "false"
                    if pagination_bool is False
                    else "unknown"
                )
                input_provenance = _first_log_value(
                    log, "input_provenance", "pipeline_version"
                ) or input_provenance
                explicit_rerun = _first_log_value(log, "rerun_required").upper()

                if request_status in {
                    "access_unavailable",
                    "blocked_by_robots",
                    "credentials_unavailable",
                }:
                    search_status = "access_unavailable"
                    source_run_status = "access_unavailable"
                    pagination_complete = "not_applicable"
                    if not failure_reason:
                        failure_reason = f"{source} access was unavailable for this run"
                elif not ok:
                    search_status = "technical_failure"
                    source_run_status = "technical_failure"
                    if not failure_reason:
                        failure_reason = f"{source} request did not complete successfully"
                elif str(raw_count) == "0":
                    search_status = "zero_results"
                    source_run_status = "success"
                elif pagination_bool is True:
                    search_status = "success"
                    source_run_status = "success"
                elif cap_reached:
                    search_status = "success_protocol_capped"
                    source_run_status = "success_protocol_capped"
                    if not failure_reason:
                        failure_reason = (
                            "Fresh v1.1 relevance-ranked retrieval cap reached; "
                            "the declared search protocol completed but full source "
                            "pagination was not attempted"
                        )
                else:
                    search_status = "partial"
                    source_run_status = "partial"
                    if not failure_reason:
                        failure_reason = (
                            f"{source} returned fewer records than required by its protocol"
                        )

            if explicit_rerun in {"Y", "N"}:
                rerun_required = explicit_rerun == "Y"
            else:
                rerun_required = (
                    query_contract_status != "approved_terms_only"
                    or search_status
                    in {
                        "partial",
                        "technical_failure",
                        "not_attempted",
                    }
                )
            rows.append(
                {
                    "ingredient_rank": target["ingredient_rank"],
                    "ingredient_id": ingredient_id,
                    "source": source,
                    "source_role": roles[source],
                    "searched_name": searched_name,
                    "query": query,
                    "searched_at": searched_at,
                    "cutoff_date": cutoff,
                    "raw_count": raw_count,
                    "retrieved_count": retrieved_count,
                    "selected_count": selected_count,
                    "pagination_complete": pagination_complete,
                    "search_status": search_status,
                    "source_run_status": source_run_status,
                    "failure_reason": failure_reason,
                    "input_provenance": input_provenance,
                    "query_contract_status": query_contract_status,
                    "rerun_required": "Y" if rerun_required else "N",
                    "review_status": REVIEW_STATUS,
                    "runtime_score_change": "none",
                    **_provenance_columns(provenance),
                    "policy_version": POLICY_VERSION,
                }
            )
    return rows


def _provisional_outcome_result_id(
    decision: PaperDecision,
    outcome: OutcomeDecision,
    outcome_rank: int,
) -> str:
    """Return a unique deterministic ID until full-text outcome keys exist."""

    metadata = decision.item.candidate.metadata
    payload = "\x1f".join(
        (
            decision.item.candidate.ingredient_id,
            paper_key(metadata),
            "not_clustered",
            "not_extracted",
            outcome.source.get("evidence_span", ""),
            str(outcome_rank),
        )
    ).encode("utf-8")
    return f"outcome:{hashlib.sha256(payload).hexdigest()[:24]}"


def _outcome_result_row(
    decision: PaperDecision,
    outcome: OutcomeDecision,
    outcome_rank: int,
    provenance: Mapping[str, object],
) -> dict[str, object]:
    metadata = decision.item.candidate.metadata
    key = paper_key(metadata)
    source = outcome.source
    span = source.get("evidence_span", "")
    p_match = P_VALUE_RE.search(span)
    hedge_match = UNCERTAIN_EFFECT_RE.search(span)
    return {
        "ingredient_id": decision.item.candidate.ingredient_id,
        "paper_key": key,
        "report_id": key,
        "outcome_result_id": _provisional_outcome_result_id(
            decision, outcome, outcome_rank
        ),
        "outcome_id_status": "provisional_abstract",
        "outcome_rank": outcome_rank,
        "study_id": "not_clustered",
        "comparison_id": "not_extracted",
        "pmid": metadata.pmid,
        "doi": metadata.doi,
        "section": "not_extracted",
        "page_table_figure": "not_extracted",
        "evidence_span": span,
        "arm_ids": "not_extracted",
        "ingredient_outcome_relation": source.get("ingredient_outcome_relation", ""),
        "effect_mapping_status": outcome.effect_mapping_status,
        "effect_id": (
            source.get("mapped_effect_ids", "")
            if outcome.effect_mapping_status == "mapped_existing"
            else "not_applicable"
        ),
        "mapped_effect_ids": source.get("mapped_effect_ids", ""),
        "raw_new_effect_candidate": source.get("new_effect_candidate", ""),
        "new_effect_candidate": (
            source.get("new_effect_candidate", "")
            if outcome.effect_mapping_status == "new_effect_candidate"
            else ""
        ),
        "raw_outcome_name": "not_extracted",
        "outcome_concept_id": "not_extracted",
        "positive_direction": "not_extracted",
        "instrument": "not_extracted",
        "model": "not_extracted",
        "channel": "not_extracted",
        "parameter": "not_extracted",
        "unit": "not_extracted",
        "estimate_direction": outcome.estimate_direction,
        "outcome_direction": outcome.outcome_direction,
        "study_design": decision.study_design,
        "contrast_type": (
            "eligible_abstract_contrast"
            if outcome.eligible_contrast
            else "not_extracted"
        ),
        "eligible_contrast": "Y" if outcome.eligible_contrast else "N",
        "p_or_ci_in_span": "Y" if outcome.p_or_ci_in_span else "N",
        "p_value_operator": (
            P_VALUE_OPERATOR_CODES[p_match.group("operator")]
            if p_match
            else "not_extracted"
        ),
        "p_value": p_match.group("value") if p_match else "not_extracted",
        "ci_low": "not_extracted",
        "ci_high": "not_extracted",
        "alpha": "not_extracted",
        "n_analyzed_by_arm": "not_extracted",
        "paired_analysis": "not_extracted",
        "multiplicity_adjusted": "not_extracted",
        "analysis_population": "not_extracted",
        "pre_post_comparison": "Y" if outcome.pre_post_comparison else "N",
        "objective_or_validated_measure": (
            "Y" if outcome.objective_or_validated_measure else "N"
        ),
        "statistical_gate_status": outcome.statistical_gate_status,
        "statistical_support": "Y" if outcome.statistical_support else "N",
        "statistical_conclusion": (
            "no_detectable_difference"
            if outcome.statistical_support
            and outcome.outcome_direction == "no_detectable_difference"
            else "difference_supported"
            if outcome.statistical_support
            else "not_supported_or_not_extracted"
        ),
        "equivalence_supported": "not_extracted",
        "safety_signal": "not_extracted",
        "hedge_flag": "Y" if hedge_match else "N",
        "hedge_span": hedge_match.group(0) if hedge_match else "",
        "explicit_result_available": (
            "Y"
            if outcome.estimate_direction not in {"unclear", "not_applicable"}
            else "N"
        ),
        "intervention_arm": "not_extracted",
        "comparator_arm": "not_extracted",
        "timepoint": "not_extracted",
        "estimate": "not_extracted",
        "effect_estimate": "not_extracted",
        "estimate_type": "unknown",
        "estimate_unit": "unknown",
        "eligibility_status": decision.eligibility_status,
        "verification_status": decision.verification_status,
        "applicability_status": decision.applicability_status,
        "score_status": (
            "not_scoreable"
            if decision.full_text_status == "not_checked"
            else decision.score_status
        ),
        "machine_signal_status": outcome.machine_signal_status,
        "full_text_status": decision.full_text_status,
        "review_status": REVIEW_STATUS,
        "runtime_score_change": "none",
        **_provenance_columns(provenance),
        "policy_version": POLICY_VERSION,
    }


def _overall_source_status(search_rows: Sequence[Mapping[str, object]]) -> dict[str, str]:
    output: dict[str, str] = {}
    by_source: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in search_rows:
        by_source[str(row["source"])].append(row)
    for source, rows in by_source.items():
        run_statuses = {str(row["source_run_status"]) for row in rows}
        if "technical_failure" in run_statuses:
            output[source] = "technical_failure"
        elif "access_unavailable" in run_statuses:
            output[source] = "access_unavailable"
        elif "partial" in run_statuses:
            output[source] = "partial"
        elif run_statuses <= {"success", "success_protocol_capped"}:
            output[source] = (
                "success_protocol_capped"
                if "success_protocol_capped" in run_statuses
                else "success"
            )
        else:
            output[source] = "provenance_incomplete"
    return output


def build_adjudication_v11(
    *,
    target_rows: Sequence[Mapping[str, str]],
    runtime_ingredient_ids: set[str],
    candidates: Sequence[CandidatePaper],
    ingredient_terms: Mapping[str, Sequence[str]],
    review_ingredient_ids: Sequence[str] | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    source_query_logs: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    non_runtime_targets = sorted(
        (row for row in target_rows if row["ingredient_id"] not in runtime_ingredient_ids),
        key=lambda row: int(row["ingredient_rank"]),
    )
    if review_ingredient_ids is None:
        review_targets = non_runtime_targets[:466]
    else:
        manifest_ids = stable_unique(review_ingredient_ids)
        target_by_id = {row["ingredient_id"]: row for row in non_runtime_targets}
        missing = [
            ingredient_id
            for ingredient_id in manifest_ids
            if ingredient_id not in target_by_id
        ]
        if missing:
            raise ValueError(
                "The frozen v1 manifest contains ingredients missing from the current "
                f"non-runtime target input: {missing[:5]}"
            )
        review_targets = [target_by_id[ingredient_id] for ingredient_id in manifest_ids]
    if len(review_targets) != 466:
        raise ValueError(f"Expected exactly 466 review targets, found {len(review_targets)}")

    provenance = build_provenance_metadata(data_dir, review_targets)
    search_rows = build_search_run_rows(
        review_targets,
        source_query_logs=source_query_logs,
        ingredient_terms=ingredient_terms,
        provenance=provenance,
    )
    searches_by_ingredient: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in search_rows:
        searches_by_ingredient[str(row["ingredient_id"])].append(row)

    candidates_by_ingredient: dict[str, list[CandidatePaper]] = defaultdict(list)
    for candidate in candidates:
        candidates_by_ingredient[candidate.ingredient_id].append(candidate)

    ingredient_rows: list[dict[str, object]] = []
    paper_rows: list[dict[str, object]] = []
    outcome_rows: list[dict[str, object]] = []
    for target in review_targets:
        ingredient_id = target["ingredient_id"]
        raw = candidates_by_ingredient.get(ingredient_id, [])
        deduped = merge_candidate_papers(raw)
        decisions = [
            decide_paper(
                evaluate_paper(candidate, ingredient_terms[ingredient_id]),
                ingredient_terms[ingredient_id],
            )
            for candidate in deduped
            if candidate.metadata.title
        ]
        representatives = select_representatives(decisions)
        all_statuses = sorted(
            {status for decision in decisions for status in decision.statuses}
            or {"abstract_insufficient"},
            key=STATUS_RANK.__getitem__,
        )
        machine_statuses = sorted(
            {
                status
                for decision in representatives
                for status in decision.machine_signal_statuses
            }
            or {"abstract_insufficient"},
            key=MACHINE_SIGNAL_RANK.__getitem__,
        )
        has_positive = any(
            status in {"score_candidate_positive", "score_candidate_supporting"}
            for status in machine_statuses
        )
        has_negative = "negative_or_null" in machine_statuses
        assessable_decisions = [
            decision
            for decision in decisions
            if decision.eligibility_status in {"eligible", "not_assessable"}
        ]
        representative_assessable = [
            decision
            for decision in representatives
            if decision.eligibility_status in {"eligible", "not_assessable"}
        ]
        primary_status = derive_ingredient_primary_status(decisions)
        effects = sorted(
            {
                effect
                for decision in representative_assessable
                for effect in decision.mapped_effect_ids
            }
        )
        new_effects = sorted(
            {
                effect
                for decision in representative_assessable
                for effect in decision.new_effect_candidates
            }
        )
        ingredient_searches = searches_by_ingredient[ingredient_id]
        source_status = {
            str(row["source"]): {
                "search_status": row["search_status"],
                "source_run_status": row["source_run_status"],
                "query_contract_status": row["query_contract_status"],
                "rerun_required": row["rerun_required"],
            }
            for row in ingredient_searches
        }
        retrieved = sum(
            int(str(row["retrieved_count"]))
            for row in ingredient_searches
            if str(row["retrieved_count"]).isdigit()
        )
        required_rerun = any(row["rerun_required"] == "Y" for row in ingredient_searches)
        capped = any(
            row["search_status"] == "success_protocol_capped"
            for row in ingredient_searches
        )
        access_limited = any(
            row["search_status"] == "access_unavailable"
            for row in ingredient_searches
        )
        search_status = (
            "partial"
            if required_rerun
            else "complete_with_source_access_limitations"
            if access_limited
            else "complete_protocol_capped"
            if capped
            else "complete"
        )
        search_result_status = (
            "results_retrieved" if retrieved else "zero_results_all_retrieved_sources"
        )
        ingredient_rows.append(
            {
                "ingredient_rank": target["ingredient_rank"],
                "ingredient_id": ingredient_id,
                "name_ko": target.get("name_ko", ""),
                "name_en": target.get("name_en", ""),
                "canonical_name": target.get("name_en", ""),
                "ingredient_entity_type": "not_extracted",
                "product_count": target.get("product_count", "0"),
                "search_status": search_status,
                "search_result_status": search_result_status,
                "source_status_json": json.dumps(
                    source_status, sort_keys=True, separators=(",", ":")
                ),
                "sources_searched": "|".join(
                    f"{row['source']}:{row['search_status']}"
                    for row in ingredient_searches
                    if row["search_status"] not in {"access_unavailable", "not_attempted"}
                ),
                "sources_not_searched": "|".join(
                    f"{row['source']}:{row['search_status']}"
                    for row in ingredient_searches
                    if row["search_status"] in {"access_unavailable", "not_attempted"}
                ),
                "raw_candidate_count": len(raw),
                "deduplicated_paper_count": len(decisions),
                "representative_paper_count": len(representatives),
                "eligibility_status": _aggregate_by_priority(
                    [decision.eligibility_status for decision in decisions],
                    priority=(
                        "eligible",
                        "not_assessable",
                        "formulation_not_isolated",
                        "retracted",
                        "wrong_ingredient",
                        "wrong_route_or_site",
                        "ineligible_design",
                    ),
                    empty="not_assessable",
                ),
                "all_eligibility_statuses": "|".join(
                    sorted({decision.eligibility_status for decision in decisions})
                ),
                "verification_status": _aggregate_by_priority(
                    [decision.verification_status for decision in assessable_decisions],
                    priority=(
                        "full_text_verified",
                        "abstract_only",
                        "correction_pending",
                        "full_text_unavailable",
                        "validity_hold",
                    ),
                    empty="abstract_only",
                ),
                "all_verification_statuses": "|".join(
                    sorted({decision.verification_status for decision in decisions})
                ),
                "applicability_status": _aggregate_by_priority(
                    [decision.applicability_status for decision in assessable_decisions],
                    priority=(
                        "general_skin",
                        "medical_context_limited",
                        "experimental_challenge_limited",
                        "safety_only",
                        "not_applicable",
                    ),
                    empty="not_applicable",
                ),
                "all_applicability_statuses": "|".join(
                    sorted({decision.applicability_status for decision in decisions})
                ),
                "effect_mapping_status": _aggregate_by_priority(
                    [
                        decision.effect_mapping_status
                        for decision in (representative_assessable or representatives)
                    ],
                    priority=(
                        "mapped_existing",
                        "new_effect_candidate",
                        "unmapped_outcome",
                        "not_mapped",
                    ),
                    empty="not_mapped",
                ),
                "outcome_direction": _aggregate_outcome_direction(
                    [
                        decision.outcome_direction
                        for decision in (representative_assessable or representatives)
                    ]
                ),
                "score_status": "not_scoreable",
                "machine_signal_status": machine_statuses[0],
                "primary_status": primary_status,
                "all_statuses": "|".join(all_statuses),
                "all_machine_signal_statuses": "|".join(machine_statuses),
                "conflicting_evidence": "Y" if has_positive and has_negative else "N",
                "candidate_effect_ids": "|".join(effects),
                "new_effect_candidates": "|".join(new_effects),
                "representative_paper_keys": "|".join(
                    paper_key(decision.item.candidate.metadata) for decision in representatives
                ),
                "full_text_gate": (
                    "required_before_scoring" if decisions else "not_applicable_no_evidence"
                ),
                "status_scope": "machine_screening_only",
                "review_status": REVIEW_STATUS,
                "runtime_score_change": "none",
                **_provenance_columns(provenance),
                "policy_version": POLICY_VERSION,
            }
        )
        for decision in representatives:
            metadata = decision.item.candidate.metadata
            key = paper_key(metadata)
            paper_rows.append(
                {
                    "ingredient_id": ingredient_id,
                    "paper_key": key,
                    "report_id": key,
                    "study_id": "not_clustered",
                    "pmid": metadata.pmid,
                    "doi": metadata.doi,
                    "title": metadata.title,
                    "journal": metadata.journal,
                    "publication_date": metadata.publication_date,
                    "publication_types": "; ".join(metadata.publication_types),
                    "sources": "|".join(decision.item.candidate.sources),
                    "retrieval_status": "retrieved_from_legacy_search_inputs",
                    "evidence_tier": decision.item.assessment.evidence_tier,
                    "evidence_kind": decision.item.assessment.evidence_kind,
                    "study_design": decision.study_design,
                    "design": "not_extracted",
                    "randomized": "not_extracted",
                    "controlled": "not_extracted",
                    "within_person": "not_extracted",
                    "comparator_type": "not_extracted",
                    "prospective": "not_extracted",
                    "design_source_span": "not_extracted",
                    "risk_of_bias_overall": "not_checked",
                    "relation_scope": decision.item.assessment.relation_scope,
                    "raw_ingredient_term": "not_extracted",
                    "entity_match_type": "machine_name_match_unverified",
                    "intervention_role": "not_extracted",
                    "ingredient_match_span": "not_extracted",
                    "ingredient_reject_reason": (
                        decision.eligibility_status
                        if decision.eligibility_status == "wrong_ingredient"
                        else ""
                    ),
                    "applicability": decision.item.assessment.applicability,
                    "eligibility_status": decision.eligibility_status,
                    "verification_status": decision.verification_status,
                    "applicability_status": decision.applicability_status,
                    "route": "not_extracted",
                    "body_site": "not_extracted",
                    "skin_condition": "not_extracted",
                    "population_type": "not_extracted",
                    "challenge_model": "not_extracted",
                    "application_regimen": "not_extracted",
                    "effect_mapping_status": decision.effect_mapping_status,
                    "outcome_direction": decision.outcome_direction,
                    "score_status": decision.score_status,
                    "machine_signal_status": decision.machine_signal_status,
                    "primary_status": decision.primary_status,
                    "all_statuses": "|".join(decision.statuses),
                    "all_machine_signal_statuses": "|".join(decision.machine_signal_statuses),
                    "mapped_effect_ids": "|".join(decision.mapped_effect_ids),
                    "new_effect_candidates": "|".join(decision.new_effect_candidates),
                    "directions": "|".join(decision.directions),
                    "statistical_support": "Y" if decision.statistical_support else "N",
                    "preprint_flag": "Y" if decision.preprint_flag else "N",
                    "case_report_flag": "Y" if decision.case_report_flag else "N",
                    "safety_only_flag": "Y" if decision.safety_only_flag else "N",
                    "medical_context_limited": "Y" if decision.medical_context_limited else "N",
                    "experimental_challenge_limited": (
                        "Y" if decision.experimental_challenge_limited else "N"
                    ),
                    "route_site_mismatch": "Y" if decision.route_site_mismatch else "N",
                    "formulation_isolation_status": decision.formulation_isolation_status,
                    "test_arm_components": "not_extracted",
                    "control_arm_components": "not_extracted",
                    "target_concentration_by_arm": "not_extracted",
                    "cointerventions_equal": "not_checked",
                    "isolation_status": decision.formulation_isolation_status,
                    "isolation_evidence_span": "not_extracted",
                    "correction_flag": "Y" if decision.correction_flag else "N",
                    "retraction_flag": "Y" if decision.retraction_flag else "N",
                    "expression_of_concern_flag": (
                        "Y" if decision.expression_of_concern_flag else "N"
                    ),
                    "duplicate_trial_status": decision.duplicate_trial_status,
                    "retraction_status": (
                        "bibliographic_signal_detected"
                        if decision.retraction_flag
                        else "not_checked"
                    ),
                    "validity_checked_at": "not_checked",
                    "validity_source": "not_checked",
                    "correction_id": "not_extracted",
                    "correction_impact": (
                        "pending_review" if decision.correction_flag else "not_applicable"
                    ),
                    "funding": "not_extracted",
                    "conflict_of_interest": "not_extracted",
                    "full_text_status": decision.full_text_status,
                    "evidence_spans": " || ".join(
                        row.get("evidence_span", "") for row in decision.item.outcomes
                    ),
                    "status_scope": "machine_screening_only",
                    "review_status": REVIEW_STATUS,
                    "runtime_score_change": "none",
                    **_provenance_columns(provenance),
                    "policy_version": POLICY_VERSION,
                }
            )
            outcome_rows.extend(
                _outcome_result_row(decision, outcome, index, provenance)
                for index, outcome in enumerate(decision.outcome_decisions, start=1)
            )

    status_counts = Counter(row["primary_status"] for row in ingredient_rows)
    summary = {
        "generated_on": date.today().isoformat(),
        "policy_version": POLICY_VERSION,
        **provenance,
        "workflow_status": (
            "search_complete_machine_screening_complete_manual_verification_pending"
            if not any(row["rerun_required"] == "Y" for row in search_rows)
            else "search_completed_with_retry_items_machine_screening_complete"
        ),
        "adjudication_complete": False,
        "portfolio_ingredient_count": len(runtime_ingredient_ids) + len(ingredient_rows),
        "existing_runtime_ingredient_count": len(runtime_ingredient_ids),
        "adjudicated_ingredient_count": len(ingredient_rows),
        "non_runtime_candidates_outside_466_capacity": (
            len(non_runtime_targets) - len(review_targets)
        ),
        "representative_paper_count": len(paper_rows),
        "outcome_result_count": len(outcome_rows),
        "search_run_count": len(search_rows),
        "search_run_rerun_required_count": sum(
            row["rerun_required"] == "Y" for row in search_rows
        ),
        "ingredient_search_rerun_required_count": len(
            {
                row["ingredient_id"]
                for row in search_rows
                if row["rerun_required"] == "Y"
            }
        ),
        "query_contract_status_counts": dict(
            sorted(Counter(row["query_contract_status"] for row in search_rows).items())
        ),
        "full_text_checked_count": sum(row["full_text_status"] == "checked" for row in paper_rows),
        "representative_effect_mapped_count": sum(
            bool(row["mapped_effect_ids"]) for row in paper_rows
        ),
        "representative_direction_determined_count": sum(
            row["outcome_direction"] not in {"", "not_applicable", "unclear"}
            for row in paper_rows
        ),
        "primary_status_counts": dict(sorted(status_counts.items())),
        "score_status_counts": dict(
            sorted(Counter(row["score_status"] for row in ingredient_rows).items())
        ),
        "source_status": _overall_source_status(search_rows),
        "status_note": (
            "Search zero-results are stored only in search_status. Abstract-only positive "
            "or supporting signals are retained in machine_signal_status and remain not_scoreable."
        ),
        "review_status": REVIEW_STATUS,
        "runtime_changed": False,
    }
    return ingredient_rows, paper_rows, outcome_rows, search_rows, summary


def build_adjudication(
    *,
    target_rows: Sequence[Mapping[str, str]],
    runtime_ingredient_ids: set[str],
    candidates: Sequence[CandidatePaper],
    ingredient_terms: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    """Backward-compatible three-value facade over the v1.1 core."""

    ingredient_rows, paper_rows, _, _, summary = build_adjudication_v11(
        target_rows=target_rows,
        runtime_ingredient_ids=runtime_ingredient_ids,
        candidates=candidates,
        ingredient_terms=ingredient_terms,
    )
    return ingredient_rows, paper_rows, summary


def _csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def validate_fresh_source_inputs(
    *,
    manifest_ids: Sequence[str],
    candidate_paths: Mapping[str, Path],
    query_log_paths: Mapping[str, Path],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    """Fail closed unless every declared fresh source artifact is complete.

    A source whose collection is structurally unavailable still needs a
    466-row query ledger and a header-only candidate ledger.  Silently treating
    a missing source file as an empty search would make the final package look
    complete when it is not.
    """

    expected_ids = list(manifest_ids)
    expected_id_set = set(expected_ids)
    required_log_fields = {
        "source",
        "ingredient_id",
        "search_query",
        "request_status",
        "returned_count",
        "query_contract_status",
        "review_status",
        "runtime_score_change",
    }
    required_candidate_fields = {
        "source",
        "ingredient_id",
        "title",
        "review_status",
        "runtime_score_change",
    }
    logs_by_source: dict[str, list[dict[str, str]]] = {}
    candidates_by_source: dict[str, list[dict[str, str]]] = {}
    for source in ("pubmed", "europe_pmc", "crossref", "openalex", "kci", "riss"):
        log_path = query_log_paths[source]
        candidate_path = candidate_paths[source]
        if not log_path.is_file():
            raise FileNotFoundError(f"Fresh {source} query ledger is missing: {log_path}")
        if not candidate_path.is_file():
            raise FileNotFoundError(
                f"Fresh {source} candidate ledger is missing: {candidate_path}"
            )

        log_header = set(_csv_header(log_path))
        candidate_header = set(_csv_header(candidate_path))
        missing_log_fields = sorted(required_log_fields - log_header)
        missing_candidate_fields = sorted(required_candidate_fields - candidate_header)
        if missing_log_fields:
            raise ValueError(
                f"Fresh {source} query ledger lacks required fields: "
                + ", ".join(missing_log_fields)
            )
        if missing_candidate_fields:
            raise ValueError(
                f"Fresh {source} candidate ledger lacks required fields: "
                + ", ".join(missing_candidate_fields)
            )

        logs = read_csv(log_path)
        candidates = read_csv(candidate_path)
        logged_ids = [row.get("ingredient_id", "") for row in logs]
        if len(logs) != len(expected_ids) or logged_ids != expected_ids:
            raise ValueError(
                f"Fresh {source} query ledger must match the ordered frozen manifest: "
                f"rows={len(logs)} ordered_match={logged_ids == expected_ids}"
            )
        if any(row.get("source") != source for row in logs):
            raise ValueError(f"Fresh {source} query ledger contains a wrong source value")
        if any(
            row.get("review_status") != REVIEW_STATUS
            or row.get("runtime_score_change") != "none"
            for row in logs
        ):
            raise ValueError(f"Fresh {source} query ledger violates review/runtime invariants")
        if any(row.get("query_contract_status") != "approved_terms_only" for row in logs):
            raise ValueError(f"Fresh {source} query ledger is not approved-terms-only")

        if any(row.get("ingredient_id", "") not in expected_id_set for row in candidates):
            raise ValueError(f"Fresh {source} candidates contain an out-of-manifest ingredient")
        if any(row.get("source") != source for row in candidates):
            raise ValueError(f"Fresh {source} candidates contain a wrong source value")
        if any(
            row.get("review_status") != REVIEW_STATUS
            or row.get("runtime_score_change") != "none"
            for row in candidates
        ):
            raise ValueError(f"Fresh {source} candidates violate review/runtime invariants")
        returned_sum = sum(int(row.get("returned_count") or 0) for row in logs)
        if returned_sum != len(candidates):
            raise ValueError(
                f"Fresh {source} returned_count sum does not match candidate rows: "
                f"{returned_sum} != {len(candidates)}"
            )
        if "query_id" in candidate_header:
            query_ids = {row.get("query_id", "") for row in logs}
            if any(row.get("query_id", "") not in query_ids for row in candidates):
                raise ValueError(f"Fresh {source} candidate has an unknown query_id")

        logs_by_source[source] = logs
        candidates_by_source[source] = candidates
    return candidates_by_source, logs_by_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_500.csv"),
    )
    parser.add_argument(
        "--v1-manifest",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466.csv"),
        help="Frozen v1 ingredient ledger whose 466 ingredient IDs define the v1.1 cohort.",
    )
    parser.add_argument("--runtime-effects", type=Path, default=Path("data/ingredient_effect.csv"))
    parser.add_argument(
        "--pubmed",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/pubmed_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--pubmed-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/pubmed_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--europe-pmc",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/europe_pmc_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--crossref",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/crossref_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--openalex",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/openalex_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--kci",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/kci_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--riss",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/riss_candidates_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--europe-pmc-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/europe_pmc_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--crossref-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/crossref_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--openalex-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/openalex_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--kci-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/kci_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument(
        "--riss-query-log",
        type=Path,
        default=Path(
            "data/reconciliation/v1_1_fresh/riss_query_log_466_v1_1_fresh.csv"
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--ingredient-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466_v1_1.csv"),
    )
    parser.add_argument(
        "--paper-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_representatives_466_v1_1.csv"),
    )
    parser.add_argument(
        "--outcome-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_outcome_results_466_v1_1.csv"),
    )
    parser.add_argument(
        "--search-run-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_search_runs_466_v1_1.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_evidence_adjudication_466_v1_1_summary.json"),
    )
    args = parser.parse_args()

    targets = read_csv(args.targets)
    target_ids = {row["ingredient_id"] for row in targets}
    terms = load_approved_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        target_ids,
    )
    manifest_rows = read_csv(args.v1_manifest)
    manifest_ids = [row["ingredient_id"] for row in manifest_rows]
    candidate_rows_by_source, query_logs = validate_fresh_source_inputs(
        manifest_ids=manifest_ids,
        candidate_paths={
            "pubmed": args.pubmed,
            "europe_pmc": args.europe_pmc,
            "crossref": args.crossref,
            "openalex": args.openalex,
            "kci": args.kci,
            "riss": args.riss,
        },
        query_log_paths={
            "pubmed": args.pubmed_query_log,
            "europe_pmc": args.europe_pmc_query_log,
            "crossref": args.crossref_query_log,
            "openalex": args.openalex_query_log,
            "kci": args.kci_query_log,
            "riss": args.riss_query_log,
        },
    )
    candidates = [
        pubmed_candidate(row) for row in candidate_rows_by_source["pubmed"]
    ]
    for source in ("europe_pmc", "crossref", "openalex", "kci", "riss"):
        for raw_row in candidate_rows_by_source[source]:
            row = dict(raw_row)
            row["publication_date"] = (
                row.get("publication_date", "")
                or row.get("publication_year", "")
            )
            row["abstract"] = row.get("abstract", "") or row.get("pre_abstract", "")
            candidates.append(external_candidate(row))
    ingredient_rows, paper_rows, outcome_rows, search_rows, summary = build_adjudication_v11(
        target_rows=targets,
        runtime_ingredient_ids=read_runtime_ingredient_ids(args.runtime_effects),
        candidates=candidates,
        ingredient_terms=terms,
        review_ingredient_ids=manifest_ids,
        data_dir=args.data_dir,
        source_query_logs=query_logs,
    )
    write_csv(args.ingredient_output, INGREDIENT_FIELDS, ingredient_rows)
    write_csv(args.paper_output, PAPER_FIELDS, paper_rows)
    write_csv(args.outcome_output, OUTCOME_RESULT_FIELDS, outcome_rows)
    write_csv(args.search_run_output, SEARCH_RUN_FIELDS, search_rows)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Ingredient evidence v1.1 screening ledgers complete: "
        f"ingredients={len(ingredient_rows)} representatives={len(paper_rows)} "
        f"outcomes={len(outcome_rows)} search_runs={len(search_rows)} "
        f"statuses={summary['primary_status_counts']}"
    )


if __name__ == "__main__":
    main()
