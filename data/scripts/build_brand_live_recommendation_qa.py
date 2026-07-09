"""Run live-ish brand QA through seed, search, recommendation, and product detail services.

This script never touches the developer's local DB. It builds a temporary subset data
folder, seeds an in-memory SQLite database, and verifies corrected brand behavior in
service-level responses.
"""

from __future__ import annotations

import csv
import html
import shutil
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = ROOT / "apps" / "backend"
if str(BACKEND_APP) not in sys.path:
    sys.path.insert(0, str(BACKEND_APP))

from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import make_engine  # noqa: E402
from app.schemas.recommendation import RecommendationRequest  # noqa: E402
from app.services.db_seed import seed_database  # noqa: E402
from app.services.product_detail_service import get_product_detail_response  # noqa: E402
from app.services.product_search_service import get_product_search_response  # noqa: E402
from app.services.recommendation_pipeline import create_recommendation_response  # noqa: E402
from app.services.search_index_builder import build_product_search_index_documents  # noqa: E402


TARGETS: dict[str, tuple[str, ...]] = {
    "Numbuzin": ("Numbuzin", "넘버즈인"),
    "111SKIN": ("111SKIN",),
    "Dr Dennis Gross": ("Dr Dennis Gross", "Dr. Dennis Gross", "Dr. Dennis Gross Skincare"),
    "Clé de Peau Beauté": ("Clé de Peau Beauté", "Cle de Peau Beaute", "Clé de Peau", "Cle de Peau"),
    "La Roche-Posay": ("La Roche-Posay", "La Roche Posay", "라로슈포제"),
}
QUERY_BY_TARGET = {
    "Numbuzin": "Numbuzin 진정 세럼 추천해줘",
    "111SKIN": "111SKIN 탄력 세럼 추천해줘",
    "Dr Dennis Gross": "Dr Dennis Gross 진정 세럼 추천해줘",
    "Clé de Peau Beauté": "Clé de Peau Beauté Brightening Serum 미백 세럼 추천해줘",
    "La Roche-Posay": "La Roche-Posay Lipikar 민감 보습 크림 추천해줘",
}
SEARCH_QUERY_BY_TARGET = {
    "Numbuzin": "Numbuzin",
    "111SKIN": "111SKIN",
    "Dr Dennis Gross": "Dr Dennis Gross",
    "Clé de Peau Beauté": "Clé de Peau Beauté Brightening Serum",
    "La Roche-Posay": "La Roche-Posay Lipikar",
}

SUMMARY_FIELDS = [
    "qa_area",
    "target_brand",
    "status",
    "checked_count",
    "issue_count",
    "note",
]
RESULT_FIELDS = [
    "qa_area",
    "target_brand",
    "query",
    "product_id",
    "brand",
    "name",
    "rank",
    "lowest_price",
    "image_count",
    "ingredient_count",
    "status",
    "note",
]


@dataclass(frozen=True)
class ProductRow:
    product_id: str
    brand: str
    name: str
    category: str
    is_recommendable: bool


def main() -> None:
    data_dir = ROOT / "data"
    output_dir = data_dir / "reconciliation"
    output_dir.mkdir(parents=True, exist_ok=True)

    products = read_products(data_dir)
    corrections = read_corrections(output_dir / "brand_corrections_recommendable.csv")
    corrected_products = apply_corrections(products, corrections)
    selected_ids = select_qa_product_ids(corrected_products, corrections)

    summary_rows: list[dict[str, str]] = []
    result_rows: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="brand-live-qa-", dir=ROOT) as tmp_name:
        tmp_data_dir = Path(tmp_name) / "data"
        build_subset_data_dir(data_dir, tmp_data_dir, selected_ids, corrections)

        engine = make_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            seed_result = seed_database(session, tmp_data_dir)
            build_product_search_index_documents(session)
            session.commit()

            summary_rows.append(
                {
                    "qa_area": "seed",
                    "target_brand": "ALL",
                    "status": "pass",
                    "checked_count": str(seed_result.products),
                    "issue_count": "0",
                    "note": f"임시 SQLite DB에 QA subset seed 완료. products={seed_result.products}",
                }
            )

            run_brand_search_qa(session, summary_rows, result_rows)
            run_recommendation_qa(session, summary_rows, result_rows)
            run_detail_qa(session, summary_rows, result_rows)

        engine.dispose()

    write_csv(output_dir / "brand_live_recommendation_qa_summary.csv", SUMMARY_FIELDS, summary_rows)
    write_csv(output_dir / "brand_live_recommendation_qa_results.csv", RESULT_FIELDS, result_rows)
    write_html(output_dir / "brand_live_recommendation_qa_report.html", summary_rows, result_rows)

    failed_sections = sum(1 for row in summary_rows if row["status"] == "fail")
    issue_count = sum(int(row["issue_count"] or 0) for row in summary_rows)
    print(
        "BrandLiveRecommendationQa("
        f"summary_rows={len(summary_rows)}, result_rows={len(result_rows)}, "
        f"issues={issue_count}, failed_sections={failed_sections})"
    )


def run_brand_search_qa(session: Session, summary_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> None:
    for target, aliases in TARGETS.items():
        query = SEARCH_QUERY_BY_TARGET[target]
        alias_keys = normalized_aliases(aliases)
        response = get_product_search_response(
            session,
            query=query,
            page=1,
            page_size=20,
            enable_elasticsearch=False,
            enable_pgvector=False,
        )
        issues = []
        for item in response.items:
            ok = normalize(item.brand) in alias_keys
            status = "pass" if ok else "fail"
            if not ok:
                issues.append(item.product_id)
            result_rows.append(
                {
                    "qa_area": "brand_search",
                    "target_brand": target,
                    "query": query,
                    "product_id": item.product_id,
                    "brand": item.brand,
                    "name": item.name,
                    "rank": "",
                    "lowest_price": str(item.lowest_price),
                    "image_count": "",
                    "ingredient_count": "",
                    "status": status,
                    "note": "브랜드 검색 결과 브랜드 일치 확인",
                }
            )
        if not response.items:
            result_rows.append(
                {
                    "qa_area": "brand_search",
                    "target_brand": target,
                    "query": query,
                    "product_id": "",
                    "brand": "",
                    "name": "",
                    "rank": "",
                    "lowest_price": "",
                    "image_count": "",
                    "ingredient_count": "",
                    "status": "fail",
                    "note": "검색 결과 0개",
                }
            )
        summary_rows.append(
            {
                "qa_area": "brand_search",
                "target_brand": target,
                "status": "pass" if response.items and not issues else "fail",
                "checked_count": str(len(response.items)),
                "issue_count": str(len(issues) if response.items else 1),
                "note": "실제 product_search_service database fallback 결과 확인",
            }
        )


def run_recommendation_qa(session: Session, summary_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> None:
    for target, aliases in TARGETS.items():
        query = QUERY_BY_TARGET[target]
        alias_keys = normalized_aliases(aliases)
        response = create_recommendation_response(
            session,
            RecommendationRequest(
                concern_text=query,
                skin_type="건성",
                sensitivity="민감",
                avoid_ingredients=[],
            ),
            result_limit=10,
            candidate_pool_limit=50,
            page=1,
            page_size=10,
            commit=False,
        )
        issues = []
        for product in response.products:
            ok = normalize(product.brand) in alias_keys
            status = "pass" if ok else "fail"
            if not ok:
                issues.append(product.product_id)
            result_rows.append(
                {
                    "qa_area": "recommendation_result",
                    "target_brand": target,
                    "query": query,
                    "product_id": product.product_id,
                    "brand": product.brand,
                    "name": product.name,
                    "rank": str(product.rank),
                    "lowest_price": str(product.lowest_price),
                    "image_count": "",
                    "ingredient_count": "",
                    "status": status,
                    "note": "실제 추천 응답 브랜드 일치 확인",
                }
            )
        if not response.products:
            result_rows.append(
                {
                    "qa_area": "recommendation_result",
                    "target_brand": target,
                    "query": query,
                    "product_id": "",
                    "brand": "",
                    "name": "",
                    "rank": "",
                    "lowest_price": "",
                    "image_count": "",
                    "ingredient_count": "",
                    "status": "fail",
                    "note": "추천 결과 0개",
                }
            )
        matched_brand_names = [brand.name for brand in response.summary.purchase_constraints.brands]
        no_brand_constraint = not response.summary.purchase_constraints.brands
        if no_brand_constraint:
            issues.append("no_brand_constraint")
        summary_rows.append(
            {
                "qa_area": "recommendation_result",
                "target_brand": target,
                "status": "pass" if response.products and not issues else "fail",
                "checked_count": str(len(response.products)),
                "issue_count": str(len(issues) if response.products else max(1, len(issues))),
                "note": "실제 recommendation_pipeline 응답 확인. matched_brands=" + "; ".join(matched_brand_names),
            }
        )


def run_detail_qa(session: Session, summary_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> None:
    checked = 0
    issues = 0
    seen: set[str] = set()
    recommendation_products = [
        row for row in result_rows
        if row["qa_area"] == "recommendation_result" and row["status"] == "pass"
    ]
    for row in recommendation_products:
        product_id = row["product_id"]
        if product_id in seen:
            continue
        seen.add(product_id)
        detail = get_product_detail_response(session, product_id)
        checked += 1
        image_count = len(detail.images)
        ingredient_count = len(detail.ingredients)
        ok = bool(detail.product.brand) and image_count > 0 and detail.product.lowest_price > 0 and ingredient_count > 0
        if not ok:
            issues += 1
        result_rows.append(
            {
                "qa_area": "product_detail",
                "target_brand": detail.product.brand,
                "query": "",
                "product_id": detail.product.product_id,
                "brand": detail.product.brand,
                "name": detail.product.name,
                "rank": "",
                "lowest_price": str(detail.product.lowest_price),
                "image_count": str(image_count),
                "ingredient_count": str(ingredient_count),
                "status": "pass" if ok else "fail",
                "note": "실제 product_detail_service 응답의 브랜드/이미지/가격/성분 연결 확인",
            }
        )
    summary_rows.append(
        {
            "qa_area": "product_detail",
            "target_brand": "recommendation_products",
            "status": "pass" if checked and issues == 0 else "fail",
            "checked_count": str(checked),
            "issue_count": str(issues if checked else 1),
            "note": "추천 결과 상품 상세 응답 확인",
        }
    )


def read_products(data_dir: Path) -> list[ProductRow]:
    rows = []
    for row in iter_csv_rows(data_dir, "products.csv"):
        rows.append(
            ProductRow(
                product_id=row["product_id"].strip(),
                brand=row["brand"].strip(),
                name=row["name"].strip(),
                category=row["category"].strip(),
                is_recommendable=(row.get("is_recommendable") or "").strip().lower() == "true",
            )
        )
    return rows


def read_corrections(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return {row["product_code"]: row for row in csv.DictReader(csv_file)}


def apply_corrections(products: list[ProductRow], corrections: dict[str, dict[str, str]]) -> list[ProductRow]:
    corrected = []
    for product in products:
        correction = corrections.get(product.product_id)
        if correction:
            corrected.append(
                ProductRow(
                    product_id=product.product_id,
                    brand=correction["corrected_brand"],
                    name=product.name,
                    category=product.category,
                    is_recommendable=product.is_recommendable,
                )
            )
        else:
            corrected.append(product)
    return corrected


def select_qa_product_ids(products: list[ProductRow], corrections: dict[str, dict[str, str]]) -> set[str]:
    selected = set(corrections)
    target_keys = {target: normalized_aliases(aliases) for target, aliases in TARGETS.items()}
    for target, keys in target_keys.items():
        target_products = [
            product for product in products
            if product.is_recommendable and (normalize(product.brand) in keys or starts_with_alias(product.name, keys))
        ]
        for product in target_products[:80]:
            selected.add(product.product_id)
    return selected


def build_subset_data_dir(source_dir: Path, output_dir: Path, selected_ids: set[str], corrections: dict[str, dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_static_files(source_dir, output_dir)
    write_filtered_csv(source_dir, output_dir, "products.csv", lambda row: row.get("product_id") in selected_ids)
    write_filtered_csv(source_dir, output_dir, "product_prices.csv", lambda row: row.get("product_id") in selected_ids)
    write_filtered_csv(source_dir, output_dir, "product_image_assets.csv", lambda row: row.get("product_id") in selected_ids)
    write_filtered_csv(source_dir, output_dir, "product_inventory.csv", lambda row: row.get("product_id") in selected_ids)
    write_filtered_csv(source_dir, output_dir, "product_market_signals.csv", lambda row: row.get("product_id") in selected_ids)
    write_filtered_csv(source_dir, output_dir, "product_skin_profiles.csv", lambda row: row.get("product_id") in selected_ids)

    selected_ingredient_ids = write_product_ingredients_subset(source_dir, output_dir, selected_ids)
    write_master_subset(source_dir, output_dir, selected_ingredient_ids)
    write_vector_docs_subset(source_dir, output_dir, selected_ids, selected_ingredient_ids)
    write_corrections_subset(output_dir, corrections, selected_ids)


def copy_static_files(source_dir: Path, output_dir: Path) -> None:
    for name in ("tags.json", "concern_to_effect.json"):
        shutil.copy2(source_dir / name, output_dir / name)


def write_product_ingredients_subset(source_dir: Path, output_dir: Path, selected_ids: set[str]) -> set[str]:
    ingredient_ids: set[str] = set()
    rows = []
    fieldnames = None
    for path in csv_paths(source_dir, "product_ingredients.csv"):
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = fieldnames or list(reader.fieldnames or [])
            for row in reader:
                if row.get("product_id") in selected_ids:
                    rows.append(row)
                    if row.get("ingredient_id"):
                        ingredient_ids.add(row["ingredient_id"])
    write_rows(output_dir / "product_ingredients.csv", fieldnames or [], rows)
    return ingredient_ids


def write_master_subset(source_dir: Path, output_dir: Path, ingredient_ids: set[str]) -> None:
    write_filtered_csv(source_dir, output_dir, "ingredients.csv", lambda row: row.get("ingredient_id") in ingredient_ids)
    write_filtered_csv(source_dir, output_dir, "ingredient_aliases.csv", lambda row: row.get("canonical_id") in ingredient_ids)
    write_filtered_csv(source_dir, output_dir, "ingredient_effect.csv", lambda row: row.get("ingredient_id") in ingredient_ids)
    write_filtered_csv(source_dir, output_dir, "ingredient_effect_ranges.csv", lambda row: row.get("ingredient_id") in ingredient_ids)
    write_filtered_csv(source_dir, output_dir, "ingredient_evidence.csv", lambda row: row.get("ingredient_id") in ingredient_ids)
    write_filtered_csv(source_dir, output_dir, "risk_flags.csv", lambda row: row.get("ingredient_id") in ingredient_ids)


def write_vector_docs_subset(source_dir: Path, output_dir: Path, product_ids: set[str], ingredient_ids: set[str]) -> None:
    def include(row: dict[str, str]) -> bool:
        source_type = row.get("source_type")
        source_id = row.get("source_id", "")
        if source_type == "product":
            return source_id in product_ids
        if source_type == "ingredient":
            return source_id in ingredient_ids
        if source_type in {"evidence", "ingredient_evidence"}:
            ingredient_id = source_id.partition(":")[0]
            return ingredient_id in ingredient_ids
        return False

    write_filtered_csv(source_dir, output_dir, "vector_docs.csv", include)


def write_corrections_subset(output_dir: Path, corrections: dict[str, dict[str, str]], selected_ids: set[str]) -> None:
    rows = [row for product_id, row in corrections.items() if product_id in selected_ids]
    reconciliation_dir = output_dir / "reconciliation"
    reconciliation_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "product_code",
        "source_prefix",
        "current_brand",
        "corrected_brand",
        "product_name",
        "confidence",
        "basis",
        "note",
    ]
    write_rows(reconciliation_dir / "brand_corrections_recommendable.csv", fieldnames, rows)


def write_filtered_csv(source_dir: Path, output_dir: Path, csv_name: str, predicate) -> None:
    paths = csv_paths(source_dir, csv_name)
    rows = []
    fieldnames = None
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = fieldnames or list(reader.fieldnames or [])
            rows.extend(row for row in reader if predicate(row))
    write_rows(output_dir / csv_name, fieldnames or [], rows)


def iter_csv_rows(data_dir: Path, csv_name: str) -> Iterable[dict[str, str]]:
    for path in csv_paths(data_dir, csv_name):
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            yield from csv.DictReader(csv_file)


def csv_paths(data_dir: Path, csv_name: str) -> list[Path]:
    direct = data_dir / csv_name
    split_dir = data_dir / csv_name.removesuffix(".csv")
    if direct.exists():
        return [direct]
    if split_dir.exists():
        return sorted(split_dir.glob("*.csv"))
    return []


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalized_aliases(aliases: tuple[str, ...]) -> set[str]:
    return {normalize(alias) for alias in aliases if normalize(alias)}


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in value if ch.isalnum())


def starts_with_alias(value: str, aliases: set[str]) -> bool:
    key = normalize(value)
    return any(alias and key.startswith(alias) for alias in aliases)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    write_rows(path, fieldnames, rows)


def write_html(path: Path, summary_rows: list[dict[str, str]], result_rows: list[dict[str, str]]) -> None:
    path.write_text(
        """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<title>브랜드 실제 추천 QA</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 28px; background: #f7f4ed; color: #1f2a22; }
section { background: #fffdf8; border: 1px solid #ded7c9; border-radius: 12px; padding: 18px; margin: 16px 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #ece5d8; padding: 8px; text-align: left; vertical-align: top; }
th { background: #efe7d7; position: sticky; top: 0; }
.pass { color: #1f6b44; font-weight: 700; }
.fail { color: #b32929; font-weight: 700; }
.scroll { max-height: 620px; overflow: auto; border: 1px solid #ece5d8; border-radius: 8px; }
</style>
</head>
<body>
<h1>브랜드 실제 추천 QA</h1>
<p>임시 SQLite DB에 subset 데이터를 seed한 뒤 상품 검색, 추천 응답, 상품 상세 응답을 검증했습니다.</p>
<section><h2>요약</h2>__SUMMARY__</section>
<section><h2>상세 결과</h2><div class="scroll">__RESULTS__</div></section>
</body>
</html>
""".replace("__SUMMARY__", html_table(summary_rows)).replace("__RESULTS__", html_table(result_rows)),
        encoding="utf-8",
    )


def html_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<p>표시할 행이 없습니다.</p>"
    fields = list(rows[0].keys())
    header = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        cells = []
        for field in fields:
            value = str(row.get(field, ""))
            css = ' class="pass"' if field == "status" and value == "pass" else (' class="fail"' if field == "status" and value == "fail" else "")
            cells.append(f"<td{css}>{html.escape(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return "<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"


if __name__ == "__main__":
    main()

