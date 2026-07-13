#!/usr/bin/env python3
"""Validate canonical mappings against every product ingredient row."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationStats:
    canonical_count: int
    mapping_count: int
    mapped_target_count: int
    total_product_ingredient_rows: int
    product_count: int
    affected_product_count: int
    already_canonical_rows: int
    mapped_source_rows: int
    effective_canonical_rows: int
    unmapped_pending_rows: int
    effective_canonical_coverage_pct: float
    duplicate_effective_pairs: int
    unique_effective_pairs: int
    missing_mapping_source_ids: tuple[str, ...]


def resolve_csv_paths(path: Path) -> tuple[Path, ...]:
    if path.exists():
        return (path,)
    shard_dir = path.parent / path.stem
    paths = tuple(sorted(shard_dir.glob("*.csv"))) if shard_dir.exists() else ()
    if not paths:
        raise FileNotFoundError(path)
    return paths


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_batch(
    *,
    ingredients_path: Path,
    mappings_path: Path,
    product_ingredients_path: Path,
) -> ValidationStats:
    ingredient_rows = load_rows(ingredients_path)
    all_ingredient_ids = {row["ingredient_id"] for row in ingredient_rows}
    canonical_ids = {
        ingredient_id
        for ingredient_id in all_ingredient_ids
        if not ingredient_id.startswith("ing_pending_")
    }
    mapping_rows = load_rows(mappings_path)
    canonical_by_source = {
        row["source_ingredient_id"]: row["canonical_id"]
        for row in mapping_rows
        if not row.get("source_ingredient_name", "").strip()
    }
    canonical_by_source_name = {
        (row["source_ingredient_id"], "".join(row["source_ingredient_name"].casefold().split())): row[
            "canonical_id"
        ]
        for row in mapping_rows
        if row.get("source_ingredient_name", "").strip()
    }
    mapping_keys = [
        (
            row["source_ingredient_id"],
            "".join(row.get("source_ingredient_name", "").casefold().split()),
        )
        for row in mapping_rows
    ]
    if len(mapping_keys) != len(set(mapping_keys)):
        raise ValueError("ingredient canonical mapping source/name keys are not unique")
    all_mapping_sources = {row["source_ingredient_id"] for row in mapping_rows}
    all_mapping_targets = {row["canonical_id"] for row in mapping_rows}
    missing_source_definitions = sorted(all_mapping_sources - all_ingredient_ids)
    missing_targets = sorted(all_mapping_targets - canonical_ids)
    if missing_source_definitions or missing_targets:
        raise ValueError(
            "mapping references are invalid: "
            f"missing_sources={missing_source_definitions[:5]} missing_targets={missing_targets[:5]}"
        )

    total_rows = 0
    product_count = 0
    affected_product_count = 0
    already_canonical_rows = 0
    mapped_source_rows = 0
    unmapped_pending_rows = 0
    duplicate_effective_pairs = 0
    unique_effective_pairs = 0
    seen_wildcard_sources: set[str] = set()
    completed_products: set[str] = set()
    current_product = ""
    current_effective_ids: set[str] = set()
    current_affected = False

    def finish_product() -> None:
        nonlocal product_count, affected_product_count, unique_effective_pairs
        if not current_product:
            return
        product_count += 1
        affected_product_count += int(current_affected)
        unique_effective_pairs += len(current_effective_ids)
        completed_products.add(current_product)

    for csv_path in resolve_csv_paths(product_ingredients_path):
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                total_rows += 1
                product_id = row["product_id"]
                if product_id != current_product:
                    finish_product()
                    if product_id in completed_products:
                        raise ValueError(
                            "product ingredient rows must be contiguous for streaming validation: "
                            f"{product_id}"
                        )
                    current_product = product_id
                    current_effective_ids = set()
                    current_affected = False

                source_id = row["ingredient_id"]
                normalized_name = "".join(row["ingredient_name"].casefold().split())
                target_id = canonical_by_source_name.get(
                    (source_id, normalized_name),
                    canonical_by_source.get(source_id),
                )
                if target_id is not None:
                    mapped_source_rows += 1
                    current_affected = True
                    if source_id in canonical_by_source:
                        seen_wildcard_sources.add(source_id)
                    effective_id = target_id
                else:
                    effective_id = source_id
                    if source_id in canonical_ids:
                        already_canonical_rows += 1
                    elif source_id.startswith("ing_pending_"):
                        unmapped_pending_rows += 1
                    else:
                        raise ValueError(f"unknown product ingredient id: {source_id}")

                if effective_id in current_effective_ids:
                    duplicate_effective_pairs += 1
                else:
                    current_effective_ids.add(effective_id)
    finish_product()

    effective_canonical_rows = already_canonical_rows + mapped_source_rows
    missing_mapping_sources = tuple(sorted(set(canonical_by_source) - seen_wildcard_sources))
    if missing_mapping_sources:
        raise ValueError(
            "mapping source IDs have no product rows: " + ", ".join(missing_mapping_sources[:10])
        )
    return ValidationStats(
        canonical_count=len(canonical_ids),
        mapping_count=len(mapping_rows),
        mapped_target_count=len(all_mapping_targets),
        total_product_ingredient_rows=total_rows,
        product_count=product_count,
        affected_product_count=affected_product_count,
        already_canonical_rows=already_canonical_rows,
        mapped_source_rows=mapped_source_rows,
        effective_canonical_rows=effective_canonical_rows,
        unmapped_pending_rows=unmapped_pending_rows,
        effective_canonical_coverage_pct=round(
            effective_canonical_rows / max(total_rows, 1) * 100,
            4,
        ),
        duplicate_effective_pairs=duplicate_effective_pairs,
        unique_effective_pairs=unique_effective_pairs,
        missing_mapping_source_ids=missing_mapping_sources,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ingredients", type=Path, default=Path("data/ingredients.csv"))
    parser.add_argument(
        "--mappings",
        type=Path,
        default=Path("data/ingredient_canonical_mappings.csv"),
    )
    parser.add_argument(
        "--product-ingredients",
        type=Path,
        default=Path("data/product_ingredients.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reconciliation/ingredient_canonicalization_validation.json"),
    )
    args = parser.parse_args()
    stats = validate_batch(
        ingredients_path=args.ingredients,
        mappings_path=args.mappings,
        product_ingredients_path=args.product_ingredients,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(stats), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "Ingredient canonicalization validation: "
        f"canonical={stats.canonical_count} mappings={stats.mapping_count} "
        f"mapped_rows={stats.mapped_source_rows}/{stats.total_product_ingredient_rows} "
        f"coverage={stats.effective_canonical_coverage_pct:.4f}% "
        f"collapsed_duplicates={stats.duplicate_effective_pairs} output={args.output}"
    )


if __name__ == "__main__":
    main()
