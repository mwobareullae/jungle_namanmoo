#!/usr/bin/env python3
"""Build review-gated score counterfactuals for the research portfolio."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


OUTPUT_FIELDS = [
    "portfolio_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "current_runtime",
    "current_effect_score",
    "best_evidence_tier",
    "best_relation_scope",
    "best_applicability",
    "best_pmid",
    "signal_strength",
    "score_basis",
    "proposed_effect_score",
    "scientific_evidence_score",
    "runtime_score_eligible",
    "counterfactual_score_eligible_after_review",
    "score_exclusion_reason",
    "review_status",
    "activation_status",
]

TIER_PROVISIONAL_SCORES = {1: 8.0, 2: 8.0, 3: 8.0, 4: 6.0, 5: 4.0, 6: 4.0, 7: 4.0, 8: 3.0}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def provisional_score(row: dict[str, str]) -> tuple[float, str, str]:
    tier_text = row.get("best_evidence_tier", "").strip()
    applicability = row.get("best_applicability", "")
    if not tier_text:
        return 0.0, "screening_only_cosing_function", "no_exact_pubmed_paper"

    tier = int(tier_text)
    if applicability == "combination_or_formulation":
        return 0.0, f"screening_only_tier_{tier}", "combination_not_separable"
    if applicability == "route_mismatch":
        return 0.0, f"screening_only_tier_{tier}", "route_mismatch"
    if tier == 8 or applicability == "reference_only":
        return 0.0, "screening_only_reference", "reference_only"
    if row.get("effect_id") == "effect_brightening" and not (
        tier <= 3 and applicability == "human_topical"
    ):
        return 0.0, f"screening_only_tier_{tier}", "brightening_human_clinical_required"
    return TIER_PROVISIONAL_SCORES[tier], f"paper_candidate_tier_{tier}", ""


def build_proposal(
    pair_rows: list[dict[str, str]],
    current_effect_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    current = {
        (row["ingredient_id"], row["effect_id"]): row["effect_score"]
        for row in current_effect_rows
    }
    output: list[dict[str, str]] = []
    for row in pair_rows:
        key = (row["ingredient_id"], row["effect_id"])
        current_score = current.get(key, "")
        if current_score:
            score = float(current_score)
            basis = "existing_runtime_unchanged"
            exclusion_reason = ""
            current_runtime = "Y"
            activation = "active_existing"
            review_status = "existing_runtime"
            runtime_score_eligible = "Y"
            counterfactual_eligible = "N"
        else:
            score, basis, exclusion_reason = provisional_score(row)
            current_runtime = "N"
            activation = "candidate_unverified" if score > 0 else "screening_only"
            review_status = "candidate_unverified"
            runtime_score_eligible = "N"
            counterfactual_eligible = "Y" if score > 0 else "N"
        output.append(
            {
                "portfolio_rank": row["portfolio_rank"],
                "ingredient_id": row["ingredient_id"],
                "name_ko": row["name_ko"],
                "name_en": row["name_en"],
                "effect_id": row["effect_id"],
                "effect_name": row["effect_name"],
                "current_runtime": current_runtime,
                "current_effect_score": current_score,
                "best_evidence_tier": row.get("best_evidence_tier", ""),
                "best_relation_scope": row.get("best_relation_scope", ""),
                "best_applicability": row.get("best_applicability", ""),
                "best_pmid": row.get("best_pmid", ""),
                "signal_strength": row.get("signal_strength", ""),
                "score_basis": basis,
                "proposed_effect_score": f"{score:.2f}",
                "scientific_evidence_score": "0.00" if not current_score else "",
                "runtime_score_eligible": runtime_score_eligible,
                "counterfactual_score_eligible_after_review": counterfactual_eligible,
                "score_exclusion_reason": exclusion_reason,
                "review_status": review_status,
                "activation_status": activation,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(encoding="utf-8", newline="", mode="w") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_portfolio_500.csv"),
    )
    parser.add_argument(
        "--current-effects", type=Path, default=Path("data/ingredient_effect.csv")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_business_score_proposal_500.csv"),
    )
    args = parser.parse_args()
    rows = build_proposal(read_csv(args.pairs), read_csv(args.current_effects))
    write_csv(args.output, rows)
    print(
        "Business effect score proposal: "
        f"rows={len(rows)} review_candidates="
        f"{sum(row['counterfactual_score_eligible_after_review'] == 'Y' for row in rows)} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
