from __future__ import annotations

import csv
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import home_market_popularity as market


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RECON_DIR = DATA_DIR / "reconciliation"
COVERAGE_PATH = RECON_DIR / "concentration_coverage_estimates.csv"
ALL_OUT = RECON_DIR / "home_cold_start_candidates.csv"
P2_OUT = RECON_DIR / "home_cold_start_p2_candidates.csv"


SECTION_CONFIGS = [
    {
        "section_id": "moisture_barrier",
        "section_label": "보습·장벽 예시",
        "effect_id": "effect_moisture_barrier",
        "effect_name": "보습·장벽",
        "required": ("수분", "보습", "장벽", "베리어", "히알루", "모이스", "아쿠아", "하이드라", "워터", "판테놀"),
        "excluded": ("미백", "화이트", "잡티", "기미", "흔적", "톤업", "브라이트", "글루타", "txa", "티엑스", "레티", "탄력", "주름", "여드름", "트러블", "각질", "필링", "시카", "진정", "수딩", "카밍", "센텔라"),
    },
    {
        "section_id": "calming",
        "section_label": "진정 예시",
        "effect_id": "effect_calming",
        "effect_name": "진정",
        "required": ("진정", "수딩", "시카", "카밍", "병풀", "센텔라", "티트리", "레드", "붉은", "어성초"),
        "excluded": ("미백", "화이트", "잡티", "기미", "톤업", "브라이트", "글루타", "txa", "티엑스", "각질", "필링", "레티", "주름", "탄력", "여드름", "트러블"),
    },
    {
        "section_id": "brightening",
        "section_label": "미백·톤 예시",
        "effect_id": "effect_brightening",
        "effect_name": "미백·톤",
        "required": ("미백", "화이트", "잡티", "기미", "흔적", "톤", "브라이트", "글루타", "txa", "티엑스", "트라넥", "나이아신", "비타"),
        "excluded": ("각질", "필링", "레티", "여드름", "트러블", "시카", "진정", "수딩", "카밍"),
    },
    {
        "section_id": "acne_sebum",
        "section_label": "여드름·피지 예시",
        "effect_id": "effect_acne_sebum",
        "effect_name": "여드름·피지",
        "required": ("피지", "모공", "여드름", "트러블", "ac", "아크네", "bha", "살리실", "티트리", "징크"),
        "excluded": ("미백", "잡티", "주름", "탄력", "톤업"),
    },
    {
        "section_id": "wrinkle",
        "section_label": "주름·탄력 예시",
        "effect_id": "effect_wrinkle",
        "effect_name": "주름·탄력",
        "required": ("주름", "탄력", "레티", "리프팅", "안티에이징", "아데노신", "콜라겐"),
        "excluded": ("미백", "잡티", "기미", "톤업", "트러블", "여드름", "각질", "필링"),
    },
    {
        "section_id": "exfoliation",
        "section_label": "각질 예시",
        "effect_id": "effect_exfoliation",
        "effect_name": "각질",
        "required": ("각질", "필링", "aha", "bha", "pha", "살리실", "락틱", "글라이콜", "토너패드"),
        "excluded": ("레티", "주름", "탄력", "미백", "잡티", "톤업"),
    },
]


P2_SECTION_IDS = {"moisture_barrier", "calming", "brightening"}
HOME_SECTION_LIMIT = 15
ALL_SECTION_LIMIT = 15
MARKET_POPULAR_SECTION = {
    "section_id": "market_popular",
    "section_label": "지금 인기 있는 제품",
    "effect_id": "",
    "effect_name": "시장 인기",
}

BRIGHTENING_ANCHORS = {"tranexamic_acid", "arbutin", "glutathione", "bisabolol", "ascorbic_acid", "licorice_extract", "kojic_acid"}
ACNE_ANCHORS = {"salicylic_acid_bha", "zinc_pca", "tea_tree", "phytosphingosine"}
EXFOLIATION_ANCHORS = {"salicylic_acid_bha", "aha", "pha", "urea"}
WRINKLE_ANCHORS = {"retinol", "retinal", "adenosine", "peptides"}
GENERIC_INGREDIENTS = {"glycerin"}

COVERAGE_BONUS = {
    "exact": 14.0,
    "range": 10.0,
    "regulatory_anchor": 8.0,
    "legal_upper_bound": 1.5,
    "lower_bound": 0.5,
    "marker_upper_bound": 0.5,
    "prior_estimate": 0.0,
}

COVERAGE_PRIORITY = {
    "exact": 100,
    "range": 90,
    "regulatory_anchor": 80,
    "legal_upper_bound": 70,
    "lower_bound": 60,
    "marker_upper_bound": 50,
    "prior_estimate": 10,
}

OUTPUT_FIELDS = [
    "section_id",
    "section_label",
    "effect_id",
    "effect_name",
    "rank",
    "product_id",
    "brand",
    "name",
    "category",
    "price",
    "home_example_score",
    "axis_score",
    "coverage_score",
    "market_popularity_score",
    "review_count_score",
    "rating_score",
    "sales_score",
    "recent_signal_score",
    "coverage_types",
    "risk_penalty",
    "matched_ingredients",
    "coverage_basis",
    "reason_summary",
    "thumbnail_url",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(value: str) -> str:
    return (value or "").lower().replace(" ", "")


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_true(value: str) -> bool:
    return (value or "").strip().lower() == "true"


def split_values(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def ensure_coverage_file() -> None:
    if COVERAGE_PATH.exists():
        return
    subprocess.run(
        [sys.executable, str(DATA_DIR / "scripts" / "build_concentration_coverage_estimates.py")],
        cwd=ROOT,
        check=True,
    )


def load_lowest_prices() -> dict[str, int]:
    prices: dict[str, int] = {}
    for row in read_csv(DATA_DIR / "product_prices.csv"):
        if row.get("is_lowest", "").lower() != "true" and row["product_id"] in prices:
            continue
        price = to_int(row.get("price", ""))
        if price:
            prices[row["product_id"]] = price
    return prices


def load_ingredients_by_product() -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(DATA_DIR / "product_ingredients.csv"):
        grouped[row["product_id"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: to_int(row.get("display_order", ""), 9999))
    return grouped


def load_effects() -> dict[str, dict[str, dict[str, str]]]:
    effects: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in read_csv(DATA_DIR / "ingredient_effect.csv"):
        effects[row["ingredient_id"]][row["effect_id"]] = row
    return effects


def load_ranges() -> dict[tuple[str, str], dict[str, str]]:
    return {
        (row["ingredient_id"], row["effect_id"]): row
        for row in read_csv(DATA_DIR / "ingredient_effect_ranges.csv")
    }


def load_coverage() -> dict[tuple[str, str], dict[str, str]]:
    ensure_coverage_file()
    coverage: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv(COVERAGE_PATH):
        key = (row["product_id"], row["ingredient_id"])
        existing = coverage.get(key)
        if existing is None or COVERAGE_PRIORITY.get(row["concentration_type"], 0) > COVERAGE_PRIORITY.get(existing["concentration_type"], 0):
            coverage[key] = row
    return coverage


def load_risk_scores() -> dict[str, float]:
    return {
        row["ingredient_id"]: to_float(row.get("severity_score", ""), 0.0)
        for row in read_csv(DATA_DIR / "risk_flags.csv")
    }


def product_is_eligible(
    product: dict[str, str],
    prices: dict[str, int],
    ingredients_by_product: dict[str, list[dict[str, str]]],
) -> bool:
    product_id = product["product_id"]
    return (
        is_true(product.get("is_recommendable", ""))
        and product_id in prices
        and bool((product.get("thumbnail_url") or "").strip())
        and bool(ingredients_by_product.get(product_id))
    )


def position_matches(product: dict[str, str], section: dict[str, object]) -> bool:
    text = normalize_text(product.get("name", ""))
    if any(normalize_text(token) in text for token in section["excluded"]):
        return False
    return any(normalize_text(token) in text for token in section["required"])


def ingredient_allowed(
    ingredient_id: str,
    effect_id: str,
    product_ingredient_ids: set[str],
) -> bool:
    if ingredient_id in GENERIC_INGREDIENTS:
        return False
    if ingredient_id == "niacinamide" and effect_id != "effect_brightening":
        return False
    if effect_id == "effect_brightening" and ingredient_id == "niacinamide":
        return bool(product_ingredient_ids & BRIGHTENING_ANCHORS)
    if effect_id == "effect_acne_sebum":
        return ingredient_id in ACNE_ANCHORS
    if effect_id == "effect_exfoliation":
        return ingredient_id in EXFOLIATION_ANCHORS
    if effect_id == "effect_wrinkle":
        return ingredient_id in WRINKLE_ANCHORS
    return True


def position_weight(display_order: int) -> float:
    if display_order <= 5:
        return 1.0
    if display_order <= 15:
        return 0.85
    if display_order <= 30:
        return 0.7
    return 0.55


def ingredient_weight(ingredient_id: str) -> float:
    if ingredient_id == "panthenol":
        return 0.78
    if ingredient_id == "niacinamide":
        return 0.62
    return 1.0


def price_score(price: int) -> float:
    if 8_000 <= price <= 35_000:
        return 12.0
    if 5_000 <= price <= 50_000:
        return 7.0
    return 2.0


def fit_bonus(
    coverage_row: dict[str, str] | None,
    range_row: dict[str, str] | None,
) -> float:
    if not coverage_row or coverage_row.get("concentration_type") != "exact" or not range_row:
        return 0.0
    value = to_float(coverage_row.get("value_min", "nan"), math.nan)
    meaningful = to_float(range_row.get("meaningful_min", "nan"), math.nan)
    optimal_min = to_float(range_row.get("optimal_min", "nan"), math.nan)
    optimal_max = to_float(range_row.get("optimal_max", "nan"), math.nan)
    excessive = to_float(range_row.get("excessive_min", "nan"), math.nan)
    if math.isnan(value) or math.isnan(meaningful) or math.isnan(optimal_min) or math.isnan(optimal_max):
        return 0.0
    if not math.isnan(excessive) and value >= excessive:
        return -8.0
    if value < meaningful:
        return -3.0
    if value < optimal_min:
        return 4.0
    if value <= optimal_max:
        return 8.0
    return 3.0


def score_product_for_section(
    product: dict[str, str],
    section: dict[str, object],
    ingredients: list[dict[str, str]],
    effects: dict[str, dict[str, dict[str, str]]],
    ranges: dict[tuple[str, str], dict[str, str]],
    coverage: dict[tuple[str, str], dict[str, str]],
    risk_scores: dict[str, float],
    price: int,
) -> dict[str, object] | None:
    effect_id = str(section["effect_id"])
    product_ingredient_ids = {row["ingredient_id"] for row in ingredients}
    contributions: list[dict[str, object]] = []
    seen_ingredients: set[str] = set()

    for ingredient in ingredients:
        ingredient_id = ingredient["ingredient_id"]
        if ingredient_id in seen_ingredients:
            continue
        seen_ingredients.add(ingredient_id)
        effect_row = effects.get(ingredient_id, {}).get(effect_id)
        if not effect_row:
            continue
        if not ingredient_allowed(ingredient_id, effect_id, product_ingredient_ids):
            continue
        display_order = to_int(ingredient.get("display_order", ""), 9999)
        base = to_float(effect_row.get("effect_score", "0"))
        coverage_row = coverage.get((product["product_id"], ingredient_id))
        range_row = ranges.get((ingredient_id, effect_id))
        ctype = coverage_row["concentration_type"] if coverage_row else ""
        coverage_bonus = COVERAGE_BONUS.get(ctype, 0.0) + fit_bonus(coverage_row, range_row)
        axis = base * position_weight(display_order) * ingredient_weight(ingredient_id)
        contributions.append(
            {
                "ingredient_id": ingredient_id,
                "ingredient_name": ingredient["ingredient_name"],
                "axis": axis,
                "coverage_bonus": coverage_bonus,
                "coverage_type": ctype,
                "coverage_basis": coverage_row.get("basis", "") if coverage_row else "",
                "display_order": display_order,
            }
        )

    if not contributions:
        return None

    contributions.sort(
        key=lambda item: (
            -(float(item["axis"]) + float(item["coverage_bonus"])),
            int(item["display_order"]),
            str(item["ingredient_id"]),
        )
    )
    top = contributions[:4]
    axis_score = sum(float(item["axis"]) for item in top)
    coverage_score = sum(float(item["coverage_bonus"]) for item in top)
    risk_penalty = 5.0 * sum(risk_scores[ingredient_id] for ingredient_id in product_ingredient_ids & set(risk_scores))
    final_score = axis_score + coverage_score + price_score(price) - risk_penalty

    return {
        "home_example_score": round(final_score, 2),
        "axis_score": round(axis_score, 2),
        "coverage_score": round(coverage_score, 2),
        "risk_penalty": round(risk_penalty, 2),
        "matched_ingredients": "; ".join(item["ingredient_name"] for item in top),
        "coverage_types": "; ".join(
            f"{item['ingredient_name']}={item['coverage_type'] or 'none'}"
            for item in top
        ),
        "coverage_basis": " | ".join(
            f"{item['ingredient_name']}: {item['coverage_basis']}"
            for item in top
            if item["coverage_basis"]
        ),
        "reason_summary": f"{section['effect_name']} 축 성분 근거와 함량 coverage 정보를 함께 봤어요.",
    }


def select_section_rows(
    section: dict[str, object],
    products: list[dict[str, str]],
    ingredients_by_product: dict[str, list[dict[str, str]]],
    effects: dict[str, dict[str, dict[str, str]]],
    ranges: dict[tuple[str, str], dict[str, str]],
    coverage: dict[tuple[str, str], dict[str, str]],
    risk_scores: dict[str, float],
    prices: dict[str, int],
    *,
    used_product_ids: set[str] | None = None,
    limit: int = 5,
) -> list[dict[str, str]]:
    scored: list[dict[str, object]] = []
    for product in products:
        product_id = product["product_id"]
        if used_product_ids is not None and product_id in used_product_ids:
            continue
        if not position_matches(product, section):
            continue
        score = score_product_for_section(
            product,
            section,
            ingredients_by_product[product_id],
            effects,
            ranges,
            coverage,
            risk_scores,
            prices[product_id],
        )
        if score is None:
            continue
        scored.append({**product, **score})

    scored.sort(
        key=lambda item: (
            -float(item["home_example_score"]),
            -float(item["axis_score"]),
            -float(item["coverage_score"]),
            float(item["risk_penalty"]),
            prices[str(item["product_id"])],
            str(item["category"]),
            str(item["brand"]),
            str(item["product_id"]),
        )
    )
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    brand_count: Counter[str] = Counter()
    category_count: Counter[str] = Counter()
    for item in scored:
        if brand_count[item["brand"]] >= 1:
            continue
        if category_count[item["category"]] >= 2:
            continue
        selected.append(item)
        selected_ids.add(str(item["product_id"]))
        brand_count[item["brand"]] += 1
        category_count[item["category"]] += 1
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for item in scored:
            product_id = str(item["product_id"])
            if product_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(product_id)
            if len(selected) >= limit:
                break

    rows: list[dict[str, str]] = []
    for item in selected:
        rank = len(rows) + 1
        rows.append(
            {
                "section_id": str(section["section_id"]),
                "section_label": str(section["section_label"]),
                "effect_id": str(section["effect_id"]),
                "effect_name": str(section["effect_name"]),
                "rank": str(rank),
                "product_id": str(item["product_id"]),
                "brand": str(item["brand"]),
                "name": str(item["name"]),
                "category": str(item["category"]),
                "price": str(prices[str(item["product_id"])]),
                "home_example_score": str(item["home_example_score"]),
                "axis_score": str(item["axis_score"]),
                "coverage_score": str(item["coverage_score"]),
                "coverage_types": str(item["coverage_types"]),
                "risk_penalty": str(item["risk_penalty"]),
                "matched_ingredients": str(item["matched_ingredients"]),
                "coverage_basis": str(item["coverage_basis"]),
                "reason_summary": str(item["reason_summary"]),
                "thumbnail_url": str(item["thumbnail_url"]),
            }
        )
        if used_product_ids is not None:
            used_product_ids.add(str(item["product_id"]))
        if len(rows) >= limit:
            break
    return rows


def select_market_popular_rows(
    products: list[dict[str, str]],
    prices: dict[str, int],
    market_context: market.MarketPopularityContext,
    *,
    used_product_ids: set[str] | None = None,
    limit: int = 5,
) -> list[dict[str, str]]:
    if not market_context.available:
        return []

    scored: list[dict[str, object]] = []
    for product in products:
        product_id = product["product_id"]
        if used_product_ids is not None and product_id in used_product_ids:
            continue
        popularity = market.score_market_popularity(product_id, market_context)
        if popularity is None or popularity.total <= 0:
            continue
        scored.append(
            {
                **product,
                "market_popularity_score": popularity.total,
                "review_count_score": popularity.review_count_score,
                "rating_score": popularity.rating_score,
                "sales_score": popularity.sales_score,
                "recent_signal_score": popularity.recent_signal_score,
            }
        )

    scored.sort(
        key=lambda item: (
            -float(item["market_popularity_score"]),
            -float(item["sales_score"]),
            -float(item["review_count_score"]),
            -float(item["rating_score"]),
            prices[str(item["product_id"])],
            str(item["category"]),
            str(item["brand"]),
            str(item["product_id"]),
        )
    )

    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    brand_count: Counter[str] = Counter()
    category_count: Counter[str] = Counter()
    for item in scored:
        if brand_count[str(item["brand"])] >= 1:
            continue
        if category_count[str(item["category"])] >= 2:
            continue
        selected.append(item)
        selected_ids.add(str(item["product_id"]))
        brand_count[str(item["brand"])] += 1
        category_count[str(item["category"])] += 1
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for item in scored:
            product_id = str(item["product_id"])
            if product_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(product_id)
            if len(selected) >= limit:
                break

    rows: list[dict[str, str]] = []
    for item in selected:
        rank = len(rows) + 1
        rows.append(
            {
                "section_id": str(MARKET_POPULAR_SECTION["section_id"]),
                "section_label": str(MARKET_POPULAR_SECTION["section_label"]),
                "effect_id": "",
                "effect_name": str(MARKET_POPULAR_SECTION["effect_name"]),
                "rank": str(rank),
                "product_id": str(item["product_id"]),
                "brand": str(item["brand"]),
                "name": str(item["name"]),
                "category": str(item["category"]),
                "price": str(prices[str(item["product_id"])]),
                "home_example_score": str(item["market_popularity_score"]),
                "axis_score": "",
                "coverage_score": "",
                "market_popularity_score": str(item["market_popularity_score"]),
                "review_count_score": str(item["review_count_score"]),
                "rating_score": str(item["rating_score"]),
                "sales_score": str(item["sales_score"]),
                "recent_signal_score": str(item["recent_signal_score"]),
                "coverage_types": "",
                "risk_penalty": "",
                "matched_ingredients": "",
                "coverage_basis": "",
                "reason_summary": "리뷰, 평점, 판매 신호를 함께 본 인기 후보예요.",
                "thumbnail_url": str(item["thumbnail_url"]),
            }
        )
        if used_product_ids is not None:
            used_product_ids.add(str(item["product_id"]))
        if len(rows) >= limit:
            break
    return rows


def build() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    products = read_csv(DATA_DIR / "products.csv")
    prices = load_lowest_prices()
    ingredients_by_product = load_ingredients_by_product()
    effects = load_effects()
    ranges = load_ranges()
    coverage = load_coverage()
    risk_scores = load_risk_scores()
    market_context = market.load_market_popularity_context(DATA_DIR)

    eligible = [
        product
        for product in products
        if product_is_eligible(product, prices, ingredients_by_product)
    ]

    all_rows: list[dict[str, str]] = []
    all_rows.extend(select_market_popular_rows(eligible, prices, market_context, limit=ALL_SECTION_LIMIT))
    for section in SECTION_CONFIGS:
        all_rows.extend(
            select_section_rows(
                section,
                eligible,
                ingredients_by_product,
                effects,
                ranges,
                coverage,
                risk_scores,
                prices,
                limit=ALL_SECTION_LIMIT,
            )
        )

    p2_rows: list[dict[str, str]] = []
    used_product_ids: set[str] = set()
    p2_rows.extend(
        select_market_popular_rows(
            eligible,
            prices,
            market_context,
            used_product_ids=used_product_ids,
            limit=HOME_SECTION_LIMIT,
        )
    )
    for section in SECTION_CONFIGS:
        if section["section_id"] not in P2_SECTION_IDS:
            continue
        p2_rows.extend(
            select_section_rows(
                section,
                eligible,
                ingredients_by_product,
                effects,
                ranges,
                coverage,
                risk_scores,
                prices,
                used_product_ids=used_product_ids,
                limit=HOME_SECTION_LIMIT,
            )
        )
    return all_rows, p2_rows


def main() -> None:
    all_rows, p2_rows = build()
    write_csv(ALL_OUT, all_rows)
    write_csv(P2_OUT, p2_rows)
    print(f"wrote {ALL_OUT} ({len(all_rows)} rows)")
    print(f"wrote {P2_OUT} ({len(p2_rows)} rows)")
    if any(row["section_id"] == MARKET_POPULAR_SECTION["section_id"] for row in p2_rows):
        print(MARKET_POPULAR_SECTION["section_id"], sum(1 for row in p2_rows if row["section_id"] == MARKET_POPULAR_SECTION["section_id"]))
    for section_id in P2_SECTION_IDS:
        print(section_id, sum(1 for row in p2_rows if row["section_id"] == section_id))


if __name__ == "__main__":
    main()
