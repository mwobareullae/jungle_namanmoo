#!/usr/bin/env python3
"""Select safe canonicalization proposals until a product-row coverage target is met."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


SAFE_ACTIONS = {"create_canonical", "merge_existing"}


@dataclass(frozen=True)
class SelectionStats:
    selected_rows: int
    selected_source_rows: int
    selected_new_canonical: int
    last_selected_rank: int
    projected_coverage_pct: float


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_safe_exact(row: dict[str, str]) -> bool:
    return (
        row.get("official_match_status") == "official_exact"
        and row.get("proposal_confidence") == "high"
        and row.get("proposed_action") in SAFE_ACTIONS
        and bool(row.get("proposed_canonical_id"))
    )


def select_coverage_batch(
    rows: list[dict[str, str]],
    *,
    total_product_ingredient_rows: int,
    effective_canonical_rows: int,
    target_coverage_pct: float,
) -> tuple[list[dict[str, str]], SelectionStats]:
    if not 0 < target_coverage_pct <= 100:
        raise ValueError("target_coverage_pct must be in (0, 100]")
    required_rows = max(
        math.ceil(total_product_ingredient_rows * target_coverage_pct / 100)
        - effective_canonical_rows,
        0,
    )
    selected_source_rows = 0
    selected_new_codes: set[str] = set()
    last_selected_rank = 0
    output: list[dict[str, str]] = []

    for row in rows:
        updated = dict(row)
        selected = is_safe_exact(row) and selected_source_rows < required_rows
        if selected:
            updated["selected_for_target"] = "Y"
            updated["review_status"] = "accepted_auto_exact"
            selected_source_rows += int(row["row_count"])
            last_selected_rank = int(row["rank"])
            if row["proposed_action"] == "create_canonical":
                selected_new_codes.add(row["kcia_ingredient_code"])
        else:
            updated["selected_for_target"] = "N"
            if is_safe_exact(row):
                updated["review_status"] = "candidate_unverified"
        output.append(updated)

    projected_rows = effective_canonical_rows + selected_source_rows
    projected_coverage_pct = projected_rows / max(total_product_ingredient_rows, 1) * 100
    if required_rows and selected_source_rows < required_rows:
        raise ValueError(
            "safe proposals do not reach target coverage: "
            f"selected={selected_source_rows} required={required_rows}"
        )
    return output, SelectionStats(
        selected_rows=sum(row["selected_for_target"] == "Y" for row in output),
        selected_source_rows=selected_source_rows,
        selected_new_canonical=len(selected_new_codes),
        last_selected_rank=last_selected_rank,
        projected_coverage_pct=projected_coverage_pct,
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("proposal rows are empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(encoding="utf-8", newline="", mode="w") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-coverage-pct", type=float, default=80.0)
    args = parser.parse_args()

    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    rows, stats = select_coverage_batch(
        read_csv(args.proposals),
        total_product_ingredient_rows=int(validation["total_product_ingredient_rows"]),
        effective_canonical_rows=int(validation["effective_canonical_rows"]),
        target_coverage_pct=args.target_coverage_pct,
    )
    write_csv(args.output, rows)
    print(
        "Ingredient canonicalization coverage batch: "
        f"selected={stats.selected_rows} source_rows={stats.selected_source_rows} "
        f"new_canonical={stats.selected_new_canonical} last_rank={stats.last_selected_rank} "
        f"projected_coverage={stats.projected_coverage_pct:.4f}% output={args.output}"
    )


if __name__ == "__main__":
    main()
