#!/usr/bin/env python3
"""Build a smaller, deterministic seed data directory from the full data CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


PRODUCT_SCOPED_FILES = (
    "product_prices.csv",
    "product_inventory.csv",
    "product_skin_profiles.csv",
    "product_image_assets.csv",
)

JSON_FILES = (
    "tags.json",
    "concern_to_effect.json",
)


@dataclass(frozen=True)
class SubsetStats:
    selected_products: int
    selected_ingredients: int
    selected_effects: int
    output_dir: Path


def main() -> None:
    args = _parse_args()
    stats = build_seed_subset(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        limit=None if args.no_limit else args.limit,
        recommendable_only=not args.include_non_recommendable,
        force=args.force,
    )
    print(
        "SeedSubset("
        f"products={stats.selected_products}, "
        f"ingredients={stats.selected_ingredients}, "
        f"effects={stats.selected_effects}, "
        f"output_dir='{stats.output_dir}'"
        ")"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a small seed dataset for local development. "
            "By default, it selects the first 1,000 is_recommendable=true products "
            "and keeps related product, ingredient, evidence, risk, and search rows."
        )
    )
    parser.add_argument("--source-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/dev-small"))
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument(
        "--no-limit",
        action="store_true",
        help="Keep all products that match the recommendable filter.",
    )
    parser.add_argument(
        "--include-non-recommendable",
        action="store_true",
        help="Do not filter by products.csv is_recommendable=true.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Remove and recreate output-dir if it already exists.",
    )
    return parser.parse_args()


def build_seed_subset(
    *,
    source_dir: Path,
    output_dir: Path,
    limit: int | None = 1000,
    recommendable_only: bool = True,
    force: bool = False,
) -> SubsetStats:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive or None.")
    if not source_dir.exists():
        raise FileNotFoundError(f"source_dir does not exist: {source_dir}")
    _prepare_output_dir(output_dir, force=force)

    products = _read_csv(source_dir / "products.csv")
    selected_products = _select_products(
        products,
        limit=limit,
        recommendable_only=recommendable_only,
    )
    selected_product_ids = {row["product_id"] for row in selected_products}
    _write_csv(output_dir / "products.csv", products.fieldnames, selected_products)

    for file_name in PRODUCT_SCOPED_FILES:
        _filter_csv_by_values(
            source_dir / file_name,
            output_dir / file_name,
            "product_id",
            selected_product_ids,
        )

    product_ingredient_rows = _filter_csv_by_values(
        source_dir / "product_ingredients.csv",
        output_dir / "product_ingredients.csv",
        "product_id",
        selected_product_ids,
    )
    selected_ingredient_ids = {row["ingredient_id"] for row in product_ingredient_rows}

    _filter_csv_by_values(
        source_dir / "ingredients.csv",
        output_dir / "ingredients.csv",
        "ingredient_id",
        selected_ingredient_ids,
    )
    _filter_csv_by_values(
        source_dir / "ingredient_aliases.csv",
        output_dir / "ingredient_aliases.csv",
        "canonical_id",
        selected_ingredient_ids,
        optional=True,
    )

    ingredient_effect_rows = _filter_csv_by_values(
        source_dir / "ingredient_effect.csv",
        output_dir / "ingredient_effect.csv",
        "ingredient_id",
        selected_ingredient_ids,
    )
    selected_effect_ids = {row["effect_id"] for row in ingredient_effect_rows}

    _filter_csv_by_ingredient_and_effect(
        source_dir / "ingredient_effect_ranges.csv",
        output_dir / "ingredient_effect_ranges.csv",
        selected_ingredient_ids=selected_ingredient_ids,
        selected_effect_ids=selected_effect_ids,
    )
    _filter_csv_by_ingredient_and_effect(
        source_dir / "ingredient_evidence.csv",
        output_dir / "ingredient_evidence.csv",
        selected_ingredient_ids=selected_ingredient_ids,
        selected_effect_ids=selected_effect_ids,
    )
    _filter_csv_by_values(
        source_dir / "risk_flags.csv",
        output_dir / "risk_flags.csv",
        "ingredient_id",
        selected_ingredient_ids,
    )
    _filter_vector_docs(
        source_dir / "vector_docs.csv",
        output_dir / "vector_docs.csv",
        selected_product_ids=selected_product_ids,
        selected_ingredient_ids=selected_ingredient_ids,
    )
    _filter_csv_by_values(
        source_dir / "product_market_signals.csv",
        output_dir / "product_market_signals.csv",
        "product_id",
        selected_product_ids,
        optional=True,
    )
    for file_name in JSON_FILES:
        shutil.copy2(source_dir / file_name, output_dir / file_name)

    _write_manifest(
        output_dir,
        source_dir=source_dir,
        limit=limit,
        recommendable_only=recommendable_only,
        selected_products=len(selected_products),
        selected_ingredients=len(selected_ingredient_ids),
        selected_effects=len(selected_effect_ids),
    )
    return SubsetStats(
        selected_products=len(selected_products),
        selected_ingredients=len(selected_ingredient_ids),
        selected_effects=len(selected_effect_ids),
        output_dir=output_dir,
    )


def _prepare_output_dir(output_dir: Path, *, force: bool) -> None:
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"output_dir already exists. Re-run with --force: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)


def _select_products(
    products: _CsvRows,
    *,
    limit: int | None,
    recommendable_only: bool,
) -> list[dict[str, str]]:
    rows = products.rows
    if recommendable_only:
        if "is_recommendable" not in (products.fieldnames or ()):
            raise ValueError("products.csv must contain is_recommendable when recommendable_only=True.")
        rows = [row for row in rows if _is_true(row.get("is_recommendable", ""))]
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("No products matched the subset criteria.")
    return rows


@dataclass(frozen=True)
class _CsvRows:
    fieldnames: list[str]
    rows: list[dict[str, str]]


def _read_csv(path: Path) -> _CsvRows:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = list(reader.fieldnames or [])
        return _CsvRows(fieldnames=fieldnames, rows=[dict(row) for row in reader])


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _filter_csv_by_values(
    source_path: Path,
    output_path: Path,
    field_name: str,
    allowed_values: set[str],
    *,
    optional: bool = False,
) -> list[dict[str, str]]:
    if optional and not source_path.exists():
        return []
    rows = _read_csv(source_path)
    selected_rows = [row for row in rows.rows if row.get(field_name, "") in allowed_values]
    _write_csv(output_path, rows.fieldnames, selected_rows)
    return selected_rows


def _filter_csv_by_ingredient_and_effect(
    source_path: Path,
    output_path: Path,
    *,
    selected_ingredient_ids: set[str],
    selected_effect_ids: set[str],
) -> list[dict[str, str]]:
    rows = _read_csv(source_path)
    selected_rows = [
        row
        for row in rows.rows
        if row.get("ingredient_id", "") in selected_ingredient_ids
        and row.get("effect_id", "") in selected_effect_ids
    ]
    _write_csv(output_path, rows.fieldnames, selected_rows)
    return selected_rows


def _filter_vector_docs(
    source_path: Path,
    output_path: Path,
    *,
    selected_product_ids: set[str],
    selected_ingredient_ids: set[str],
) -> list[dict[str, str]]:
    rows = _read_csv(source_path)
    selected_rows = [
        row
        for row in rows.rows
        if (
            row.get("source_type") == "product"
            and row.get("source_id", "") in selected_product_ids
        )
        or (
            row.get("source_type") == "ingredient"
            and row.get("source_id", "") in selected_ingredient_ids
        )
    ]
    _write_csv(output_path, rows.fieldnames, selected_rows)
    return selected_rows


def _write_manifest(
    output_dir: Path,
    *,
    source_dir: Path,
    limit: int | None,
    recommendable_only: bool,
    selected_products: int,
    selected_ingredients: int,
    selected_effects: int,
) -> None:
    manifest = {
        "source_dir": str(source_dir),
        "limit": limit,
        "recommendable_only": recommendable_only,
        "selected_products": selected_products,
        "selected_ingredients": selected_ingredients,
        "selected_effects": selected_effects,
        "notes": (
            "Generated local seed subset. Do not edit generated files by hand; "
            "regenerate from data/*.csv instead."
        ),
    }
    (output_dir / "subset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_true(value: str) -> bool:
    return value.strip().casefold() == "true"


if __name__ == "__main__":
    main()
