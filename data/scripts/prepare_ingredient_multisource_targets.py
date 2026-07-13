#!/usr/bin/env python3
"""Create the 482-ingredient multi-source review target and exclusion audit."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence


EXCLUDED_FIELDS = [
    "ingredient_rank",
    "ingredient_id",
    "name_ko",
    "name_en",
    "product_count",
    "pubmed_raw_hit_count",
    "exclusion_reason",
    "scope",
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_targets(
    target_rows: Sequence[Mapping[str, str]],
    screening_rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    screening_by_ingredient: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in screening_rows:
        screening_by_ingredient[row["ingredient_id"]].append(row)

    excluded_ids = {
        row["ingredient_id"]
        for row in target_rows
        if int(row["raw_pubmed_hit_count"]) > 0
        and screening_by_ingredient[row["ingredient_id"]]
        and all(
            paper["relation_scope"] == "unconfirmed"
            for paper in screening_by_ingredient[row["ingredient_id"]]
        )
    }
    targets = [dict(row) for row in target_rows if row["ingredient_id"] not in excluded_ids]
    excluded = [
        {
            "ingredient_rank": row["ingredient_rank"],
            "ingredient_id": row["ingredient_id"],
            "name_ko": row.get("name_ko", ""),
            "name_en": row.get("name_en", ""),
            "product_count": row.get("product_count", "0"),
            "pubmed_raw_hit_count": row["raw_pubmed_hit_count"],
            "exclusion_reason": "exact_ingredient_not_confirmed_in_pubmed_title_or_abstract",
            "scope": "research_target_only_canonical_ingredient_retained",
        }
        for row in target_rows
        if row["ingredient_id"] in excluded_ids
    ]
    return targets, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--target-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_482.csv"),
    )
    parser.add_argument(
        "--excluded-output",
        type=Path,
        default=Path("data/reconciliation/ingredient_paper_targets_excluded_18.csv"),
    )
    args = parser.parse_args()

    target_fields, target_rows = read_csv(args.targets)
    _, screening_rows = read_csv(args.screening)
    targets, excluded = prepare_targets(target_rows, screening_rows)
    if len(target_rows) != 500 or len(targets) != 482 or len(excluded) != 18:
        raise ValueError(
            f"Unexpected target split: input={len(target_rows)} kept={len(targets)} excluded={len(excluded)}"
        )
    write_csv(args.target_output, target_fields, targets)
    write_csv(args.excluded_output, EXCLUDED_FIELDS, excluded)
    print(f"Prepared multi-source targets: kept={len(targets)} excluded={len(excluded)}")


if __name__ == "__main__":
    main()
