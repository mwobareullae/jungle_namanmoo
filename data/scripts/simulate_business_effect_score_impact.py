#!/usr/bin/env python3
"""Simulate ingredient-effect component changes without modifying runtime seeds."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from build_ingredient_role_inventory import apply_mapping, load_mappings
from reconcile_a_group_product_ingredients import resolve_csv_paths

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "apps/backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scoring_policy import (  # noqa: E402
    DEFAULT_INGREDIENT_EFFECT_WEIGHT,
    EFFECT_CAP,
    TOP_INGREDIENT_DECAYS,
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def effect_component(scores: list[float]) -> float:
    ranked = sorted(scores, reverse=True)[: len(TOP_INGREDIENT_DECAYS)]
    return min(
        sum(
            score / 100 * decay
            for score, decay in zip(ranked, TOP_INGREDIENT_DECAYS, strict=False)
        ),
        EFFECT_CAP,
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(math.ceil(len(ordered) * fraction) - 1, len(ordered) - 1)
    return ordered[max(index, 0)]


def _scenario_summary(
    *,
    current_scores: dict[tuple[str, str], float],
    scenario_scores: dict[tuple[str, str], float],
    product_scores: dict[str, dict[str, dict[str, float]]],
    total_products: int,
) -> dict[str, object]:
    deltas_by_effect: dict[str, list[float]] = defaultdict(list)
    changed_products: set[str] = set()
    top_impacts: list[dict[str, object]] = []
    for product_id, effects in product_scores.items():
        max_point_delta = 0.0
        changed_effects: list[str] = []
        for effect_id, ingredient_scores in effects.items():
            scenario_values = [
                score
                for ingredient_id, score in ingredient_scores.items()
                if (ingredient_id, effect_id) in scenario_scores
            ]
            after = effect_component(scenario_values)
            before_values = [
                current_scores[(ingredient_id, effect_id)]
                for ingredient_id in ingredient_scores
                if (ingredient_id, effect_id) in current_scores
            ]
            before = effect_component(before_values)
            delta = max(after - before, 0.0)
            if delta <= 0:
                continue
            deltas_by_effect[effect_id].append(delta)
            changed_products.add(product_id)
            changed_effects.append(effect_id)
            max_point_delta = max(
                max_point_delta,
                delta * DEFAULT_INGREDIENT_EFFECT_WEIGHT * 100,
            )
        if changed_effects:
            top_impacts.append(
                {
                    "product_id": product_id,
                    "changed_effect_ids": sorted(changed_effects),
                    "max_single_effect_total_point_delta": round(max_point_delta, 4),
                }
            )

    effect_summary = {}
    for effect_id, values in sorted(deltas_by_effect.items()):
        point_values = [value * DEFAULT_INGREDIENT_EFFECT_WEIGHT * 100 for value in values]
        effect_summary[effect_id] = {
            "changed_products": len(values),
            "median_total_point_delta": round(percentile(point_values, 0.5), 4),
            "p95_total_point_delta": round(percentile(point_values, 0.95), 4),
            "max_total_point_delta": round(max(point_values), 4),
        }
    top_impacts.sort(
        key=lambda row: (-float(row["max_single_effect_total_point_delta"]), str(row["product_id"]))
    )
    return {
        "total_products": total_products,
        "changed_products": len(changed_products),
        "changed_product_pct": round(len(changed_products) / max(total_products, 1) * 100, 4),
        "current_pair_count": len(current_scores),
        "proposed_pair_count": len(scenario_scores),
        "new_provisional_pair_count": len(scenario_scores) - len(current_scores),
        "effect_summary": effect_summary,
        "top_impacts": top_impacts[:100],
    }


def simulate(
    *,
    product_ingredients_path: Path,
    mappings_path: Path,
    current_effect_rows: list[dict[str, str]],
    proposal_rows: list[dict[str, str]],
) -> dict[str, object]:
    current_scores = {
        (row["ingredient_id"], row["effect_id"]): float(row["effect_score"])
        for row in current_effect_rows
    }
    counterfactual_scores = dict(current_scores)
    for row in proposal_rows:
        if row.get("counterfactual_score_eligible_after_review") != "Y":
            continue
        counterfactual_scores[(row["ingredient_id"], row["effect_id"])] = float(
            row["proposed_effect_score"]
        )

    relevant_ids = {ingredient_id for ingredient_id, _ in counterfactual_scores}
    scores_by_ingredient: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (ingredient_id, effect_id), score in counterfactual_scores.items():
        scores_by_ingredient[ingredient_id].append((effect_id, score))

    exact_mapping, wildcard_mapping = load_mappings(mappings_path)
    product_scores: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    product_ids: set[str] = set()
    for path in resolve_csv_paths(product_ingredients_path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = row["product_id"]
                product_ids.add(product_id)
                ingredient_id = apply_mapping(
                    row["ingredient_id"],
                    row.get("ingredient_name", ""),
                    exact_mapping,
                    wildcard_mapping,
                )
                if ingredient_id not in relevant_ids:
                    continue
                for effect_id, score in scores_by_ingredient[ingredient_id]:
                    prior = product_scores[product_id][effect_id].get(ingredient_id, 0.0)
                    product_scores[product_id][effect_id][ingredient_id] = max(prior, score)

    guarded = _scenario_summary(
        current_scores=current_scores,
        scenario_scores=current_scores,
        product_scores=product_scores,
        total_products=len(product_ids),
    )
    counterfactual = _scenario_summary(
        current_scores=current_scores,
        scenario_scores=counterfactual_scores,
        product_scores=product_scores,
        total_products=len(product_ids),
    )
    return {
        "simulation_only": True,
        "runtime_files_changed": False,
        "approval_gate": "candidate_unverified rows contribute zero until accepted",
        "scoring_policy": {
            "effect_cap": EFFECT_CAP,
            "top_ingredient_decays": list(TOP_INGREDIENT_DECAYS),
            "ingredient_effect_weight": DEFAULT_INGREDIENT_EFFECT_WEIGHT,
        },
        "runtime_guarded": guarded,
        "counterfactual_if_all_review_candidates_accepted": counterfactual,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product-ingredients", type=Path, default=Path("data/product_ingredients.csv")
    )
    parser.add_argument(
        "--mappings", type=Path, default=Path("data/ingredient_canonical_mappings.csv")
    )
    parser.add_argument(
        "--current-effects", type=Path, default=Path("data/ingredient_effect.csv")
    )
    parser.add_argument(
        "--proposal",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_business_score_proposal_500.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_effect_business_score_impact_500.json"),
    )
    args = parser.parse_args()
    result = simulate(
        product_ingredients_path=args.product_ingredients,
        mappings_path=args.mappings,
        current_effect_rows=read_csv(args.current_effects),
        proposal_rows=read_csv(args.proposal),
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "Business effect score simulation: "
        f"runtime_changed={result['runtime_guarded']['changed_products']} "
        f"counterfactual_changed="
        f"{result['counterfactual_if_all_review_candidates_accepted']['changed_products']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
