#!/usr/bin/env python3
"""Build deterministic product-related benchmark datasets from a full data directory."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


DEFAULT_SIZES = (1000, 5000, 10000, 80000)
STATIC_FILES = {
    "concern_to_effect.json",
    "ingredients.csv",
    "ingredient_aliases.csv",
    "ingredient_effect.csv",
    "ingredient_effect_ranges.csv",
    "ingredient_evidence.csv",
    "risk_flags.csv",
    "tags.json",
}
PRODUCT_FILES = {
    "product_image_assets.csv",
    "product_inventory.csv",
    "product_market_signals.csv",
    "product_prices.csv",
    "product_review_profile_stats.csv",
    "product_review_signals.csv",
    "product_review_summary.csv",
    "product_skin_profiles.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def product_files(source_dir: Path) -> list[Path]:
    single = source_dir / "products.csv"
    if single.exists():
        return [single]
    files = sorted((source_dir / "products").glob("*.csv"))
    if not files:
        raise SystemExit(f"products.csv or products/*.csv is missing: {source_dir}")
    return files


def read_rows(files: list[Path]) -> tuple[list[str], list[dict[str, str]]]:
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "product_id" not in reader.fieldnames:
                raise SystemExit(f"product_id column is missing: {path}")
            if headers is None:
                headers = list(reader.fieldnames)
            rows.extend(reader)
    if headers is None:
        raise SystemExit("no product rows found")
    rows.sort(key=lambda row: row["product_id"])
    return headers, rows


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def copy_static_files(source_dir: Path, output_dir: Path) -> None:
    for name in STATIC_FILES:
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, output_dir / name)


def filter_csv(
    source: Path,
    output: Path,
    product_ids: set[str],
    *,
    source_id_allowed: bool = False,
) -> int:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        if "product_id" not in headers and not source_id_allowed:
            shutil.copy2(source, output)
            return -1
        rows = []
        for row in reader:
            key = row.get("product_id")
            if key is None and row.get("source_type") in {"product", "catalog_product"}:
                key = row.get("source_id")
            if key in product_ids or (key is None and row.get("source_type") not in {"product", "catalog_product"}):
                rows.append(row)
    write_csv(output, headers, rows)
    return len(rows)


def copy_product_related(source_dir: Path, output_dir: Path, product_ids: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in sorted(PRODUCT_FILES):
        source = source_dir / name
        if source.exists():
            counts[name] = filter_csv(source, output_dir / name, product_ids)

    vector_docs = source_dir / "vector_docs.csv"
    if vector_docs.exists():
        counts["vector_docs.csv"] = filter_csv(
            vector_docs,
            output_dir / "vector_docs.csv",
            product_ids,
            source_id_allowed=True,
        )

    for directory_name in ("product_ingredients", "storefront_product_reviews"):
        source_dir_path = source_dir / directory_name
        if not source_dir_path.exists():
            continue
        total = 0
        for source in sorted(source_dir_path.glob("*.csv")):
            total += max(
                filter_csv(
                    source,
                    output_dir / directory_name / source.name,
                    product_ids,
                ),
                0,
            )
        counts[directory_name] = total
    return counts


def build_dataset(source_dir: Path, output_root: Path, size: int, product_headers: list[str], product_rows: list[dict[str, str]], overwrite: bool) -> None:
    if size > len(product_rows):
        raise SystemExit(f"requested {size} products, source has only {len(product_rows)}")
    output_dir = output_root / f"benchmark-{size}"
    if output_dir.exists():
        if not overwrite:
            raise SystemExit(f"output exists; use --overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    selected_rows = product_rows[:size]
    product_ids = {row["product_id"] for row in selected_rows}
    write_csv(output_dir / "products" / "products_000.csv", product_headers, selected_rows)
    copy_static_files(source_dir, output_dir)
    related_counts = copy_product_related(source_dir, output_dir, product_ids)
    (output_dir / "product_ids.txt").write_text("\n".join(sorted(product_ids)) + "\n", encoding="utf-8")
    manifest = {
        "version": 1,
        "dataset": str(size),
        "product_count": size,
        "source_dir": str(source_dir),
        "selection": "product_id ascending, deterministic",
        "related_row_counts": related_counts,
        "product_ids_file": "product_ids.txt",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_root = args.output_root.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"source directory is missing: {source_dir}")
    product_headers, product_rows = read_rows(product_files(source_dir))
    for size in sorted(set(args.sizes)):
        build_dataset(source_dir, output_root, size, product_headers, product_rows, args.overwrite)


if __name__ == "__main__":
    main()
