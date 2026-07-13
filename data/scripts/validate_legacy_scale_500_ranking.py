#!/usr/bin/env python3
"""Validate the 34-pair baseline to 187-ingredient runtime scoring transition."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from build_ingredient_role_inventory import (
    HIGH_EFFECT_FUNCTIONS,
    MEDIUM_EFFECT_FUNCTIONS,
    apply_mapping,
    load_mappings,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DECAYS = (1.0, 0.5, 0.25)
EFFECT_CAP = 1.2
FINAL_CLAMP = 1.0
EFFECT_WEIGHT_POINTS = 26
EVIDENCE_WEIGHT_POINTS = 18
EFFECT_NAMES = {
    "effect_brightening": "미백·톤",
    "effect_moisture_barrier": "보습·장벽",
    "effect_acne_sebum": "여드름·피지",
    "effect_wrinkle": "주름·탄력",
    "effect_calming": "진정",
    "effect_exfoliation": "각질",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validated-on", default=date.today().isoformat())
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pair_scores(rows: list[dict[str, str]], score_field: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        score = float(row[score_field])
        if score_field == "evidence_score":
            authority = float(row["source_authority_score"] or 1.0)
            score *= max(0.0, min(1.0, authority))
        result[row["ingredient_id"]][row["effect_id"]] = score
    return dict(result)


def top3_score(
    ingredient_orders: dict[str, int],
    ranking_scores: dict[str, dict[str, float]],
    component_scores: dict[str, dict[str, float]],
    effect_id: str,
) -> float:
    ranked = sorted(
        (
            (scores[effect_id], ingredient_orders[ingredient_id], ingredient_id)
            for ingredient_id, scores in ranking_scores.items()
            if ingredient_id in ingredient_orders and effect_id in scores
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    raw = sum(
        component_scores.get(ingredient_id, {}).get(effect_id, 0.0) / 100 * decay
        for (_, _, ingredient_id), decay in zip(ranked, DECAYS, strict=False)
    )
    return round(max(0.0, min(FINAL_CLAMP, min(raw, EFFECT_CAP))), 12)


def percentage(count: int, total: int) -> float:
    return round(count / total * 100, 4) if total else 0.0


def top_overlap(before: dict[str, float], after: dict[str, float], size: int = 100) -> int:
    before_ids = sorted(before, key=lambda product_id: (-before[product_id], product_id))[:size]
    after_ids = sorted(after, key=lambda product_id: (-after[product_id], product_id))[:size]
    return len(set(before_ids) & set(after_ids))


def compare(before: dict[str, float], after: dict[str, float]) -> dict[str, float | int]:
    deltas = {
        product_id: round(after[product_id] - before[product_id], 12)
        for product_id in before
    }
    changed = sum(delta != 0 for delta in deltas.values())
    return {
        "changed_count": changed,
        "changed_pct": percentage(changed, len(deltas)),
        "improved_count": sum(delta > 0 for delta in deltas.values()),
        "worsened_count": sum(delta < 0 for delta in deltas.values()),
        "minimum_delta": min(deltas.values(), default=0.0),
        "maximum_delta": max(deltas.values(), default=0.0),
    }


def load_product_orders(
    active_ingredient_ids: set[str],
) -> tuple[list[str], dict[str, dict[str, int]]]:
    recommendable_ids: set[str] = set()
    for path in sorted((DATA_DIR / "products").glob("products_*.csv")):
        for row in read_csv(path):
            if row["is_recommendable"].strip().casefold() == "true":
                recommendable_ids.add(row["product_id"])

    price_ids = {row["product_id"] for row in read_csv(DATA_DIR / "product_prices.csv")}
    runtime_ids = sorted(recommendable_ids & price_ids)

    exact_mapping, wildcard_mapping = load_mappings(
        DATA_DIR / "ingredient_canonical_mappings.csv"
    )
    orders: dict[str, dict[str, int]] = defaultdict(dict)
    runtime_id_set = set(runtime_ids)
    for path in sorted((DATA_DIR / "product_ingredients").glob("product_ingredients_*.csv")):
        for row in read_csv(path):
            product_id = row["product_id"]
            if product_id not in runtime_id_set:
                continue
            ingredient_id = apply_mapping(
                row["ingredient_id"],
                row.get("ingredient_name", ""),
                exact_mapping,
                wildcard_mapping,
            )
            if ingredient_id not in active_ingredient_ids:
                continue
            display_order = int(row["display_order"] or 999)
            existing = orders[product_id].get(ingredient_id)
            if existing is None or display_order < existing:
                orders[product_id][ingredient_id] = display_order

    return runtime_ids, dict(orders)


def official_axis_leakage(audit_rows: list[dict[str, str]]) -> int:
    allowed = {
        effect_id: set(functions) | set(MEDIUM_EFFECT_FUNCTIONS.get(effect_id, set()))
        for effect_id, functions in HIGH_EFFECT_FUNCTIONS.items()
    }
    violations = 0
    for row in audit_rows:
        if "official_function_prior" not in row["score_origin"]:
            continue
        functions = {
            value
            for value in re.split(r"[|+]", row["official_signal_functions"])
            if value
        }
        if not functions or not functions <= allowed.get(row["effect_id"], set()):
            violations += 1
    return violations


def build_summary(validated_on: str) -> dict[str, object]:
    legacy_dir = DATA_DIR / "reconciliation/legacy_scale_500"
    baseline_effect_path = legacy_dir / "baseline_ingredient_effect_34.csv"
    baseline_evidence_path = legacy_dir / "baseline_ingredient_evidence_34.csv"
    runtime_effect_path = DATA_DIR / "ingredient_effect.csv"
    runtime_evidence_path = DATA_DIR / "ingredient_evidence.csv"
    reconciled_effect_path = legacy_dir / "ingredient_effect_500_legacy_scale.csv"
    audit_path = legacy_dir / "ingredient_effect_500_legacy_scale_audit.csv"
    cohort_path = DATA_DIR / "reconciliation/ingredient_evidence_adjudication_466.csv"
    ingredient_path = DATA_DIR / "ingredients.csv"

    baseline_effect_rows = read_csv(baseline_effect_path)
    baseline_evidence_rows = read_csv(baseline_evidence_path)
    runtime_effect_rows = read_csv(runtime_effect_path)
    runtime_evidence_rows = read_csv(runtime_evidence_path)
    reconciled_effect_rows = read_csv(reconciled_effect_path)
    audit_rows = read_csv(audit_path)
    cohort_rows = read_csv(cohort_path)
    ingredient_rows = read_csv(ingredient_path)

    baseline_effect = pair_scores(baseline_effect_rows, "effect_score")
    baseline_evidence = pair_scores(baseline_evidence_rows, "evidence_score")
    runtime_effect = pair_scores(runtime_effect_rows, "effect_score")
    runtime_evidence = pair_scores(runtime_evidence_rows, "evidence_score")
    runtime_ids, orders_by_product = load_product_orders(set(runtime_effect))

    axis_rows: list[dict[str, object]] = []
    for effect_id, effect_name in EFFECT_NAMES.items():
        baseline_effect_values: dict[str, float] = {}
        runtime_effect_values: dict[str, float] = {}
        baseline_evidence_values: dict[str, float] = {}
        runtime_evidence_values: dict[str, float] = {}
        baseline_combined: dict[str, float] = {}
        runtime_combined: dict[str, float] = {}

        for product_id in runtime_ids:
            orders = orders_by_product.get(product_id, {})
            baseline_effect_value = top3_score(
                orders, baseline_effect, baseline_effect, effect_id
            )
            runtime_effect_value = top3_score(
                orders, runtime_effect, runtime_effect, effect_id
            )
            # The deployed baseline ranks evidence with effect_score. The new runtime
            # ranks evidence independently with authority-adjusted evidence_score.
            baseline_evidence_value = top3_score(
                orders, baseline_effect, baseline_evidence, effect_id
            )
            runtime_evidence_value = top3_score(
                orders, runtime_evidence, runtime_evidence, effect_id
            )

            baseline_effect_values[product_id] = baseline_effect_value
            runtime_effect_values[product_id] = runtime_effect_value
            baseline_evidence_values[product_id] = baseline_evidence_value
            runtime_evidence_values[product_id] = runtime_evidence_value
            baseline_combined[product_id] = round(
                baseline_effect_value * EFFECT_WEIGHT_POINTS
                + baseline_evidence_value * EVIDENCE_WEIGHT_POINTS,
                12,
            )
            runtime_combined[product_id] = round(
                runtime_effect_value * EFFECT_WEIGHT_POINTS
                + runtime_evidence_value * EVIDENCE_WEIGHT_POINTS,
                12,
            )

        effect_comparison = compare(baseline_effect_values, runtime_effect_values)
        evidence_comparison = compare(baseline_evidence_values, runtime_evidence_values)
        combined_comparison = compare(baseline_combined, runtime_combined)
        axis_rows.append(
            {
                "effect_id": effect_id,
                "effect_name": effect_name,
                "baseline_reach_pct": percentage(
                    sum(value > 0 for value in baseline_effect_values.values()),
                    len(runtime_ids),
                ),
                "expanded_reach_pct": percentage(
                    sum(value > 0 for value in runtime_effect_values.values()),
                    len(runtime_ids),
                ),
                "baseline_saturation_pct": percentage(
                    sum(value == 1.0 for value in baseline_effect_values.values()),
                    len(runtime_ids),
                ),
                "expanded_saturation_pct": percentage(
                    sum(value == 1.0 for value in runtime_effect_values.values()),
                    len(runtime_ids),
                ),
                "effect_comparison": effect_comparison,
                "evidence_comparison": evidence_comparison,
                "combined_comparison": combined_comparison,
                "top_100_effect_overlap_count": top_overlap(
                    baseline_effect_values, runtime_effect_values
                ),
            }
        )

    baseline_ids = set(baseline_effect)
    runtime_active_ids = set(runtime_effect)
    cohort_ids = {row["ingredient_id"] for row in cohort_rows}
    ingredient_ids = {row["ingredient_id"] for row in ingredient_rows}
    baseline_pairs = {
        (row["ingredient_id"], row["effect_id"]) for row in baseline_effect_rows
    }
    runtime_pairs = {
        (row["ingredient_id"], row["effect_id"]) for row in runtime_effect_rows
    }
    invariants = {
        "baseline_ingredient_count": len(baseline_ids),
        "baseline_pair_count": len(baseline_effect_rows),
        "baseline_rows_exactly_preserved": (
            runtime_effect_rows[: len(baseline_effect_rows)] == baseline_effect_rows
        ),
        "fixed_cohort_count": len(baseline_ids | cohort_ids),
        "expanded_active_ingredient_count": len(runtime_active_ids),
        "expanded_pair_count": len(runtime_effect_rows),
        "new_active_ingredient_count": len(runtime_active_ids - baseline_ids),
        "new_pair_count": len(runtime_pairs - baseline_pairs),
        "expanded_evidence_row_count": len(runtime_evidence_rows),
        "effect_score_min": min(int(row["effect_score"]) for row in runtime_effect_rows),
        "effect_score_max": max(int(row["effect_score"]) for row in runtime_effect_rows),
        "unknown_effect_id_count": sum(
            row["effect_id"] not in EFFECT_NAMES for row in runtime_effect_rows
        ),
        "missing_ingredient_id_count": len(runtime_active_ids - ingredient_ids),
        "official_prior_cross_axis_leakage_count": official_axis_leakage(audit_rows),
        "deterministic_rebuild_matches_runtime": (
            runtime_effect_rows == reconciled_effect_rows
        ),
    }

    errors: list[str] = []
    expected_invariants = {
        "baseline_ingredient_count": 34,
        "baseline_pair_count": 72,
        "baseline_rows_exactly_preserved": True,
        "fixed_cohort_count": 500,
        "expanded_active_ingredient_count": 187,
        "expanded_pair_count": 245,
        "new_active_ingredient_count": 153,
        "new_pair_count": 173,
        "expanded_evidence_row_count": 107,
        "unknown_effect_id_count": 0,
        "missing_ingredient_id_count": 0,
        "official_prior_cross_axis_leakage_count": 0,
        "deterministic_rebuild_matches_runtime": True,
    }
    for key, expected in expected_invariants.items():
        if invariants[key] != expected:
            errors.append(f"{key}: expected {expected!r}, got {invariants[key]!r}")
    if len(runtime_ids) != 10_164:
        errors.append(f"runtime product count: expected 10164, got {len(runtime_ids)}")
    for row in axis_rows:
        for comparison_name in (
            "effect_comparison",
            "evidence_comparison",
            "combined_comparison",
        ):
            comparison = row[comparison_name]
            if comparison["worsened_count"] != 0:
                errors.append(
                    f"{row['effect_id']} {comparison_name} worsened: "
                    f"{comparison['worsened_count']}"
                )
            if comparison["minimum_delta"] < 0:
                errors.append(
                    f"{row['effect_id']} {comparison_name} minimum delta: "
                    f"{comparison['minimum_delta']}"
                )
    if errors:
        raise ValueError("ranking validation failed\n" + "\n".join(errors))

    summary: dict[str, object] = {
        "validation_version": "mwbl-legacy-scale-500-ranking-audit-v2",
        "validated_on": validated_on,
        "status": "pass",
        "transition": (
            "34 ingredients/72 pairs with coupled evidence top3 -> "
            "187 ingredients/245 pairs with independent evidence top3"
        ),
        "selection_policy": {
            "ingredient_effect": "top3 effect_score",
            "ingredient_evidence": "independent top3 authority-adjusted evidence_score",
            "decays": list(DECAYS),
            "effect_cap": EFFECT_CAP,
            "final_clamp": FINAL_CLAMP,
            "score_evidence_explanation": (
                "effect top3; unchanged by the numeric evidence top3 selection"
            ),
        },
        "input_sha256": {
            "baseline_effect": sha256_file(baseline_effect_path),
            "baseline_evidence": sha256_file(baseline_evidence_path),
            "runtime_effect": sha256_file(runtime_effect_path),
            "runtime_evidence": sha256_file(runtime_evidence_path),
            "canonical_mapping": sha256_file(
                DATA_DIR / "ingredient_canonical_mappings.csv"
            ),
            "frozen_466_cohort": sha256_file(cohort_path),
        },
        "populations": {"runtime_recommendable_with_price": len(runtime_ids)},
        "data_invariants": invariants,
        "runtime_recommendable_effect_axis_summary": axis_rows,
        "resolved_issue": {
            "code": "effect_ranked_top3_reused_for_evidence",
            "resolution": (
                "Evidence top3 is selected independently by authority-adjusted "
                "evidence score."
            ),
            "remaining_separate_issue": (
                "moisture top3 clamp saturation is tracked separately and is not "
                "changed here."
            ),
        },
    }
    payload = json.dumps(
        summary,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    summary["validation_payload_sha256"] = hashlib.sha256(payload).hexdigest()
    return summary


def main() -> None:
    args = parse_args()
    summary = build_summary(args.validated_on)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(summary["validation_payload_sha256"])


if __name__ == "__main__":
    main()
