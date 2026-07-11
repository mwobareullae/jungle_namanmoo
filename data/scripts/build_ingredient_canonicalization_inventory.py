#!/usr/bin/env python3
"""Build a frequency-ranked review queue for unresolved ingredient ids."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from reconcile_a_group_product_ingredients import (
    load_alias_lookup,
    normalize_raw,
    normalize_text,
    resolve_csv_paths,
)


OUTPUT_FIELDS = [
    "rank",
    "source_ingredient_id",
    "dominant_name",
    "row_count",
    "product_count",
    "cumulative_all_rows_pct",
    "observed_name_count",
    "top_observed_names",
    "observed_names_json",
    "existing_canonical_id",
    "triage_status",
    "triage_note",
]

NOISE_RE = re.compile(r"^[\d\W_]+$", re.UNICODE)


def build_inventory(
    product_ingredients_path: Path,
    aliases_path: Path,
    *,
    limit: int = 300,
    mapped_source_ids: set[str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    alias_lookup = load_alias_lookup(aliases_path)
    mapped_source_ids = mapped_source_ids or set()
    counts: Counter[str] = Counter()
    products: dict[str, set[str]] = defaultdict(set)
    names: dict[str, Counter[str]] = defaultdict(Counter)
    total_rows = 0

    for csv_path in resolve_csv_paths(product_ingredients_path):
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                total_rows += 1
                ingredient_id = row["ingredient_id"].strip()
                if not ingredient_id.startswith("ing_pending_"):
                    continue
                if ingredient_id in mapped_source_ids:
                    continue
                ingredient_name = row["ingredient_name"].strip()
                counts[ingredient_id] += 1
                products[ingredient_id].add(row["product_id"].strip())
                names[ingredient_id][ingredient_name] += 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    output: list[dict[str, str]] = []
    cumulative_rows = 0
    for rank, (ingredient_id, row_count) in enumerate(ranked, start=1):
        cumulative_rows += row_count
        observed_names = names[ingredient_id]
        dominant_name = observed_names.most_common(1)[0][0]
        matched_canonical: Counter[str] = Counter()
        unmatched_rows = 0
        for raw_name, count in observed_names.items():
            cleaned = normalize_raw(raw_name, alias_lookup)
            alias = alias_lookup.get(normalize_text(cleaned)) if cleaned else None
            if alias is None:
                unmatched_rows += count
            else:
                matched_canonical[alias["canonical_id"]] += count

        existing_canonical_id, status, note = classify_candidate(
            dominant_name=dominant_name,
            row_count=row_count,
            matched_canonical=matched_canonical,
            unmatched_rows=unmatched_rows,
        )
        top_names = " | ".join(
            f"{name} ({count})" for name, count in observed_names.most_common(5)
        )
        output.append(
            {
                "rank": str(rank),
                "source_ingredient_id": ingredient_id,
                "dominant_name": dominant_name,
                "row_count": str(row_count),
                "product_count": str(len(products[ingredient_id])),
                "cumulative_all_rows_pct": f"{(cumulative_rows / total_rows) * 100:.4f}",
                "observed_name_count": str(len(observed_names)),
                "top_observed_names": top_names,
                "observed_names_json": json.dumps(
                    [
                        {"name": name, "count": count}
                        for name, count in observed_names.most_common()
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "existing_canonical_id": existing_canonical_id,
                "triage_status": status,
                "triage_note": note,
            }
        )

    stats = {
        "total_rows": total_rows,
        "pending_ids": len(counts),
        "selected_ids": len(output),
        "selected_rows": sum(int(row["row_count"]) for row in output),
    }
    return output, stats


def load_mapped_source_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {
            row["source_ingredient_id"].strip()
            for row in csv.DictReader(handle)
            if not row.get("source_ingredient_name", "").strip()
        }


def classify_candidate(
    *,
    dominant_name: str,
    row_count: int,
    matched_canonical: Counter[str],
    unmatched_rows: int,
) -> tuple[str, str, str]:
    if len(matched_canonical) == 1 and unmatched_rows == 0:
        canonical_id = next(iter(matched_canonical))
        return canonical_id, "merge_existing", "모든 원문명이 기존 alias와 정확히 일치"
    if matched_canonical:
        matched = "; ".join(
            f"{canonical_id}:{count}" for canonical_id, count in matched_canonical.most_common()
        )
        return "", "manual_review", f"일부만 기존 alias와 일치 ({matched}); 미일치 {unmatched_rows}/{row_count}"
    normalized = normalize_text(dominant_name)
    if not normalized or NOISE_RE.fullmatch(normalized):
        return "", "reject_noise_candidate", "숫자·기호 중심의 비성분 원문 후보"
    return "", "canonical_review_required", "기존 alias 없음; 신규 canonical 또는 중복 표기 검토 필요"


def write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product-ingredients",
        type=Path,
        default=Path("data/product_ingredients.csv"),
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("data/ingredient_aliases.csv"),
    )
    parser.add_argument(
        "--mappings",
        type=Path,
        default=Path("data/ingredient_canonical_mappings.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonicalization_top300.csv"),
    )
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()

    rows, stats = build_inventory(
        args.product_ingredients,
        args.aliases,
        limit=args.limit,
        mapped_source_ids=load_mapped_source_ids(args.mappings),
    )
    write_inventory(args.output, rows)
    print(
        "ingredient canonicalization inventory: "
        f"selected={stats['selected_ids']} rows={stats['selected_rows']}/{stats['total_rows']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
