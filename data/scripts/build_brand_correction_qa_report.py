#!/usr/bin/env python3
"""Build before/after QA reports for product brand corrections."""

from __future__ import annotations

import argparse
import csv
import html
from collections import Counter
from dataclasses import replace
from pathlib import Path

from build_brand_normalization_report import (
    ProductRow,
    build_reports,
    group_products_by_normalized_name,
    read_products,
)


SUMMARY_FIELDS = ["metric", "before", "after", "delta", "note"]
SAMPLE_FIELDS = [
    "product_code",
    "source_prefix",
    "product_name",
    "before_brand",
    "after_brand",
    "confidence",
    "basis",
]
MANUAL_PRIORITY_FIELDS = [
    "product_code",
    "source_prefix",
    "current_brand",
    "suspected_brand",
    "product_name",
    "duplicate_group_size",
    "duplicate_brand_count",
    "duplicate_brands",
    "confidence",
    "note",
]


def main() -> None:
    args = parse_args()
    products_before = read_products(args.source_dir)
    if args.recommendable_only:
        products_before = [product for product in products_before if product.is_recommendable]

    corrections = read_corrections(args.corrections)
    products_after, applied_rows = apply_corrections(products_before, corrections)

    before_report, before_manual, _ = build_reports(products_before)
    after_report, after_manual, _ = build_reports(products_after)
    manual_priority_rows = build_manual_priority_rows(products_after, after_manual)

    before_duplicate_groups, before_duplicate_rows = duplicate_brand_name_stats(products_before)
    after_duplicate_groups, after_duplicate_rows = duplicate_brand_name_stats(products_after)

    summary_rows = [
        metric_row("products", len(products_before), len(products_after), "검사 대상 상품 수"),
        metric_row("unique_brands", unique_brand_count(products_before), unique_brand_count(products_after), "브랜드 수"),
        metric_row("correction_file_rows", len(corrections), len(corrections), "보정표 row 수"),
        metric_row("corrections_applied", 0, len(applied_rows), "실제로 적용된 브랜드 보정 수"),
        metric_row("report_rows", len(before_report), len(after_report), "브랜드 정규화 이슈 row 수"),
        metric_row(
            "fix_brand_rows",
            count_action(before_report, "fix_brand"),
            count_action(after_report, "fix_brand"),
            "자동 브랜드 수정 대상",
        ),
        metric_row("manual_review_rows", len(before_manual), len(after_manual), "수동 검수 대상"),
        metric_row(
            "multi_brand_same_name_groups",
            before_duplicate_groups,
            after_duplicate_groups,
            "같은 상품명이 여러 브랜드에 연결된 그룹 수",
        ),
        metric_row(
            "multi_brand_same_name_rows",
            before_duplicate_rows,
            after_duplicate_rows,
            "같은 상품명 다중 브랜드 문제에 영향받는 상품 row 수",
        ),
    ]

    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_summary, SUMMARY_FIELDS, summary_rows)
    write_csv(args.output_samples, SAMPLE_FIELDS, applied_rows)
    write_csv(args.output_manual_priority, MANUAL_PRIORITY_FIELDS, manual_priority_rows)
    write_html(
        args.output_html,
        summary_rows,
        applied_rows,
        before_report,
        after_report,
        manual_priority_rows,
    )

    print(
        "BrandCorrectionQaReport("
        f"products={len(products_before)}, "
        f"corrections_applied={len(applied_rows)}, "
        f"fix_brand_before={count_action(before_report, 'fix_brand')}, "
        f"fix_brand_after={count_action(after_report, 'fix_brand')}, "
        f"manual_before={len(before_manual)}, "
        f"manual_after={len(after_manual)}, "
        f"summary='{args.output_summary}'"
        ")"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create brand correction before/after QA outputs.")
    parser.add_argument("--source-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--corrections",
        type=Path,
        default=Path("data/reconciliation/brand_corrections_recommendable.csv"),
    )
    parser.add_argument(
        "--output-summary",
        type=Path,
        default=Path("data/reconciliation/brand_correction_qa_summary.csv"),
    )
    parser.add_argument(
        "--output-samples",
        type=Path,
        default=Path("data/reconciliation/brand_correction_qa_applied_samples.csv"),
    )
    parser.add_argument(
        "--output-manual-priority",
        type=Path,
        default=Path("data/reconciliation/brand_correction_qa_remaining_manual_priority.csv"),
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=Path("data/reconciliation/brand_correction_qa_report.html"),
    )
    parser.add_argument(
        "--recommendable-only",
        action="store_true",
        help="Only inspect products with is_recommendable=true.",
    )
    return parser.parse_args()


def read_corrections(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {row["product_code"]: row for row in reader}


def apply_corrections(
    products: list[ProductRow],
    corrections: dict[str, dict[str, str]],
) -> tuple[list[ProductRow], list[dict[str, str]]]:
    corrected_products: list[ProductRow] = []
    applied_rows: list[dict[str, str]] = []
    for product in products:
        correction = corrections.get(product.product_id)
        if correction and correction["corrected_brand"] != product.brand:
            corrected_products.append(replace(product, brand=correction["corrected_brand"]))
            applied_rows.append(
                {
                    "product_code": product.product_id,
                    "source_prefix": correction.get("source_prefix", ""),
                    "product_name": product.name,
                    "before_brand": product.brand,
                    "after_brand": correction["corrected_brand"],
                    "confidence": correction.get("confidence", ""),
                    "basis": correction.get("basis", ""),
                }
            )
        else:
            corrected_products.append(product)
    return corrected_products, applied_rows


def duplicate_brand_name_stats(products: list[ProductRow]) -> tuple[int, int]:
    groups = group_products_by_normalized_name(products)
    group_count = 0
    row_count = 0
    for group_products in groups.values():
        brands = {product.brand for product in group_products if product.brand}
        if len(brands) > 1:
            group_count += 1
            row_count += len(group_products)
    return group_count, row_count


def build_manual_priority_rows(
    products: list[ProductRow],
    manual_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    product_groups: dict[str, list[ProductRow]] = {}
    for group_products in group_products_by_normalized_name(products).values():
        for product in group_products:
            product_groups[product.product_id] = group_products

    rows: list[dict[str, str]] = []
    for row in manual_rows:
        group_products = product_groups.get(row["product_code"], [])
        brands = sorted({product.brand for product in group_products if product.brand})
        rows.append(
            {
                "product_code": row["product_code"],
                "source_prefix": row["source_prefix"],
                "current_brand": row["current_brand"],
                "suspected_brand": row["suspected_brand"],
                "product_name": row["product_name"],
                "duplicate_group_size": str(len(group_products)),
                "duplicate_brand_count": str(len(brands)),
                "duplicate_brands": "; ".join(brands[:20]),
                "confidence": row["confidence"],
                "note": row["note"],
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            -int(row["duplicate_group_size"]),
            -int(row["duplicate_brand_count"]),
            row["product_name"],
            row["current_brand"],
            row["product_code"],
        ),
    )


def unique_brand_count(products: list[ProductRow]) -> int:
    return len({product.brand for product in products if product.brand})


def count_action(rows: list[dict[str, str]], action: str) -> int:
    return sum(1 for row in rows if row.get("recommended_action") == action)


def metric_row(metric: str, before: int, after: int, note: str) -> dict[str, str]:
    return {
        "metric": metric,
        "before": str(before),
        "after": str(after),
        "delta": str(after - before),
        "note": note,
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_html(
    path: Path,
    summary_rows: list[dict[str, str]],
    applied_rows: list[dict[str, str]],
    before_report: list[dict[str, str]],
    after_report: list[dict[str, str]],
    manual_priority_rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    action_before = Counter(row["recommended_action"] for row in before_report)
    action_after = Counter(row["recommended_action"] for row in after_report)
    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>브랜드 보정 전후 QA 리포트</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2a22; background: #f8f5ef; }}
    h1, h2 {{ color: #173f2f; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0 32px; background: white; }}
    th, td {{ border: 1px solid #d9d2c3; padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #e8f0ea; }}
    .delta-minus {{ color: #1f6f43; font-weight: 700; }}
    .delta-plus {{ color: #b44c2c; font-weight: 700; }}
    .card {{ background: white; border: 1px solid #d9d2c3; border-radius: 10px; padding: 18px; margin-bottom: 18px; }}
    code {{ background: #eee8dc; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>브랜드 보정 전후 QA 리포트</h1>
  <div class="card">
    <p>추천 가능 상품 기준으로 <code>brand_corrections_recommendable.csv</code> 적용 전/후를 비교했습니다.</p>
    <p>원본 상품 CSV는 수정하지 않고, seed/import 로딩 단계에서 브랜드만 보정하는 전제입니다.</p>
  </div>

  <h2>요약 지표</h2>
  {summary_table(summary_rows)}

  <h2>이슈 유형 변화</h2>
  {action_table(action_before, action_after)}

  <h2>적용된 자동 보정 샘플</h2>
  {sample_table(applied_rows[:80])}

  <h2>남은 수동 검수 우선순위</h2>
  {manual_priority_table(manual_priority_rows[:80])}
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def summary_table(rows: list[dict[str, str]]) -> str:
    body = []
    for row in rows:
        delta = int(row["delta"])
        delta_class = "delta-minus" if delta < 0 else "delta-plus" if delta > 0 else ""
        body.append(
            "<tr>"
            f"<td>{escape(row['metric'])}</td>"
            f"<td>{escape(row['before'])}</td>"
            f"<td>{escape(row['after'])}</td>"
            f"<td class='{delta_class}'>{escape(row['delta'])}</td>"
            f"<td>{escape(row['note'])}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>지표</th><th>보정 전</th><th>보정 후</th><th>변화</th><th>설명</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def action_table(before: Counter[str], after: Counter[str]) -> str:
    actions = sorted(set(before) | set(after))
    body = []
    for action in actions:
        before_count = before.get(action, 0)
        after_count = after.get(action, 0)
        delta = after_count - before_count
        delta_class = "delta-minus" if delta < 0 else "delta-plus" if delta > 0 else ""
        body.append(
            "<tr>"
            f"<td>{escape(action)}</td>"
            f"<td>{before_count}</td>"
            f"<td>{after_count}</td>"
            f"<td class='{delta_class}'>{delta}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>권장 조치</th><th>보정 전</th><th>보정 후</th><th>변화</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def sample_table(rows: list[dict[str, str]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row['product_code'])}</td>"
            f"<td>{escape(row['source_prefix'])}</td>"
            f"<td>{escape(row['product_name'])}</td>"
            f"<td>{escape(row['before_brand'])}</td>"
            f"<td>{escape(row['after_brand'])}</td>"
            f"<td>{escape(row['confidence'])}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>상품 ID</th><th>수집처</th><th>상품명</th><th>보정 전</th><th>보정 후</th><th>신뢰도</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def manual_priority_table(rows: list[dict[str, str]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{escape(row['product_code'])}</td>"
            f"<td>{escape(row['source_prefix'])}</td>"
            f"<td>{escape(row['product_name'])}</td>"
            f"<td>{escape(row['current_brand'])}</td>"
            f"<td>{escape(row['suspected_brand'])}</td>"
            f"<td>{escape(row['duplicate_group_size'])}</td>"
            f"<td>{escape(row['duplicate_brand_count'])}</td>"
            f"<td>{escape(row['duplicate_brands'])}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>상품 ID</th><th>수집처</th><th>상품명</th><th>현재 브랜드</th><th>추정 브랜드</th><th>그룹 row 수</th><th>브랜드 수</th><th>연결 브랜드</th></tr></thead><tbody>" + "".join(body) + "</tbody></table>"


def escape(value: object) -> str:
    return html.escape(str(value))


if __name__ == "__main__":
    main()