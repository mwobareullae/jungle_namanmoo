#!/usr/bin/env python3
"""Rewrite A-group product ingredient links to canonical ingredient ids.

The script only maps rows that exact-match the alias table after the minimal
label cleanup rules. It does not infer ingredient identity.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


PRODUCT_INGREDIENT_FIELDS = [
    "product_id",
    "ingredient_id",
    "ingredient_name",
    "content_confidence",
    "display_order",
    "concentration_text",
    "concentration_value",
    "concentration_unit",
    "concentration_confidence",
    "normalized_concentration_value",
    "normalized_concentration_unit",
]

SPLIT_CSV_TARGET_BYTES = 45 * 1024 * 1024
SOURCE_CSV_FIELD = "_source_csv"

REVIEW_FIELDS = [
    "product_id",
    "canonical_id",
    "kept_ingredient_name",
    "kept_display_order",
    "source_row_count",
    "source_ingredient_ids",
    "source_ingredient_names",
    "source_display_orders",
    "source_concentration_texts",
    "source_normalized_concentrations",
    "concentration_policy",
]

UNIT_TAIL_RE = re.compile(
    r"(?i)\s*[\(\[\{（]?\s*\d+(?:[,.]\d+)*\s*"
    r"(?:%|ppm|ppb|mg|㎎|g|iu)\s*[\)\]\}）]?\s*$"
)
UNIT_ONLY_RE = re.compile(
    r"(?i)^\s*[\(\[\{（]?\s*\d+(?:[,.]\d+)*\s*"
    r"(?:%|ppm|ppb|mg|㎎|g|iu)\s*[\)\]\}）]?\s*$"
)
CLAIM_TAIL_RE = re.compile(r"\s*[\(\[\{（]?\s*(주름개선|미백|기능성|함량)\s*[\)\]\}）]?\s*$")

CLAIM_PREFIXES = (
    "기능성성분:",
    "기능성 성분:",
    "기능성성분 :",
    "기능성 성분 :",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for csv_path in resolve_csv_paths(path):
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def read_product_ingredient_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for csv_path in resolve_csv_paths(path):
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                row[SOURCE_CSV_FIELD] = str(csv_path)
                rows.append(row)
    return rows


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    *,
    encoding: str = "utf-8",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def resolve_csv_paths(path: Path) -> tuple[Path, ...]:
    if path.exists():
        return (path,)

    shard_dir = path.parent / path.stem
    if not shard_dir.exists():
        raise FileNotFoundError(path)
    shard_paths = tuple(sorted(csv_path for csv_path in shard_dir.glob("*.csv") if csv_path.is_file()))
    if not shard_paths:
        raise FileNotFoundError(f"Split CSV directory is empty: {shard_dir}")
    return shard_paths


def write_product_ingredients(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    shard_dir = path.parent / path.stem
    source_paths = resolve_csv_paths(path)
    if len(source_paths) > 1 and all(row.get(SOURCE_CSV_FIELD) for row in rows):
        write_csv_shards_preserving_sources(source_paths, fieldnames, rows)
        return
    clean_rows = [{field: row.get(field, "") for field in fieldnames} for row in rows]
    if shard_dir.exists() or not path.exists():
        write_csv_shards(shard_dir, path.stem, fieldnames, clean_rows)
        if path.exists():
            path.unlink()
        return

    write_csv(path, fieldnames, clean_rows)


def write_csv_shards_preserving_sources(
    source_paths: tuple[Path, ...],
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    rows_by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        source_path = row.get(SOURCE_CSV_FIELD)
        if source_path is None:
            raise ValueError("source shard metadata is missing")
        rows_by_source[source_path].append({field: row.get(field, "") for field in fieldnames})

    pending_replacements: list[tuple[Path, Path]] = []
    try:
        for source_path in source_paths:
            temp_path = source_path.with_suffix(f"{source_path.suffix}.tmp")
            write_csv(
                temp_path,
                fieldnames,
                rows_by_source.get(str(source_path), []),
                encoding="utf-8-sig",
            )
            pending_replacements.append((temp_path, source_path))
        for temp_path, source_path in pending_replacements:
            temp_path.replace(source_path)
    finally:
        for temp_path, _ in pending_replacements:
            if temp_path.exists():
                temp_path.unlink()


def write_csv_shards(shard_dir: Path, prefix: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    shard_dir.mkdir(parents=True, exist_ok=True)
    for old_path in shard_dir.glob("*.csv"):
        old_path.unlink()

    part = 0
    rows_in_part = 0
    out_path = shard_dir / f"{prefix}_{part:03d}.csv"
    out_handle = out_path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()

    try:
        for row in rows:
            if rows_in_part > 0 and out_path.stat().st_size >= SPLIT_CSV_TARGET_BYTES:
                out_handle.close()
                part += 1
                rows_in_part = 0
                out_path = shard_dir / f"{prefix}_{part:03d}.csv"
                out_handle = out_path.open("w", newline="", encoding="utf-8")
                writer = csv.DictWriter(out_handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()

            writer.writerow(row)
            rows_in_part += 1
    finally:
        out_handle.close()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return "".join(normalized.casefold().split())


def clean_outer(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw or "")
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip("*\"'ㆍ·:;, ")


def normalize_raw(raw: str, alias_lookup: dict[str, dict[str, str]]) -> str:
    normalized = clean_outer(raw)
    if UNIT_ONLY_RE.match(normalized):
        return ""

    for prefix in CLAIM_PREFIXES:
        if prefix in normalized:
            _, after = normalized.split(prefix, 1)
            candidate = clean_outer(after)
            if candidate:
                normalized = candidate
            break

    while True:
        before = normalized
        normalized = UNIT_TAIL_RE.sub("", normalized).strip().rstrip("([{（ ").strip()
        if normalized == before:
            break

    match = CLAIM_TAIL_RE.search(normalized)
    if match:
        candidate = CLAIM_TAIL_RE.sub("", normalized).strip().rstrip("([{（ ").strip()
        if normalize_text(candidate) in alias_lookup:
            normalized = candidate

    return normalized.strip()


def load_alias_lookup(
    path: Path,
    canonical_ids: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        if canonical_ids is not None and row["canonical_id"] not in canonical_ids:
            continue
        key = normalize_text(row["alias"])
        existing = aliases.get(key)
        if existing and existing["canonical_id"] != row["canonical_id"]:
            raise ValueError(
                "alias collision: "
                f"{row['alias']} maps to both {existing['canonical_id']} and {row['canonical_id']}"
            )
        aliases[key] = row
    return aliases


def reconcile_rows(
    rows: list[dict[str, str]],
    alias_lookup: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    transformed: list[tuple[dict[str, str], bool]] = []
    matched_rows = 0

    for row in rows:
        candidate = normalize_raw(row["ingredient_name"], alias_lookup)
        alias = alias_lookup.get(normalize_text(candidate)) if candidate else None
        if alias is None:
            transformed.append((dict(row), False))
            continue

        mapped = dict(row)
        mapped["_source_ingredient_id"] = row["ingredient_id"]
        mapped["ingredient_id"] = alias["canonical_id"]
        transformed.append((mapped, True))
        matched_rows += 1

    grouped: dict[tuple[str, str], list[tuple[dict[str, str], bool]]] = defaultdict(list)
    for row, was_matched in transformed:
        grouped[(row["product_id"], row["ingredient_id"])].append((row, was_matched))

    output_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    collapsed_groups = 0
    collapsed_rows = 0

    emitted_collapsed_keys: set[tuple[str, str]] = set()
    for row, _ in transformed:
        key = (row["product_id"], row["ingredient_id"])
        group = grouped[key]
        if len(group) == 1 or not any(was_matched for _, was_matched in group):
            output_rows.append(product_row(row))
            continue
        if key in emitted_collapsed_keys:
            continue

        emitted_collapsed_keys.add(key)
        collapsed_groups += 1
        collapsed_rows += len(group) - 1
        rows_to_merge = [row for row, _ in group]
        merged, review = merge_group(rows_to_merge)
        output_rows.append(merged)
        review_rows.append(review)

    stats = {
        "input_rows": len(rows),
        "matched_rows": matched_rows,
        "output_rows": len(output_rows),
        "collapsed_groups": collapsed_groups,
        "collapsed_rows": collapsed_rows,
        "review_rows": len(review_rows),
    }
    return output_rows, review_rows, stats


def merge_group(rows: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    ordered = sorted(rows, key=order_key)
    primary = dict(ordered[0])
    primary["display_order"] = str(min(order_key(row) for row in ordered))

    text_values = unique_nonempty(row.get("concentration_text", "") for row in ordered)
    normalized_pairs = unique_nonempty(
        concentration_pair(
            row.get("normalized_concentration_value", ""),
            row.get("normalized_concentration_unit", ""),
        )
        for row in ordered
    )
    raw_pairs = unique_nonempty(
        concentration_pair(row.get("concentration_value", ""), row.get("concentration_unit", ""))
        for row in ordered
    )

    if len(normalized_pairs) > 1 or len(raw_pairs) > 1:
        concentration_policy = "ambiguous_numeric_blank"
        clear_concentration(primary)
    elif len(normalized_pairs) == 1 or len(raw_pairs) == 1:
        concentration_policy = "single_numeric_preserved"
        source = first_row_with_concentration(ordered)
        copy_concentration(primary, source)
    elif len(text_values) > 1:
        concentration_policy = "ambiguous_text_blank"
        clear_concentration(primary)
    elif len(text_values) == 1:
        concentration_policy = "single_text_preserved"
        primary["concentration_text"] = text_values[0]
        primary["concentration_confidence"] = first_nonempty(
            row.get("concentration_confidence", "") for row in ordered
        ) or "unknown"
        primary["concentration_value"] = ""
        primary["concentration_unit"] = ""
        primary["normalized_concentration_value"] = ""
        primary["normalized_concentration_unit"] = ""
    else:
        concentration_policy = "none"
        clear_concentration(primary)

    review = {
        "product_id": primary["product_id"],
        "canonical_id": primary["ingredient_id"],
        "kept_ingredient_name": primary.get("ingredient_name", ""),
        "kept_display_order": primary.get("display_order", ""),
        "source_row_count": str(len(rows)),
        "source_ingredient_ids": "; ".join(
            unique_nonempty(row.get("_source_ingredient_id", row.get("ingredient_id", "")) for row in rows)
        ),
        "source_ingredient_names": "; ".join(unique_nonempty(row.get("ingredient_name", "") for row in rows)),
        "source_display_orders": "; ".join(unique_nonempty(row.get("display_order", "") for row in rows)),
        "source_concentration_texts": "; ".join(text_values),
        "source_normalized_concentrations": "; ".join(normalized_pairs),
        "concentration_policy": concentration_policy,
    }
    return product_row(primary), review


def product_row(row: dict[str, str]) -> dict[str, str]:
    output = {field: row.get(field, "") for field in PRODUCT_INGREDIENT_FIELDS}
    if row.get(SOURCE_CSV_FIELD):
        output[SOURCE_CSV_FIELD] = row[SOURCE_CSV_FIELD]
    return output


def order_key(row: dict[str, str]) -> int:
    try:
        return int(row.get("display_order", ""))
    except ValueError:
        return 999999


def unique_nonempty(values) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def concentration_pair(value: str, unit: str) -> str:
    value = (value or "").strip()
    unit = (unit or "").strip()
    if not value and not unit:
        return ""
    return f"{value} {unit}".strip()


def first_nonempty(values) -> str:
    for value in values:
        if value:
            return value
    return ""


def first_row_with_concentration(rows: list[dict[str, str]]) -> dict[str, str]:
    for row in rows:
        if row.get("normalized_concentration_value") or row.get("concentration_value"):
            return row
    return rows[0]


def copy_concentration(target: dict[str, str], source: dict[str, str]) -> None:
    for field in [
        "concentration_text",
        "concentration_value",
        "concentration_unit",
        "concentration_confidence",
        "normalized_concentration_value",
        "normalized_concentration_unit",
    ]:
        target[field] = source.get(field, "")


def clear_concentration(row: dict[str, str]) -> None:
    row["concentration_text"] = ""
    row["concentration_value"] = ""
    row["concentration_unit"] = ""
    row["concentration_confidence"] = "unknown"
    row["normalized_concentration_value"] = ""
    row["normalized_concentration_unit"] = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-ingredients", type=Path, default=Path("data/product_ingredients.csv"))
    parser.add_argument("--aliases", type=Path, default=Path("data/ingredient_aliases.csv"))
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("data/reconciliation/a_group_product_ingredient_collapse_review.csv"),
    )
    parser.add_argument(
        "--canonical-id",
        action="append",
        dest="canonical_ids",
        help="only apply aliases targeting this canonical id; repeat for multiple ids",
    )
    parser.add_argument("--write", action="store_true", help="rewrite product_ingredients.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_product_ingredient_rows(args.product_ingredients)
    canonical_ids = set(args.canonical_ids) if args.canonical_ids else None
    alias_lookup = load_alias_lookup(args.aliases, canonical_ids)
    output_rows, review_rows, stats = reconcile_rows(rows, alias_lookup)

    if args.write:
        write_product_ingredients(args.product_ingredients, PRODUCT_INGREDIENT_FIELDS, output_rows)
        write_csv(args.review_output, REVIEW_FIELDS, review_rows)

    for key, value in stats.items():
        print(f"{key}: {value}")
    if args.write:
        print(f"wrote: {args.product_ingredients}")
        print(f"wrote: {args.review_output}")


if __name__ == "__main__":
    main()
