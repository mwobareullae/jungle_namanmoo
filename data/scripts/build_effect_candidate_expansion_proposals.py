#!/usr/bin/env python3
"""Build an intentionally broad initial canonical-expansion screen.

The historical target count controls only which exact ingredients are added to
the canonical recognition layer. The final paper-review list is decided by
``ingredient_effect_pubmed_screening.csv``. CosIng functions are not scientific
evidence, approval, or runtime scores.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from build_ingredient_role_inventory import (
    CosingRecord,
    effect_signals,
    fetch_cosing_records,
    load_cosing_cache,
    match_cosing_record,
    write_cosing_cache,
)
from build_kcia_canonicalization_proposals import PROPOSAL_FIELDS


EXTRA_FIELDS = [
    "baseline_effect_candidate_count",
    "target_effect_candidate_count",
    "cosing_match_status",
    "cosing_inci_name",
    "cosing_functions",
    "effect_signal_ids",
    "effect_signal_basis",
    "effect_candidate_rank",
    "effect_candidate_selection_reason",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[*PROPOSAL_FIELDS, *EXTRA_FIELDS],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def candidate_records(
    proposal_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    rows_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in proposal_rows:
        if (
            row.get("official_match_status") != "official_exact"
            or row.get("proposed_action") != "create_canonical"
            or row.get("proposal_confidence") != "high"
            or not row.get("proposed_canonical_id")
        ):
            continue
        rows_by_id[row["proposed_canonical_id"]].append(row)

    ingredients = [
        {
            "ingredient_id": canonical_id,
            "name_en": rows[0]["kcia_standard_name_en"],
        }
        for canonical_id, rows in sorted(rows_by_id.items())
    ]
    return ingredients, rows_by_id


def signal_basis(signals: dict[str, tuple[str, tuple[str, ...]]]) -> str:
    return "|".join(
        f"{effect_id}:{strength}:{'+'.join(functions)}"
        for effect_id, (strength, functions) in sorted(signals.items())
    )


def build_expansion_rows(
    proposal_rows: list[dict[str, str]],
    records: dict[str, CosingRecord],
    *,
    current_candidate_count: int,
    target_candidate_count: int,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    ingredients, rows_by_id = candidate_records(proposal_rows)
    needed = max(target_candidate_count - current_candidate_count, 0)
    ranked: list[dict[str, object]] = []

    for ingredient in ingredients:
        canonical_id = ingredient["ingredient_id"]
        match_status, record = match_cosing_record(ingredient["name_en"], records)
        if record is None:
            continue
        signals = effect_signals(record.functions)
        if not signals:
            continue
        source_rows = rows_by_id[canonical_id]
        strongest = "high" if any(value[0] == "high" for value in signals.values()) else "medium"
        ranked.append(
            {
                "canonical_id": canonical_id,
                "match_status": match_status,
                "record": record,
                "signals": signals,
                "strength": strongest,
                "row_count": sum(int(row["row_count"]) for row in source_rows),
                "product_count": sum(int(row["product_count"]) for row in source_rows),
            }
        )

    ranked.sort(
        key=lambda row: (
            0 if row["strength"] == "high" else 1,
            -int(row["product_count"]),
            -int(row["row_count"]),
            str(row["canonical_id"]),
        )
    )
    selected = ranked[:needed]
    if len(selected) < needed:
        raise ValueError(
            f"효능 후보가 부족합니다: 필요 {needed}, 확보 {len(selected)}. "
            "pending inventory 범위를 늘려야 합니다."
        )

    metadata_by_id = {str(row["canonical_id"]): row for row in ranked}
    rank_by_id = {
        str(row["canonical_id"]): index for index, row in enumerate(selected, start=1)
    }
    output: list[dict[str, str]] = []
    for canonical_id, source_rows in rows_by_id.items():
        metadata = metadata_by_id.get(canonical_id)
        if metadata is None:
            continue
        record = metadata["record"]
        signals = metadata["signals"]
        selected_rank = rank_by_id.get(canonical_id)
        for source_row in source_rows:
            row = {field: source_row.get(field, "") for field in PROPOSAL_FIELDS}
            row["selected_for_target"] = "Y" if selected_rank is not None else "N"
            row["review_status"] = (
                "accepted_auto_exact" if selected_rank is not None else "candidate_unverified"
            )
            row.update(
                {
                    "cosing_match_status": str(metadata["match_status"]),
                    "baseline_effect_candidate_count": str(current_candidate_count),
                    "target_effect_candidate_count": str(target_candidate_count),
                    "cosing_inci_name": record.inci_name,
                    "cosing_functions": "|".join(record.functions),
                    "effect_signal_ids": "|".join(sorted(signals)),
                    "effect_signal_basis": signal_basis(signals),
                    "effect_candidate_rank": str(selected_rank or ""),
                    "effect_candidate_selection_reason": (
                        "KCIA exact canonical + CosIng 6축 기능 신호; 논문 검토 후보일 뿐 점수 아님"
                    ),
                }
            )
            output.append(row)

    output.sort(
        key=lambda row: (
            0 if row["selected_for_target"] == "Y" else 1,
            int(row["effect_candidate_rank"] or 10**9),
            int(row["rank"]),
        )
    )
    stats = {
        "current_effect_candidate_count": current_candidate_count,
        "target_effect_candidate_count": target_candidate_count,
        "needed_new_effect_candidates": needed,
        "available_effect_candidates": len(ranked),
        "selected_new_effect_candidates": len(selected),
        "projected_effect_candidate_count": current_candidate_count + len(selected),
        "selected_source_rows": sum(row["selected_for_target"] == "Y" for row in output),
    }
    return output, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-proposals", type=Path, required=True)
    parser.add_argument("--current-effect-candidates", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonical_expansion_proposals_initial.csv"),
    )
    parser.add_argument("--target-effect-candidates", type=int, default=500)
    parser.add_argument("--cosing-cache", type=Path, default=Path("/tmp/cosing_effect_expansion.csv"))
    parser.add_argument("--refresh-cosing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proposals = read_csv(args.canonical_proposals)
    ingredients, _ = candidate_records(proposals)
    if args.cosing_cache.exists() and not args.refresh_cosing:
        records, _ = load_cosing_cache(args.cosing_cache)
    else:
        records = fetch_cosing_records(ingredients)
        write_cosing_cache(args.cosing_cache, records, "2026-07-12")

    rows, stats = build_expansion_rows(
        proposals,
        records,
        current_candidate_count=args.current_effect_candidates,
        target_candidate_count=args.target_effect_candidates,
    )
    write_csv(args.output, rows)
    print(
        "Effect candidate expansion proposals: "
        f"available={stats['available_effect_candidates']} "
        f"selected={stats['selected_new_effect_candidates']} "
        f"projected={stats['projected_effect_candidate_count']}/"
        f"{stats['target_effect_candidate_count']} "
        f"source_rows={stats['selected_source_rows']} output={args.output}"
    )


if __name__ == "__main__":
    main()
