#!/usr/bin/env python3
"""Assess whether ingredient-first PubMed signals can inform scoring.

This is a review-only gate. It distinguishes benefit-score candidates,
null/conflicting human evidence, preclinical support, risk evidence, new effect
axes, formulation-only evidence, and reference-only evidence. It never writes
runtime seeds, DB rows, or recommendation scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from build_ingredient_first_paper_catalog import (
    _paper_evidence_roles,
    extract_outcomes,
    read_csv,
    write_csv,
)
from discover_new_evidence import PaperMetadata, load_ingredient_terms
from screen_effect_review_candidates import PaperAssessment, assess_paper_candidate


POLICY_VERSION = "mwbl-score-eligibility-review-v1"

CLAIM_FIELDS = [
    "cohort",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "paper_key",
    "pmid",
    "doi",
    "title",
    "evidence_tier",
    "relation_scope",
    "applicability",
    "claim_category",
    "effect_id",
    "new_effect_candidate",
    "direction",
    "evidence_span",
    "recommended_score_use",
    "review_status",
    "runtime_score_change",
]

INGREDIENT_FIELDS = [
    "cohort",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "raw_pubmed_hit_count",
    "representative_paper_count",
    "benefit_candidate_count",
    "uncertain_effect_count",
    "conflict_or_zero_candidate_count",
    "mechanism_support_count",
    "risk_candidate_count",
    "safety_signal_count",
    "new_effect_candidate_count",
    "formulation_paper_count",
    "reference_paper_count",
    "best_benefit_tier",
    "candidate_effect_ids",
    "candidate_new_effects",
    "candidate_pmids",
    "score_eligibility_decision",
    "recommended_runtime_use",
    "can_change_benefit_score_now",
    "review_status",
    "runtime_score_change",
]


@dataclass(frozen=True)
class ClaimDecision:
    category: str
    recommended_score_use: str


CLEAR_ADVERSE_TITLE_RE = re.compile(
    r"\b(allergic contact dermatitis|contact dermatitis|contact allergy|"
    r"sensiti[sz](?:er|ers|ation|ing)?|contact allergen|skin irritation|"
    r"irritant|phototoxic|comedogenic|acnegenic)\b",
    re.IGNORECASE,
)
UNCERTAIN_EFFECT_RE = re.compile(
    r"\b(trend|may|might|could|suggest(?:s|ed)?|possible|potential|"
    r"inconclusive|uncertain|more evidence|further (?:study|studies|research))\b",
    re.IGNORECASE,
)
STRONG_RESULT_RE = re.compile(
    r"(?:\bp\s*[<=>]\s*0\.\d+\b|\bstatistically significant\b)",
    re.IGNORECASE,
)


def read_paper(row: Mapping[str, str]) -> PaperMetadata:
    return PaperMetadata(
        pmid=row["pmid"],
        doi=row.get("doi", ""),
        title=row.get("title", ""),
        journal=row.get("journal", ""),
        publication_date=row.get("publication_date", ""),
        publication_types=tuple(
            value for value in row.get("publication_types", "").split("; ") if value
        ),
        authors=tuple(value for value in row.get("authors", "").split("; ") if value),
        abstract=row.get("abstract", ""),
    )


def classify_outcome(
    outcome: Mapping[str, str],
    assessment: PaperAssessment,
) -> ClaimDecision | None:
    relation = outcome["ingredient_outcome_relation"]
    direction = outcome["direction"]
    mapped_effects = [value for value in outcome["mapped_effect_ids"].split("|") if value]

    if (
        outcome["mapping_status"] == "mapped_existing_effect"
        and mapped_effects
        and relation in {"direct", "review_summary"}
        and assessment.evidence_tier <= 4
        and assessment.applicability == "human_topical"
    ):
        if direction == "positive":
            if (
                UNCERTAIN_EFFECT_RE.search(outcome.get("evidence_span", ""))
                and not STRONG_RESULT_RE.search(assessment.paper.abstract)
            ):
                return ClaimDecision(
                    "uncertain_effect_review",
                    "no_score_until_effect_is_confirmed",
                )
            return ClaimDecision(
                "benefit_score_candidate",
                "benefit_score_only_after_full_text_approval",
            )
        if direction in {"negative", "null"}:
            return ClaimDecision(
                "conflict_or_zero_candidate",
                "zero_or_conflict_only_after_full_text_approval",
            )
        return None

    if (
        outcome["mapping_status"] == "mechanism_only"
        and mapped_effects
        and relation in {"direct", "mechanism_context"}
        and assessment.evidence_tier in {5, 6, 7}
        and assessment.applicability == "mechanistic"
        and direction == "positive"
    ):
        return ClaimDecision(
            "mechanism_support_candidate",
            "supporting_only_not_standalone_benefit_score",
        )

    if (
        outcome["mapping_status"] == "new_effect_candidate"
        and outcome["new_effect_candidate"]
        and relation in {"direct", "review_summary"}
        and direction == "positive"
    ):
        return ClaimDecision(
            "new_effect_axis_candidate",
            "no_score_until_effect_axis_is_approved",
        )
    return None


def is_clear_risk_penalty_candidate(
    paper: PaperMetadata,
    assessment: PaperAssessment,
) -> bool:
    """Return true only for clear human-topical adverse evidence in the title."""

    return (
        assessment.evidence_tier <= 4
        and assessment.applicability == "human_topical"
        and bool(CLEAR_ADVERSE_TITLE_RE.search(paper.title))
    )


def _claim_row(
    *,
    cohort: str,
    ingredient: Mapping[str, str],
    paper: PaperMetadata,
    assessment: PaperAssessment,
    decision: ClaimDecision,
    effect_id: str = "",
    new_effect_candidate: str = "",
    direction: str = "unclear",
    evidence_span: str = "",
) -> dict[str, object]:
    return {
        "cohort": cohort,
        "ingredient_id": ingredient["ingredient_id"],
        "name_ko": ingredient.get("name_ko", ""),
        "name_en": ingredient.get("name_en", ""),
        "product_count": ingredient.get("product_count", "0"),
        "paper_key": f"PMID:{paper.pmid}",
        "pmid": paper.pmid,
        "doi": paper.doi,
        "title": paper.title,
        "evidence_tier": assessment.evidence_tier,
        "relation_scope": assessment.relation_scope,
        "applicability": assessment.applicability,
        "claim_category": decision.category,
        "effect_id": effect_id,
        "new_effect_candidate": new_effect_candidate,
        "direction": direction,
        "evidence_span": evidence_span,
        "recommended_score_use": decision.recommended_score_use,
        "review_status": "candidate_unverified",
        "runtime_score_change": "none",
    }


def assess_score_eligibility(
    *,
    target_rows: Sequence[Mapping[str, str]],
    screening_rows: Sequence[Mapping[str, str]],
    representative_rows: Sequence[Mapping[str, str]],
    ingredient_terms: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    target_by_id = {row["ingredient_id"]: row for row in target_rows}
    representative_ids = {row["ingredient_id"] for row in representative_rows}
    representative_counts = Counter(row["ingredient_id"] for row in representative_rows)
    screening_by_id: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in screening_rows:
        screening_by_id[row["ingredient_id"]].append(row)

    claim_rows: list[dict[str, object]] = []
    paper_roles: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for ingredient_id, rows in screening_by_id.items():
        ingredient = target_by_id[ingredient_id]
        cohort = "representative_180" if ingredient_id in representative_ids else "raw_hit_190"
        terms = ingredient_terms[ingredient_id]
        for row in rows:
            paper = read_paper(row)
            assessment = assess_paper_candidate(paper, terms)
            outcomes = extract_outcomes(paper, assessment, terms)
            roles = _paper_evidence_roles(paper, assessment, outcomes, terms)
            for role in roles:
                paper_roles[ingredient_id][role].add(paper.pmid)

            for outcome in outcomes:
                decision = classify_outcome(outcome, assessment)
                if decision is None:
                    continue
                effect_ids = [
                    value for value in outcome["mapped_effect_ids"].split("|") if value
                ] or [""]
                for effect_id in effect_ids:
                    claim_rows.append(
                        _claim_row(
                            cohort=cohort,
                            ingredient=ingredient,
                            paper=paper,
                            assessment=assessment,
                            decision=decision,
                            effect_id=effect_id,
                            new_effect_candidate=outcome["new_effect_candidate"],
                            direction=outcome["direction"],
                            evidence_span=outcome["evidence_span"],
                        )
                    )

            if "safety_evidence" in roles:
                claim_rows.append(
                    _claim_row(
                        cohort=cohort,
                        ingredient=ingredient,
                        paper=paper,
                        assessment=assessment,
                        decision=ClaimDecision(
                            "safety_signal_review",
                            "safety_context_only_until_full_text_review",
                        ),
                        evidence_span=paper.title,
                    )
                )
                if is_clear_risk_penalty_candidate(paper, assessment):
                    claim_rows.append(
                        _claim_row(
                            cohort=cohort,
                            ingredient=ingredient,
                            paper=paper,
                            assessment=assessment,
                            decision=ClaimDecision(
                                "risk_penalty_candidate",
                                "risk_only_after_full_text_approval",
                            ),
                            direction="negative",
                            evidence_span=paper.title,
                        )
                    )

    deduped: dict[tuple[str, ...], dict[str, object]] = {}
    for row in claim_rows:
        key = (
            str(row["ingredient_id"]),
            str(row["pmid"]),
            str(row["claim_category"]),
            str(row["effect_id"]),
            str(row["new_effect_candidate"]),
            str(row["evidence_span"]),
        )
        deduped[key] = row
    claim_rows = sorted(
        deduped.values(),
        key=lambda row: (
            int(target_by_id[str(row["ingredient_id"])]["ingredient_rank"]),
            str(row["claim_category"]),
            int(row["pmid"]),
            str(row["effect_id"]),
        ),
    )

    claims_by_ingredient: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in claim_rows:
        claims_by_ingredient[str(row["ingredient_id"])].append(row)

    ingredient_rows: list[dict[str, object]] = []
    decision_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for target in target_rows:
        if int(target["raw_pubmed_hit_count"]) == 0:
            continue
        ingredient_id = target["ingredient_id"]
        cohort = "representative_180" if ingredient_id in representative_ids else "raw_hit_190"
        claims = claims_by_ingredient.get(ingredient_id, [])
        categories = Counter(str(row["claim_category"]) for row in claims)
        effect_ids = sorted(
            {
                str(row["effect_id"])
                for row in claims
                if row["claim_category"] == "benefit_score_candidate" and row["effect_id"]
            }
        )
        new_effects = sorted(
            {
                str(row["new_effect_candidate"])
                for row in claims
                if row["claim_category"] == "new_effect_axis_candidate"
                and row["new_effect_candidate"]
            }
        )
        benefit_rows = [
            row for row in claims if row["claim_category"] == "benefit_score_candidate"
        ]
        if benefit_rows:
            decision = "full_text_benefit_score_review"
            runtime_use = "possible_after_full_text_and_human_approval"
        elif categories["conflict_or_zero_candidate"]:
            decision = "full_text_conflict_or_zero_review"
            runtime_use = "zero_or_conflict_only_after_approval"
        elif categories["uncertain_effect_review"]:
            decision = "uncertain_effect_review_only"
            runtime_use = "no_score_until_effect_is_confirmed"
        elif categories["risk_penalty_candidate"]:
            decision = "full_text_risk_penalty_review"
            runtime_use = "risk_only_after_full_text_and_human_approval"
        elif categories["mechanism_support_candidate"]:
            decision = "mechanism_support_only"
            runtime_use = "supporting_only_not_standalone_benefit_score"
        elif categories["new_effect_axis_candidate"]:
            decision = "new_effect_axis_review"
            runtime_use = "no_score_until_effect_axis_is_approved"
        elif categories["safety_signal_review"]:
            decision = "safety_signal_review_only"
            runtime_use = "no_score_until_adverse_direction_is_confirmed"
        elif paper_roles[ingredient_id]["formulation_evidence"]:
            decision = "formulation_only_no_ingredient_score"
            runtime_use = "no_single_ingredient_benefit_score"
        elif paper_roles[ingredient_id]["reference_evidence"]:
            decision = "reference_only_no_score"
            runtime_use = "no_benefit_score"
        else:
            decision = "not_scoreable_from_current_hits"
            runtime_use = "no_score"
        decision_counts[cohort][decision] += 1
        candidate_pmids = sorted(
            {str(row["pmid"]) for row in claims},
            key=int,
        )
        ingredient_rows.append(
            {
                "cohort": cohort,
                "ingredient_id": ingredient_id,
                "name_ko": target.get("name_ko", ""),
                "name_en": target.get("name_en", ""),
                "product_count": target.get("product_count", "0"),
                "raw_pubmed_hit_count": target["raw_pubmed_hit_count"],
                "representative_paper_count": representative_counts[ingredient_id],
                "benefit_candidate_count": categories["benefit_score_candidate"],
                "uncertain_effect_count": categories["uncertain_effect_review"],
                "conflict_or_zero_candidate_count": categories[
                    "conflict_or_zero_candidate"
                ],
                "mechanism_support_count": categories["mechanism_support_candidate"],
                "risk_candidate_count": categories["risk_penalty_candidate"],
                "safety_signal_count": categories["safety_signal_review"],
                "new_effect_candidate_count": categories["new_effect_axis_candidate"],
                "formulation_paper_count": len(
                    paper_roles[ingredient_id]["formulation_evidence"]
                ),
                "reference_paper_count": len(
                    paper_roles[ingredient_id]["reference_evidence"]
                ),
                "best_benefit_tier": min(
                    (int(row["evidence_tier"]) for row in benefit_rows),
                    default="",
                ),
                "candidate_effect_ids": "|".join(effect_ids),
                "candidate_new_effects": "|".join(new_effects),
                "candidate_pmids": "|".join(candidate_pmids),
                "score_eligibility_decision": decision,
                "recommended_runtime_use": runtime_use,
                "can_change_benefit_score_now": "N",
                "review_status": "candidate_unverified",
                "runtime_score_change": "none",
            }
        )

    summary = {
        "generated_on": date.today().isoformat(),
        "policy_version": POLICY_VERSION,
        "raw_hit_ingredient_count": len(ingredient_rows),
        "claim_candidate_row_count": len(claim_rows),
        "cohorts": {
            cohort: {
                "ingredient_count": sum(row["cohort"] == cohort for row in ingredient_rows),
                "decision_counts": dict(sorted(counts.items())),
            }
            for cohort, counts in sorted(decision_counts.items())
        },
        "runtime_changed": False,
        "notes": [
            "All rows remain candidate_unverified.",
            "Benefit candidates still require full-text review and human approval.",
            "A general safety signal is not a positive efficacy or risk score.",
            "A safety mention becomes a risk candidate only for a clear human-topical adverse title.",
            "Formulation and reference evidence do not create a single-ingredient benefit score.",
        ],
    }
    return ingredient_rows, claim_rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_500.csv"),
    )
    parser.add_argument(
        "--screening",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_screening_all_500.csv"),
    )
    parser.add_argument(
        "--representatives",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_candidates_500.csv"),
    )
    parser.add_argument(
        "--ingredient-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_score_eligibility_370.csv"),
    )
    parser.add_argument(
        "--claim-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_score_claim_candidates.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_score_eligibility_summary.json"),
    )
    args = parser.parse_args()

    targets = read_csv(args.targets)
    ingredient_ids = {row["ingredient_id"] for row in targets}
    terms = load_ingredient_terms(
        read_csv(args.data_dir / "ingredients.csv"),
        read_csv(args.data_dir / "ingredient_aliases.csv"),
        ingredient_ids,
    )
    ingredient_rows, claim_rows, summary = assess_score_eligibility(
        target_rows=targets,
        screening_rows=read_csv(args.screening),
        representative_rows=read_csv(args.representatives),
        ingredient_terms=terms,
    )
    write_csv(args.ingredient_output, INGREDIENT_FIELDS, ingredient_rows)
    write_csv(args.claim_output, CLAIM_FIELDS, claim_rows)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Score eligibility review complete: "
        f"ingredients={len(ingredient_rows)} claims={len(claim_rows)}"
    )


if __name__ == "__main__":
    main()
