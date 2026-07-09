#!/usr/bin/env python3
"""Build brand alias/mismatch review reports from product catalog CSVs."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


REPORT_FIELDS = [
    "product_code",
    "source_prefix",
    "current_brand",
    "product_name",
    "suspected_brand",
    "issue_type",
    "recommended_action",
    "confidence",
    "note",
]

RULE_FIELDS = [
    "rule_id",
    "condition",
    "issue_type",
    "recommended_action",
    "confidence",
    "note",
]

KNOWN_ALIAS_GROUPS = [
    ("Dr Dennis Gross", "Dr. Dennis Gross Skincare"),
    ("Numbuzin", "넘버즈인"),
]

KNOWN_PREFIX_BRANDS = [
    "Numbuzin",
    "넘버즈인",
    "111SKIN",
    "Clé de Peau Beauté",
    "Cle de Peau Beaute",
    "Dr Dennis Gross",
    "Dr. Dennis Gross Skincare",
]

BROAD_PREFIX_FIX_SOURCES = {"cultbeauty", "lookfantastic", "dermstore", "ulta", "sephora"}

GENERIC_BRAND_TOKENS = {
    "the",
    "and",
    "by",
    "a",
    "an",
    "new",
    "set",
    "no",
}

LEADING_BRACKET_RE = re.compile(r"^\s*[\[\(\{（【][^\]\)\}）】]{1,80}[\]\)\}）】]\s*")


@dataclass(frozen=True)
class ProductRow:
    product_id: str
    brand: str
    name: str
    category: str
    is_recommendable: bool


def main() -> None:
    args = parse_args()
    products = read_products(args.source_dir)
    if args.recommendable_only:
        products = [product for product in products if product.is_recommendable]
    report_rows, manual_rows, rule_rows = build_reports(products)

    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_report, REPORT_FIELDS, report_rows)
    write_csv(args.output_manual, REPORT_FIELDS, manual_rows)
    write_csv(args.output_rules, RULE_FIELDS, rule_rows)

    print(
        "BrandNormalizationReport("
        f"products={len(products)}, "
        f"report_rows={len(report_rows)}, "
        f"manual_rows={len(manual_rows)}, "
        f"rules={len(rule_rows)}, "
        f"output='{args.output_report}'"
        ")"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create brand alias/mismatch reconciliation reports."
    )
    parser.add_argument("--source-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("data/reconciliation/brand_normalization_report.csv"),
    )
    parser.add_argument(
        "--output-manual",
        type=Path,
        default=Path("data/reconciliation/brand_normalization_manual_review.csv"),
    )
    parser.add_argument(
        "--output-rules",
        type=Path,
        default=Path("data/reconciliation/brand_normalization_auto_rules.csv"),
    )
    parser.add_argument(
        "--recommendable-only",
        action="store_true",
        help="Only inspect products with is_recommendable=true.",
    )
    return parser.parse_args()


def read_products(source_dir: Path) -> list[ProductRow]:
    product_paths = resolve_product_paths(source_dir)
    rows: list[ProductRow] = []
    for path in product_paths:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(
                    ProductRow(
                        product_id=(row.get("product_id") or "").strip(),
                        brand=(row.get("brand") or "").strip(),
                        name=(row.get("name") or "").strip(),
                        category=(row.get("category") or "").strip(),
                        is_recommendable=parse_bool(row.get("is_recommendable")),
                    )
                )
    return rows


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def resolve_product_paths(source_dir: Path) -> list[Path]:
    split_dir = source_dir / "products"
    if split_dir.exists():
        paths = sorted(split_dir.glob("*.csv"))
        if paths:
            return paths
    single = source_dir / "products.csv"
    if single.exists():
        return [single]
    raise FileNotFoundError(f"No products CSV found under {source_dir}")


def build_reports(
    products: list[ProductRow],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    brand_index = build_brand_index(products)
    strict_brand_index = build_strict_brand_index()
    alias_lookup = build_alias_lookup()
    normalized_name_groups = group_products_by_normalized_name(products)

    rows_by_product: dict[str, dict[str, str]] = {}

    for product in products:
        suspected = detect_suspected_brand(product, strict_brand_index)
        if suspected and not same_brand_or_alias(product.brand, suspected, alias_lookup):
            rows_by_product[product.product_id] = make_report_row(
                product=product,
                suspected_brand=suspected,
                issue_type="brand_mismatch",
                recommended_action="fix_brand",
                confidence="0.95",
                note="product_name starts with a different known brand token",
            )

    for product in products:
        if product.product_id in rows_by_product:
            continue
        suspected = detect_suspected_brand(product, brand_index)
        if (
            suspected
            and is_broad_prefix_fix_source(product)
            and not same_brand_or_alias(product.brand, suspected, alias_lookup)
        ):
            rows_by_product[product.product_id] = make_report_row(
                product=product,
                suspected_brand=suspected,
                issue_type="brand_mismatch",
                recommended_action="fix_brand",
                confidence="0.82",
                note="foreign-source product_name clearly starts with a catalog brand token",
            )


    for product in products:
        if product.product_id in rows_by_product:
            continue
        alias_group = find_alias_group(product.brand, alias_lookup)
        if alias_group:
            canonical = alias_group[0]
            if normalize_brand(product.brand) != normalize_brand(canonical):
                rows_by_product[product.product_id] = make_report_row(
                    product=product,
                    suspected_brand=canonical,
                    issue_type="brand_alias_candidate",
                    recommended_action="add_brand_alias",
                    confidence="0.90",
                    note=f"known alias group: {' | '.join(alias_group)}",
                )

    for group_products in normalized_name_groups.values():
        brands = sorted({p.brand for p in group_products if p.brand})
        if len(brands) <= 1:
            continue

        inferred = infer_group_brand(group_products, strict_brand_index, alias_lookup)
        weak_inferred = infer_group_brand(group_products, brand_index, alias_lookup)
        for product in group_products:
            if product.product_id in rows_by_product:
                continue
            if inferred and not same_brand_or_alias(product.brand, inferred, alias_lookup):
                rows_by_product[product.product_id] = make_report_row(
                    product=product,
                    suspected_brand=inferred,
                    issue_type="brand_mismatch",
                    recommended_action="fix_brand",
                    confidence="0.88",
                    note=(
                        "same product_name appears under multiple brands; "
                        "brand token in product_name identifies a different brand"
                    ),
                )
            else:
                manual_suspected = inferred or weak_inferred or ""
                if manual_suspected and same_brand_or_alias(product.brand, manual_suspected, alias_lookup):
                    continue
                rows_by_product[product.product_id] = make_report_row(
                    product=product,
                    suspected_brand=manual_suspected,
                    issue_type="needs_manual_review",
                    recommended_action="manual_review",
                    confidence="0.55",
                    note=(
                        "same product_name appears under multiple brands; "
                        f"brands={'; '.join(brands[:12])}"
                    ),
                )

    report_rows = sorted(
        rows_by_product.values(),
        key=lambda row: (
            issue_rank(row["issue_type"]),
            row["source_prefix"],
            row["suspected_brand"],
            row["current_brand"],
            row["product_name"],
            row["product_code"],
        ),
    )
    manual_rows = [row for row in report_rows if row["recommended_action"] == "manual_review"]
    rule_rows = build_rule_rows()
    return report_rows, manual_rows, rule_rows


def build_brand_index(products: list[ProductRow]) -> dict[str, str]:
    brand_counts: dict[str, int] = defaultdict(int)
    for product in products:
        if product.brand:
            brand_counts[product.brand] += 1
    for brand in KNOWN_PREFIX_BRANDS:
        brand_counts.setdefault(brand, 0)

    index: dict[str, str] = {}
    for brand, _count in sorted(brand_counts.items(), key=lambda item: (-len(item[0]), item[0])):
        key = normalize_brand(brand)
        if is_usable_brand_key(key):
            index.setdefault(key, brand)
    return index


def build_strict_brand_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for brand in sorted(KNOWN_PREFIX_BRANDS, key=lambda value: -len(value)):
        key = normalize_brand(brand)
        if is_usable_brand_key(key):
            index.setdefault(key, brand)
    return index


def build_alias_lookup() -> dict[str, tuple[str, ...]]:
    lookup: dict[str, tuple[str, ...]] = {}
    for group in KNOWN_ALIAS_GROUPS:
        for brand in group:
            lookup[normalize_brand(brand)] = group
    return lookup


def group_products_by_normalized_name(
    products: list[ProductRow],
) -> dict[str, list[ProductRow]]:
    groups: dict[str, list[ProductRow]] = defaultdict(list)
    for product in products:
        key = normalize_product_name(product.name)
        if key:
            groups[key].append(product)
    return groups


def detect_suspected_brand(
    product: ProductRow,
    brand_index: dict[str, str],
) -> str:
    name_key = normalize_product_name(strip_leading_marketing_tokens(product.name))
    if not name_key:
        return ""
    for brand_key, brand in sorted(brand_index.items(), key=lambda item: -len(item[0])):
        if len(brand_key) < 3:
            continue
        if name_key.startswith(brand_key):
            return brand
    return ""


def infer_group_brand(
    products: list[ProductRow],
    brand_index: dict[str, str],
    alias_lookup: dict[str, tuple[str, ...]],
) -> str:
    suspected_counts: dict[str, int] = defaultdict(int)
    for product in products:
        suspected = detect_suspected_brand(product, brand_index)
        if suspected:
            group = find_alias_group(suspected, alias_lookup)
            suspected_counts[group[0] if group else suspected] += 1
    if not suspected_counts:
        return ""
    return max(suspected_counts.items(), key=lambda item: (item[1], len(item[0])))[0]


def make_report_row(
    product: ProductRow,
    suspected_brand: str,
    issue_type: str,
    recommended_action: str,
    confidence: str,
    note: str,
) -> dict[str, str]:
    return {
        "product_code": product.product_id,
        "source_prefix": source_prefix(product.product_id),
        "current_brand": product.brand,
        "product_name": product.name,
        "suspected_brand": suspected_brand,
        "issue_type": issue_type,
        "recommended_action": recommended_action,
        "confidence": confidence,
        "note": note,
    }


def build_rule_rows() -> list[dict[str, str]]:
    return [
        {
            "rule_id": "R001",
            "condition": "product_name starts with Numbuzin but current_brand is not Numbuzin/넘버즈인",
            "issue_type": "brand_mismatch",
            "recommended_action": "fix_brand",
            "confidence": "0.95",
            "note": "Do not alias Numbuzin with the wrong current_brand.",
        },
        {
            "rule_id": "R002",
            "condition": "product_name starts with 111SKIN but current_brand is not 111SKIN",
            "issue_type": "brand_mismatch",
            "recommended_action": "fix_brand",
            "confidence": "0.95",
            "note": "Treat as source brand pollution.",
        },
        {
            "rule_id": "R003",
            "condition": "product_name starts with Clé de Peau Beauté/Cle de Peau Beaute but current_brand differs",
            "issue_type": "brand_mismatch",
            "recommended_action": "fix_brand",
            "confidence": "0.95",
            "note": "Accent-insensitive brand prefix match.",
        },
        {
            "rule_id": "R004",
            "condition": "brand is Dr Dennis Gross or Dr. Dennis Gross Skincare",
            "issue_type": "brand_alias_candidate",
            "recommended_action": "add_brand_alias",
            "confidence": "0.90",
            "note": "Same brand family; keep as alias candidate, not product brand pollution.",
        },
        {
            "rule_id": "R005",
            "condition": "brand is Numbuzin or 넘버즈인",
            "issue_type": "brand_alias_candidate",
            "recommended_action": "add_brand_alias",
            "confidence": "0.90",
            "note": "Korean/English display alias only.",
        },
        {
            "rule_id": "R006",
            "condition": "foreign-source product_name clearly starts with a catalog brand token and current_brand differs",
            "issue_type": "brand_mismatch",
            "recommended_action": "fix_brand",
            "confidence": "0.82",
            "note": "Use broad catalog brand prefix only for foreign sources with known brand pollution.",
        },
        {
            "rule_id": "R007",
            "condition": "same normalized product_name appears under multiple current_brand values and no reliable prefix brand is found",
            "issue_type": "needs_manual_review",
            "recommended_action": "manual_review",
            "confidence": "0.55",
            "note": "Do not auto-fix when product_name does not strongly identify a brand.",
        },
    ]


def same_brand_or_alias(
    left: str,
    right: str,
    alias_lookup: dict[str, tuple[str, ...]],
) -> bool:
    left_key = normalize_brand(left)
    right_key = normalize_brand(right)
    if left_key == right_key:
        return True
    left_group = alias_lookup.get(left_key)
    right_group = alias_lookup.get(right_key)
    return bool(left_group and right_group and left_group == right_group)


def find_alias_group(
    brand: str,
    alias_lookup: dict[str, tuple[str, ...]],
) -> tuple[str, ...] | None:
    return alias_lookup.get(normalize_brand(brand))


def normalize_product_name(value: str) -> str:
    return normalize_text(value)


def normalize_brand(value: str) -> str:
    return normalize_text(value)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    without_marks = without_marks.replace("&", "and")
    return "".join(ch for ch in without_marks.casefold() if ch.isalnum())


def strip_leading_marketing_tokens(value: str) -> str:
    cleaned = value or ""
    for _ in range(4):
        next_value = LEADING_BRACKET_RE.sub("", cleaned)
        if next_value == cleaned:
            break
        cleaned = next_value
    return cleaned.strip()


def is_usable_brand_key(key: str) -> bool:
    if not key or key in GENERIC_BRAND_TOKENS:
        return False
    if key.isdigit():
        return False
    return len(key) >= 2


def is_broad_prefix_fix_source(product: ProductRow) -> bool:
    return source_prefix(product.product_id) in BROAD_PREFIX_FIX_SOURCES

def source_prefix(product_id: str) -> str:
    if product_id.startswith("prod_oy_"):
        return "oliveyoung"
    if "_" in product_id:
        return product_id.split("_", 1)[0]
    return ""


def issue_rank(issue_type: str) -> int:
    return {
        "brand_mismatch": 0,
        "brand_alias_candidate": 1,
        "needs_manual_review": 2,
    }.get(issue_type, 9)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
