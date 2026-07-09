"""Build QA outputs for brand correction search/detail/recommendation-candidate checks."""

from __future__ import annotations

import csv
import html
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = ROOT / "apps" / "backend"
if str(BACKEND_APP) not in sys.path:
    sys.path.insert(0, str(BACKEND_APP))

from app.services.data_loader import load_data_catalog  # noqa: E402

TARGET_BRANDS: dict[str, tuple[str, ...]] = {
    "Numbuzin": ("Numbuzin", "넘버즈인"),
    "111SKIN": ("111SKIN",),
    "Dr Dennis Gross": (
        "Dr Dennis Gross",
        "Dr. Dennis Gross",
        "Dr. Dennis Gross Skincare",
    ),
    "Clé de Peau Beauté": (
        "Clé de Peau Beauté",
        "Cle de Peau Beaute",
        "Clé de Peau",
        "Cle de Peau",
    ),
    "La Roche-Posay": (
        "La Roche-Posay",
        "La Roche Posay",
        "라로슈포제",
    ),
}

SUMMARY_FIELDS = [
    "qa_area",
    "target_brand",
    "checked_products",
    "matching_brand_products",
    "name_prefix_matches",
    "text_document_matches",
    "issue_count",
    "status",
    "note",
]
ISSUE_FIELDS = [
    "qa_area",
    "target_brand",
    "product_id",
    "brand",
    "name",
    "category",
    "issue_type",
    "note",
]
DETAIL_FIELDS = [
    "product_id",
    "before_brand",
    "after_brand",
    "name",
    "category",
    "price_count",
    "image_asset_count",
    "ingredient_count",
    "skin_profile_count",
    "vector_doc_count",
    "status",
]
RECOMMENDATION_FIELDS = [
    "target_brand",
    "product_id",
    "brand",
    "name",
    "category",
    "issue_type",
    "status",
]


def main() -> None:
    data_dir = ROOT / "data"
    output_dir = data_dir / "reconciliation"
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = load_data_catalog(data_dir)
    corrections = read_corrections(output_dir / "brand_corrections_recommendable.csv")
    manual_rows = read_csv(output_dir / "brand_normalization_recommendable_manual_review.csv")

    products = list(catalog.products)
    products_by_id = {product.product_id: product for product in products}
    recommendable_ids = read_recommendable_product_ids(data_dir)
    recommendable_products = [product for product in products if product.product_id in recommendable_ids]

    prices_by_product = group_by_product_id(catalog.product_prices)
    images_by_product = group_by_product_id(catalog.product_image_assets)
    ingredients_by_product = group_by_product_id(catalog.product_ingredients)
    skin_profiles_by_product = group_by_product_id(catalog.product_skin_profiles)
    vector_docs_by_product = group_search_documents(catalog.search_documents)

    summary_rows: list[dict[str, str]] = []
    issue_rows: list[dict[str, str]] = []
    recommendation_rows: list[dict[str, str]] = []

    for target_brand, aliases in TARGET_BRANDS.items():
        alias_keys = tuple(normalize(value) for value in aliases)
        matching_brand_products = [
            product
            for product in recommendable_products
            if normalize(product.brand) in alias_keys
        ]
        name_prefix_matches = [
            product
            for product in recommendable_products
            if starts_with_alias(product.name, alias_keys)
        ]
        doc_matches = matching_search_documents(
            catalog.search_documents,
            products_by_id,
            alias_keys,
            recommendable_ids,
        )

        search_issues = []
        for product in name_prefix_matches:
            if normalize(product.brand) not in alias_keys:
                row = issue_row(
                    "brand_search",
                    target_brand,
                    product,
                    "name_prefix_brand_mismatch",
                    "상품명은 대상 브랜드로 시작하지만 로딩된 브랜드가 다릅니다.",
                )
                search_issues.append(row)
                issue_rows.append(row)

        for doc, product in doc_matches:
            if normalize(product.brand) not in alias_keys and starts_with_alias(product.name, alias_keys):
                row = issue_row(
                    "brand_search_document",
                    target_brand,
                    product,
                    "search_document_brand_mismatch",
                    f"검색 문서 {doc.doc_id}가 대상 브랜드 상품명과 다른 브랜드에 연결됩니다.",
                )
                search_issues.append(row)
                issue_rows.append(row)

        recommendation_issues = []
        for product in name_prefix_matches:
            if normalize(product.brand) not in alias_keys:
                recommendation_issues.append(product)
                recommendation_rows.append(
                    {
                        "target_brand": target_brand,
                        "product_id": product.product_id,
                        "brand": product.brand,
                        "name": product.name,
                        "category": product.category,
                        "issue_type": "recommendable_brand_pollution",
                        "status": "fail",
                    }
                )

        if not recommendation_issues:
            for product in name_prefix_matches[:10]:
                recommendation_rows.append(
                    {
                        "target_brand": target_brand,
                        "product_id": product.product_id,
                        "brand": product.brand,
                        "name": product.name,
                        "category": product.category,
                        "issue_type": "name_prefix_candidate_check",
                        "status": "pass",
                    }
                )

        summary_rows.append(
            {
                "qa_area": "brand_search",
                "target_brand": target_brand,
                "checked_products": str(len(recommendable_products)),
                "matching_brand_products": str(len(matching_brand_products)),
                "name_prefix_matches": str(len(name_prefix_matches)),
                "text_document_matches": str(len(doc_matches)),
                "issue_count": str(len(search_issues)),
                "status": "pass" if not search_issues else "fail",
                "note": "추천 가능 상품 기준. 상품명 접두 브랜드와 로딩 브랜드가 충돌하는지 확인.",
            }
        )

    correction_issues = []
    for product_id, row in corrections.items():
        product = products_by_id.get(product_id)
        if product is None:
            correction_issues.append((product_id, "missing_product"))
            continue
        if product.brand != row["corrected_brand"]:
            correction_issues.append((product_id, "brand_not_applied"))
            issue_rows.append(
                {
                    "qa_area": "brand_correction_apply",
                    "target_brand": row["corrected_brand"],
                    "product_id": product.product_id,
                    "brand": product.brand,
                    "name": product.name,
                    "category": product.category,
                    "issue_type": "brand_not_applied",
                    "note": f"expected={row['corrected_brand']}",
                }
            )

    summary_rows.append(
        {
            "qa_area": "brand_correction_apply",
            "target_brand": "ALL",
            "checked_products": str(len(corrections)),
            "matching_brand_products": str(len(corrections) - len(correction_issues)),
            "name_prefix_matches": "",
            "text_document_matches": "",
            "issue_count": str(len(correction_issues)),
            "status": "pass" if not correction_issues else "fail",
            "note": "brand_corrections_recommendable.csv가 data_loader 결과에 적용됐는지 확인.",
        }
    )

    detail_rows = []
    for product_id, row in corrections.items():
        product = products_by_id.get(product_id)
        if product is None:
            continue
        price_count = len(prices_by_product[product_id])
        image_count = len(images_by_product[product_id])
        ingredient_count = len(ingredients_by_product[product_id])
        skin_profile_count = len(skin_profiles_by_product[product_id])
        vector_doc_count = len(vector_docs_by_product[product_id])
        missing = []
        if price_count == 0:
            missing.append("price")
        if image_count == 0 and not product.thumbnail_url and not product.image_urls:
            missing.append("image")
        if ingredient_count == 0:
            missing.append("ingredient")
        if skin_profile_count == 0:
            missing.append("skin_profile")
        if vector_doc_count == 0:
            missing.append("vector_doc")
        status = "pass" if not missing else "fail:" + ";".join(missing)
        detail_rows.append(
            {
                "product_id": product_id,
                "before_brand": row["current_brand"],
                "after_brand": product.brand,
                "name": product.name,
                "category": product.category,
                "price_count": str(price_count),
                "image_asset_count": str(image_count),
                "ingredient_count": str(ingredient_count),
                "skin_profile_count": str(skin_profile_count),
                "vector_doc_count": str(vector_doc_count),
                "status": status,
            }
        )
        if missing:
            issue_rows.append(
                issue_row(
                    "product_detail",
                    product.brand,
                    product,
                    "missing_detail_relation",
                    "누락 연결: " + ", ".join(missing),
                )
            )

    detail_issue_count = sum(1 for row in detail_rows if row["status"] != "pass")
    summary_rows.append(
        {
            "qa_area": "product_detail",
            "target_brand": "corrected_products",
            "checked_products": str(len(detail_rows)),
            "matching_brand_products": "",
            "name_prefix_matches": "",
            "text_document_matches": "",
            "issue_count": str(detail_issue_count),
            "status": "pass" if detail_issue_count == 0 else "fail",
            "note": "보정된 상품의 가격/이미지/성분/피부타입/vector 연결 유지 확인.",
        }
    )
    summary_rows.append(
        {
            "qa_area": "manual_review_hold",
            "target_brand": "ALL",
            "checked_products": str(len(manual_rows)),
            "matching_brand_products": "",
            "name_prefix_matches": "",
            "text_document_matches": "",
            "issue_count": "0",
            "status": "held",
            "note": "수동 검수 60개는 이번 작업에서 의도적으로 보정하지 않음.",
        }
    )

    write_csv(output_dir / "brand_runtime_qa_summary.csv", SUMMARY_FIELDS, summary_rows)
    write_csv(output_dir / "brand_runtime_qa_issues.csv", ISSUE_FIELDS, issue_rows)
    write_csv(output_dir / "brand_detail_qa_corrected_products.csv", DETAIL_FIELDS, detail_rows)
    write_csv(output_dir / "brand_recommendation_candidate_qa.csv", RECOMMENDATION_FIELDS, recommendation_rows)
    write_html_report(
        output_dir / "brand_runtime_qa_report.html",
        summary_rows,
        issue_rows,
        detail_rows,
        recommendation_rows,
    )

    failed = sum(1 for row in summary_rows if row["status"] == "fail")
    print(
        "BrandRuntimeQaReport("
        f"summary_rows={len(summary_rows)}, issues={len(issue_rows)}, "
        f"detail_rows={len(detail_rows)}, recommendation_rows={len(recommendation_rows)}, "
        f"failed_sections={failed})"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))



def read_recommendable_product_ids(data_dir: Path) -> set[str]:
    paths: list[Path] = []
    products_csv = data_dir / "products.csv"
    products_dir = data_dir / "products"
    if products_csv.exists():
        paths.append(products_csv)
    elif products_dir.exists():
        paths.extend(sorted(products_dir.glob("*.csv")))

    product_ids: set[str] = set()
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                if (row.get("is_recommendable") or "").strip().lower() == "true":
                    product_id = (row.get("product_id") or "").strip()
                    if product_id:
                        product_ids.add(product_id)
    return product_ids

def read_corrections(path: Path) -> dict[str, dict[str, str]]:
    return {row["product_code"]: row for row in read_csv(path)}


def group_by_product_id(rows) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row.product_id].append(row)
    return grouped


def group_search_documents(rows) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row.source_id].append(row)
    return grouped


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in value if ch.isalnum())


def starts_with_alias(value: str, alias_keys: tuple[str, ...]) -> bool:
    key = normalize(value)
    return any(key.startswith(alias_key) for alias_key in alias_keys if alias_key)


def is_recommendable(product) -> bool:
    return "recommendable:true" in tuple(product.skin_type_tags)


def matching_search_documents(search_documents, products_by_id, alias_keys, recommendable_ids):
    matches = []
    for doc in search_documents:
        product = products_by_id.get(doc.source_id)
        if product is None or product.product_id not in recommendable_ids:
            continue
        text_key = normalize(doc.text)
        if any(alias_key and alias_key in text_key for alias_key in alias_keys):
            matches.append((doc, product))
    return matches


def issue_row(qa_area: str, target_brand: str, product, issue_type: str, note: str) -> dict[str, str]:
    return {
        "qa_area": qa_area,
        "target_brand": target_brand,
        "product_id": product.product_id,
        "brand": product.brand,
        "name": product.name,
        "category": product.category,
        "issue_type": issue_type,
        "note": note,
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_html_report(path: Path, summary_rows, issue_rows, detail_rows, recommendation_rows) -> None:
    status_class = {"pass": "pass", "fail": "fail", "held": "held"}
    body = f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>브랜드 검색/상세/추천 QA</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 28px; color: #1f2a22; background: #f7f4ed; }}
    h1, h2 {{ margin: 0 0 14px; }}
    section {{ background: #fffdf8; border: 1px solid #ded7c9; border-radius: 12px; padding: 18px; margin: 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #ece5d8; padding: 9px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #efe7d7; position: sticky; top: 0; }}
    .pass {{ color: #1f6b44; font-weight: 700; }}
    .fail {{ color: #b32929; font-weight: 700; }}
    .held {{ color: #8a6500; font-weight: 700; }}
    .scroll {{ max-height: 520px; overflow: auto; border: 1px solid #ece5d8; border-radius: 8px; }}
    code {{ background: #f0eadf; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>브랜드 검색/상세/추천 QA</h1>
  <p>추천 가능 상품 기준으로 브랜드 보정 적용 후 검색/상세/추천 후보 오염 여부를 점검했습니다.</p>
  <section>
    <h2>요약</h2>
    {html_table(summary_rows, status_class=status_class)}
  </section>
  <section>
    <h2>발견 이슈</h2>
    <p>비어 있으면 이번 자동 보정 범위에서 즉시 처리해야 할 이슈가 없다는 뜻입니다.</p>
    <div class="scroll">{html_table(issue_rows[:500])}</div>
  </section>
  <section>
    <h2>추천 후보 샘플</h2>
    <p>대상 브랜드명으로 시작하는 추천 가능 상품이 올바른 브랜드로 로딩되는지 확인한 샘플입니다.</p>
    <div class="scroll">{html_table(recommendation_rows[:300])}</div>
  </section>
  <section>
    <h2>보정 상품 상세 연결 샘플</h2>
    <p>전체 상세 연결 결과는 <code>brand_detail_qa_corrected_products.csv</code>에서 확인할 수 있습니다.</p>
    <div class="scroll">{html_table(detail_rows[:300])}</div>
  </section>
</body>
</html>
"""
    path.write_text(body, encoding="utf-8")


def html_table(rows: list[dict[str, str]], status_class: dict[str, str] | None = None) -> str:
    if not rows:
        return "<p>표시할 행이 없습니다.</p>"
    fields = list(rows[0].keys())
    header = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body_rows = []
    for row in rows:
        cells = []
        for field in fields:
            value = str(row.get(field, ""))
            css = ""
            if field == "status" and status_class:
                css = f' class="{status_class.get(value, "")}"'
            cells.append(f"<td{css}>{html.escape(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"


if __name__ == "__main__":
    main()
