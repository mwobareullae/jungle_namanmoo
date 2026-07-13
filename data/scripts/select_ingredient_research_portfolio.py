#!/usr/bin/env python3
"""Rank canonical ingredients for a target-sized research review portfolio."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


PORTFOLIO_FIELDS = [
    "portfolio_rank",
    "selected_for_portfolio",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "current_runtime",
    "effect_ids",
    "best_evidence_tier",
    "best_signal_score",
    "best_relation_scope",
    "best_applicability",
    "best_pmid",
    "best_title",
    "evidence_component",
    "product_component",
    "function_component",
    "portfolio_score",
    "selection_reason",
    "review_status",
    "score_change",
]

PAIR_FIELDS = [
    "portfolio_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "effect_id",
    "effect_name",
    "product_count",
    "selection_policy",
    "signal_strength",
    "signal_functions",
    "best_evidence_tier",
    "best_signal_score",
    "best_relation_scope",
    "best_applicability",
    "best_pmid",
    "best_title",
    "screening_status",
    "review_status",
    "score_change",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(encoding="utf-8", newline="", mode="w") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _best_screening_row(rows: list[dict[str, str]]) -> dict[str, str] | None:
    paper_rows = [row for row in rows if row.get("best_pmid")]
    if not paper_rows:
        return None
    return max(
        paper_rows,
        key=lambda row: (
            int(row.get("best_signal_score") or 0),
            -int(row.get("best_evidence_tier") or 99),
            row.get("best_relation_scope") == "title_exact",
            row.get("best_pmid", ""),
        ),
    )


def build_portfolio(
    role_rows: list[dict[str, str]],
    screening_rows: list[dict[str, str]],
    *,
    target_count: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    screening_by_ingredient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in screening_rows:
        screening_by_ingredient[row["ingredient_id"]].append(row)

    candidates = [row for row in role_rows if row.get("role_effect_candidate") == "Y"]
    if len(candidates) < target_count:
        raise ValueError(f"portfolio candidates are insufficient: {len(candidates)} < {target_count}")
    max_product_count = max(int(row.get("product_count") or 0) for row in candidates)
    ranked: list[dict[str, object]] = []

    for role in candidates:
        ingredient_id = role["ingredient_id"]
        pair_rows = screening_by_ingredient.get(ingredient_id, [])
        best = _best_screening_row(pair_rows)
        best_signal = int(best.get("best_signal_score") or 0) if best else 0
        product_count = int(role.get("product_count") or 0)
        strengths = {row.get("signal_strength", "") for row in pair_rows}
        if "high" in strengths or role.get("current_effect_ids"):
            function_component = 20.0
        elif "medium" in strengths:
            function_component = 10.0
        else:
            function_component = 0.0
        evidence_component = best_signal / 100 * 50
        product_component = (
            math.log1p(product_count) / math.log1p(max_product_count) * 30
            if max_product_count
            else 0.0
        )
        current_runtime = bool(role.get("current_effect_ids"))
        score = evidence_component + product_component + function_component
        ranked.append(
            {
                "portfolio_rank": 0,
                "selected_for_portfolio": "N",
                "ingredient_id": ingredient_id,
                "name_ko": role.get("name_ko", ""),
                "name_en": role.get("name_en", ""),
                "product_count": product_count,
                "current_runtime": "Y" if current_runtime else "N",
                "effect_ids": "|".join(sorted({row["effect_id"] for row in pair_rows})),
                "best_evidence_tier": best.get("best_evidence_tier", "") if best else "",
                "best_signal_score": best_signal,
                "best_relation_scope": best.get("best_relation_scope", "") if best else "",
                "best_applicability": best.get("best_applicability", "") if best else "",
                "best_pmid": best.get("best_pmid", "") if best else "",
                "best_title": best.get("best_title", "") if best else "",
                "evidence_component": f"{evidence_component:.4f}",
                "product_component": f"{product_component:.4f}",
                "function_component": f"{function_component:.4f}",
                "portfolio_score": f"{score:.4f}",
                "selection_reason": "",
                "review_status": "existing_runtime" if current_runtime else "candidate_unverified",
                "score_change": "none",
            }
        )

    ranked.sort(
        key=lambda row: (
            0 if row["current_runtime"] == "Y" else 1,
            -float(row["portfolio_score"]),
            -int(row["product_count"]),
            str(row["ingredient_id"]),
        )
    )
    cutoff_score = float(ranked[target_count - 1]["portfolio_score"])
    for rank, row in enumerate(ranked, start=1):
        # The target is a review-capacity goal, not a scientific cutoff. Keep
        # every score tie at the boundary so ingredient_id sorting cannot decide
        # which scientifically equivalent candidate survives.
        selected = row["current_runtime"] == "Y" or float(row["portfolio_score"]) >= cutoff_score
        row["portfolio_rank"] = rank
        row["selected_for_portfolio"] = "Y" if selected else "N"
        if row["current_runtime"] == "Y":
            row["selection_reason"] = "existing_runtime"
        elif row["best_pmid"]:
            row["selection_reason"] = "paper_signal+product_usage+official_function"
        else:
            row["selection_reason"] = "product_usage+official_function"

    selected_ranks = {
        str(row["ingredient_id"]): int(row["portfolio_rank"])
        for row in ranked
        if row["selected_for_portfolio"] == "Y"
    }
    role_by_id = {row["ingredient_id"]: row for row in role_rows}
    pair_output: list[dict[str, object]] = []
    for row in screening_rows:
        ingredient_id = row["ingredient_id"]
        if ingredient_id not in selected_ranks:
            continue
        role = role_by_id[ingredient_id]
        pair_output.append(
            {
                "portfolio_rank": selected_ranks[ingredient_id],
                "ingredient_id": ingredient_id,
                "name_ko": role.get("name_ko", ""),
                "name_en": role.get("name_en", ""),
                "effect_id": row["effect_id"],
                "effect_name": row["effect_name"],
                "product_count": role.get("product_count", "0"),
                "selection_policy": row.get("selection_policy", ""),
                "signal_strength": row.get("signal_strength", ""),
                "signal_functions": row.get("signal_functions", ""),
                "best_evidence_tier": row.get("best_evidence_tier", ""),
                "best_signal_score": row.get("best_signal_score", "0"),
                "best_relation_scope": row.get("best_relation_scope", ""),
                "best_applicability": row.get("best_applicability", ""),
                "best_pmid": row.get("best_pmid", ""),
                "best_title": row.get("best_title", ""),
                "screening_status": row.get("screening_status", ""),
                "review_status": row.get("review_status", "candidate_unverified"),
                "score_change": "none",
            }
        )
    pair_output.sort(key=lambda row: (int(row["portfolio_rank"]), str(row["effect_id"])))
    return ranked, pair_output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roles",
        type=Path,
        default=Path("data/reconciliation/ingredient_role_review.csv"),
    )
    parser.add_argument(
        "--screening",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_pubmed_screening.csv"),
    )
    parser.add_argument(
        "--portfolio-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_research_portfolio_500.csv"),
    )
    parser.add_argument(
        "--pairs-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_portfolio_500.csv"),
    )
    parser.add_argument("--target-count", type=int, default=500)
    args = parser.parse_args()

    portfolio, pairs = build_portfolio(
        read_csv(args.roles),
        read_csv(args.screening),
        target_count=args.target_count,
    )
    write_csv(args.portfolio_output, PORTFOLIO_FIELDS, portfolio)
    write_csv(args.pairs_output, PAIR_FIELDS, pairs)
    selected_count = sum(row["selected_for_portfolio"] == "Y" for row in portfolio)
    print(
        f"Ingredient research portfolio: target={args.target_count} selected={selected_count}/{len(portfolio)} "
        f"pairs={len(pairs)} output={args.portfolio_output}"
    )


if __name__ == "__main__":
    main()
