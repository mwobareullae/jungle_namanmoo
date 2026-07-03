from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import build_home_cold_start_candidates as cold
import home_market_popularity as market


OUT = cold.RECON_DIR / "home_personalized_profile_candidates.csv"
P2_PRODUCT_ID_PREFIXES = ("prod_oy_",)

SKIN_TYPE_COLUMNS = {
    "건성": "dry_fit",
    "지성": "oily_fit",
    "복합성": "combination_fit",
    "중성": "normal_fit",
    "수부지": "dehydrated_oily_fit",
}

SCENARIOS = [
    {
        "scenario_id": "dry_sensitive_barrier",
        "scenario_label": "건성·민감 장벽 고민",
        "skin_type": "건성",
        "sensitivity": "민감",
        "primary_effect_id": "effect_moisture_barrier",
        "secondary_effect_id": "effect_calming",
        "avoid_ingredient_ids": "retinol;retinal;aha;salicylic_acid_bha;tea_tree",
    },
    {
        "scenario_id": "oily_acne_sebum",
        "scenario_label": "지성·피지 트러블 고민",
        "skin_type": "지성",
        "sensitivity": "보통",
        "primary_effect_id": "effect_acne_sebum",
        "secondary_effect_id": "effect_calming",
        "avoid_ingredient_ids": "",
    },
    {
        "scenario_id": "dehydrated_oily_brightening",
        "scenario_label": "수부지·잡티 고민",
        "skin_type": "수부지",
        "sensitivity": "보통",
        "primary_effect_id": "effect_brightening",
        "secondary_effect_id": "effect_moisture_barrier",
        "avoid_ingredient_ids": "",
    },
    {
        "scenario_id": "combination_sensitive_calming",
        "scenario_label": "복합성·민감 진정 고민",
        "skin_type": "복합성",
        "sensitivity": "민감",
        "primary_effect_id": "effect_calming",
        "secondary_effect_id": "effect_moisture_barrier",
        "avoid_ingredient_ids": "retinol;retinal;aha;salicylic_acid_bha;tea_tree",
    },
]

SECTION_BLUEPRINTS = [
    {
        "section_id": "profile_focus",
        "section_label": "내 피부 기준 추천",
        "mode": "primary",
    },
    {
        "section_id": "market_popular",
        "section_label": "지금 인기 있는 제품",
        "mode": "market",
    },
    {
        "section_id": "evidence_confident",
        "section_label": "근거가 뚜렷한 추천",
        "mode": "evidence",
    },
    {
        "section_id": "price_value",
        "section_label": "가격까지 좋은 추천",
        "mode": "price_value",
    },
]

OUTPUT_FIELDS = [
    "scenario_id",
    "scenario_label",
    "skin_type",
    "sensitivity",
    "section_id",
    "section_label",
    "source_effect_id",
    "source_effect_name",
    "rank",
    "product_id",
    "brand",
    "name",
    "category",
    "price",
    "personalized_home_score",
    "axis_score",
    "coverage_score",
    "profile_fit_score",
    "sensitivity_fit_score",
    "price_score",
    "market_popularity_score",
    "review_count_score",
    "rating_score",
    "sales_score",
    "recent_signal_score",
    "risk_penalty",
    "matched_ingredients",
    "coverage_types",
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


def load_skin_profiles() -> dict[str, dict[str, str]]:
    return {
        row["product_id"]: row
        for row in read_csv(cold.DATA_DIR / "product_skin_profiles.csv")
    }


def section_by_effect_id() -> dict[str, dict[str, object]]:
    return {
        str(section["effect_id"]): section
        for section in cold.SECTION_CONFIGS
    }


def split_ids(value: str) -> set[str]:
    return {part.strip() for part in (value or "").split(";") if part.strip()}


def profile_fit_score(
    profile: dict[str, str] | None,
    skin_type: str,
) -> float:
    if not profile:
        return 50.0
    column = SKIN_TYPE_COLUMNS.get(skin_type, "normal_fit")
    return round(100 * cold.to_float(profile.get(column, ""), 0.5), 2)


def sensitivity_fit_score(
    profile: dict[str, str] | None,
    sensitivity: str,
) -> float:
    if not profile:
        return 50.0
    sensitive_fit = cold.to_float(profile.get("sensitive_fit", ""), 0.5)
    if sensitivity == "민감":
        return round(100 * sensitive_fit, 2)
    return round(100 * (0.75 + sensitive_fit * 0.25), 2)


def price_score(price: int) -> float:
    if 8_000 <= price <= 35_000:
        return 100.0
    if 5_000 <= price <= 50_000:
        return 70.0
    if 0 < price <= 80_000:
        return 45.0
    return 25.0


def normalized_axis_score(value: float) -> float:
    return min(100.0, value / 160.0 * 100.0)


def normalized_coverage_score(value: float) -> float:
    return min(100.0, max(0.0, value) / 35.0 * 100.0)


def personalized_risk_penalty(
    product_ingredient_ids: set[str],
    risk_scores: dict[str, float],
    sensitivity: str,
) -> float:
    multiplier = 11.0 if sensitivity == "민감" else 5.0
    return round(multiplier * sum(risk_scores[ingredient_id] for ingredient_id in product_ingredient_ids & set(risk_scores)), 2)


def personalized_score(
    mode: str,
    axis: float,
    coverage: float,
    profile: float,
    sensitivity: float,
    price: float,
    risk_penalty: float,
) -> float:
    axis_unit = normalized_axis_score(axis)
    coverage_unit = normalized_coverage_score(coverage)
    if mode == "evidence":
        score = axis_unit * 0.35 + coverage_unit * 0.35 + profile * 0.15 + sensitivity * 0.05 + price * 0.10
    elif mode == "price_value":
        score = axis_unit * 0.30 + coverage_unit * 0.12 + profile * 0.20 + sensitivity * 0.08 + price * 0.30
    else:
        score = axis_unit * 0.45 + coverage_unit * 0.18 + profile * 0.25 + sensitivity * 0.05 + price * 0.07
    return round(max(0.0, score - risk_penalty), 2)


def source_section_for_blueprint(
    scenario: dict[str, str],
    blueprint: dict[str, str],
    sections: dict[str, dict[str, object]],
) -> dict[str, object]:
    if blueprint["mode"] == "market":
        return {
            "effect_id": "",
            "effect_name": "시장 인기",
        }
    if blueprint["mode"] == "price_value":
        return sections[scenario["secondary_effect_id"]]
    if blueprint["mode"] == "evidence":
        return sections[scenario["primary_effect_id"]]
    return sections[scenario["primary_effect_id"]]


def product_has_avoided_ingredient(
    ingredients: list[dict[str, str]],
    avoid_ingredient_ids: set[str],
) -> bool:
    if not avoid_ingredient_ids:
        return False
    return bool({row["ingredient_id"] for row in ingredients} & avoid_ingredient_ids)


def product_in_p2_scope(product: dict[str, str]) -> bool:
    product_id = product.get("product_id", "")
    return product_id.startswith(P2_PRODUCT_ID_PREFIXES)


def score_scenario_market_section(
    scenario: dict[str, str],
    blueprint: dict[str, str],
    products: list[dict[str, str]],
    ingredients_by_product: dict[str, list[dict[str, str]]],
    prices: dict[str, int],
    skin_profiles: dict[str, dict[str, str]],
    market_context: market.MarketPopularityContext,
    used_product_ids: set[str],
    limit: int = 5,
) -> list[dict[str, str]]:
    if not market_context.available:
        return []

    avoid_ingredient_ids = split_ids(scenario.get("avoid_ingredient_ids", ""))
    scored: list[dict[str, object]] = []
    for product in products:
        product_id = product["product_id"]
        if product_id in used_product_ids:
            continue
        ingredients = ingredients_by_product[product_id]
        if product_has_avoided_ingredient(ingredients, avoid_ingredient_ids):
            continue
        popularity = market.score_market_popularity(product_id, market_context)
        if popularity is None or popularity.total <= 0:
            continue
        profile = profile_fit_score(skin_profiles.get(product_id), scenario["skin_type"])
        sensitivity = sensitivity_fit_score(skin_profiles.get(product_id), scenario["sensitivity"])
        scored.append(
            {
                **product,
                "profile_fit_score": profile,
                "sensitivity_fit_score": sensitivity,
                "price_score": price_score(prices[product_id]),
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
            -float(item["profile_fit_score"]),
            prices[str(item["product_id"])],
            str(item["category"]),
            str(item["brand"]),
            str(item["product_id"]),
        )
    )

    rows: list[dict[str, str]] = []
    brand_count: Counter[str] = Counter()
    category_count: Counter[str] = Counter()
    for item in scored:
        if brand_count[str(item["brand"])] >= 1:
            continue
        if category_count[str(item["category"])] >= 2:
            continue
        rank = len(rows) + 1
        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                "scenario_label": scenario["scenario_label"],
                "skin_type": scenario["skin_type"],
                "sensitivity": scenario["sensitivity"],
                "section_id": blueprint["section_id"],
                "section_label": blueprint["section_label"],
                "source_effect_id": "",
                "source_effect_name": "시장 인기",
                "rank": str(rank),
                "product_id": str(item["product_id"]),
                "brand": str(item["brand"]),
                "name": str(item["name"]),
                "category": str(item["category"]),
                "price": str(prices[str(item["product_id"])]),
                "personalized_home_score": str(item["market_popularity_score"]),
                "axis_score": "",
                "coverage_score": "",
                "profile_fit_score": str(item["profile_fit_score"]),
                "sensitivity_fit_score": str(item["sensitivity_fit_score"]),
                "price_score": str(item["price_score"]),
                "market_popularity_score": str(item["market_popularity_score"]),
                "review_count_score": str(item["review_count_score"]),
                "rating_score": str(item["rating_score"]),
                "sales_score": str(item["sales_score"]),
                "recent_signal_score": str(item["recent_signal_score"]),
                "risk_penalty": "",
                "matched_ingredients": "",
                "coverage_types": "",
                "coverage_basis": "",
                "reason_summary": "리뷰, 평점, 판매 신호를 함께 본 인기 후보예요.",
                "thumbnail_url": str(item["thumbnail_url"]),
            }
        )
        brand_count[str(item["brand"])] += 1
        category_count[str(item["category"])] += 1
        used_product_ids.add(str(item["product_id"]))
        if len(rows) >= limit:
            break
    return rows


def score_scenario_section(
    scenario: dict[str, str],
    blueprint: dict[str, str],
    source_section: dict[str, object],
    products: list[dict[str, str]],
    ingredients_by_product: dict[str, list[dict[str, str]]],
    effects: dict[str, dict[str, dict[str, str]]],
    ranges: dict[tuple[str, str], dict[str, str]],
    coverage: dict[tuple[str, str], dict[str, str]],
    risk_scores: dict[str, float],
    prices: dict[str, int],
    skin_profiles: dict[str, dict[str, str]],
    used_product_ids: set[str],
    limit: int = 5,
) -> list[dict[str, str]]:
    avoid_ingredient_ids = split_ids(scenario.get("avoid_ingredient_ids", ""))
    scored: list[dict[str, object]] = []
    for product in products:
        product_id = product["product_id"]
        if product_id in used_product_ids:
            continue
        ingredients = ingredients_by_product[product_id]
        if product_has_avoided_ingredient(ingredients, avoid_ingredient_ids):
            continue
        if not cold.position_matches(product, source_section):
            continue
        cold_score = cold.score_product_for_section(
            product,
            source_section,
            ingredients,
            effects,
            ranges,
            coverage,
            risk_scores,
            prices[product_id],
        )
        if cold_score is None:
            continue
        product_ingredient_ids = {row["ingredient_id"] for row in ingredients}
        profile = profile_fit_score(skin_profiles.get(product_id), scenario["skin_type"])
        sensitivity = sensitivity_fit_score(skin_profiles.get(product_id), scenario["sensitivity"])
        price = price_score(prices[product_id])
        risk_penalty = personalized_risk_penalty(product_ingredient_ids, risk_scores, scenario["sensitivity"])
        score = personalized_score(
            blueprint["mode"],
            float(cold_score["axis_score"]),
            float(cold_score["coverage_score"]),
            profile,
            sensitivity,
            price,
            risk_penalty,
        )
        scored.append(
            {
                **product,
                **cold_score,
                "profile_fit_score": profile,
                "sensitivity_fit_score": sensitivity,
                "price_score": price,
                "risk_penalty": risk_penalty,
                "personalized_home_score": score,
            }
        )

    scored.sort(
        key=lambda item: (
            -float(item["personalized_home_score"]),
            -float(item["axis_score"]),
            -float(item["coverage_score"]),
            -float(item["profile_fit_score"]),
            float(item["risk_penalty"]),
            prices[str(item["product_id"])],
            str(item["category"]),
            str(item["brand"]),
            str(item["product_id"]),
        )
    )

    rows: list[dict[str, str]] = []
    brand_count: Counter[str] = Counter()
    category_count: Counter[str] = Counter()
    for item in scored:
        if brand_count[str(item["brand"])] >= 1:
            continue
        if category_count[str(item["category"])] >= 2:
            continue
        rank = len(rows) + 1
        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                "scenario_label": scenario["scenario_label"],
                "skin_type": scenario["skin_type"],
                "sensitivity": scenario["sensitivity"],
                "section_id": blueprint["section_id"],
                "section_label": blueprint["section_label"],
                "source_effect_id": str(source_section["effect_id"]),
                "source_effect_name": str(source_section["effect_name"]),
                "rank": str(rank),
                "product_id": str(item["product_id"]),
                "brand": str(item["brand"]),
                "name": str(item["name"]),
                "category": str(item["category"]),
                "price": str(prices[str(item["product_id"])]),
                "personalized_home_score": str(item["personalized_home_score"]),
                "axis_score": str(item["axis_score"]),
                "coverage_score": str(item["coverage_score"]),
                "profile_fit_score": str(item["profile_fit_score"]),
                "sensitivity_fit_score": str(item["sensitivity_fit_score"]),
                "price_score": str(item["price_score"]),
                "risk_penalty": str(item["risk_penalty"]),
                "matched_ingredients": str(item["matched_ingredients"]),
                "coverage_types": str(item["coverage_types"]),
                "coverage_basis": str(item["coverage_basis"]),
                "reason_summary": build_reason_summary(scenario, blueprint, source_section),
                "thumbnail_url": str(item["thumbnail_url"]),
            }
        )
        brand_count[str(item["brand"])] += 1
        category_count[str(item["category"])] += 1
        used_product_ids.add(str(item["product_id"]))
        if len(rows) >= limit:
            break
    return rows


def build_reason_summary(
    scenario: dict[str, str],
    blueprint: dict[str, str],
    source_section: dict[str, object],
) -> str:
    if blueprint["mode"] == "market":
        return "리뷰, 평점, 판매 신호를 함께 본 인기 후보예요."
    if blueprint["mode"] == "evidence":
        return f"{source_section['effect_name']} 축 성분 근거와 함량 coverage가 비교적 뚜렷한 후보예요."
    if blueprint["mode"] == "price_value":
        return f"{scenario['skin_type']}·{scenario['sensitivity']} 조건에 맞는 후보 중 가격 접근성까지 함께 봤어요."
    return f"{scenario['skin_type']}·{scenario['sensitivity']} 피부 조건과 {source_section['effect_name']} 고민을 종합해 봤어요."


def build() -> list[dict[str, str]]:
    products = cold.read_csv(cold.DATA_DIR / "products.csv")
    prices = cold.load_lowest_prices()
    ingredients_by_product = cold.load_ingredients_by_product()
    effects = cold.load_effects()
    ranges = cold.load_ranges()
    coverage = cold.load_coverage()
    risk_scores = cold.load_risk_scores()
    skin_profiles = load_skin_profiles()
    market_context = market.load_market_popularity_context(cold.DATA_DIR)
    sections = section_by_effect_id()

    eligible = [
        product
        for product in products
        if product_in_p2_scope(product)
        and cold.product_is_eligible(product, prices, ingredients_by_product)
    ]

    rows: list[dict[str, str]] = []
    for scenario in SCENARIOS:
        used_product_ids: set[str] = set()
        for blueprint in SECTION_BLUEPRINTS:
            if blueprint["mode"] == "market":
                rows.extend(
                    score_scenario_market_section(
                        scenario,
                        blueprint,
                        eligible,
                        ingredients_by_product,
                        prices,
                        skin_profiles,
                        market_context,
                        used_product_ids,
                        limit=5,
                    )
                )
                continue
            source_section = source_section_for_blueprint(scenario, blueprint, sections)
            rows.extend(
                score_scenario_section(
                    scenario,
                    blueprint,
                    source_section,
                    eligible,
                    ingredients_by_product,
                    effects,
                    ranges,
                    coverage,
                    risk_scores,
                    prices,
                    skin_profiles,
                    used_product_ids,
                    limit=5,
                )
            )
    return rows


def main() -> None:
    rows = build()
    write_csv(OUT, rows)
    print(f"wrote {OUT} ({len(rows)} rows)")
    for scenario in SCENARIOS:
        scenario_rows = [row for row in rows if row["scenario_id"] == scenario["scenario_id"]]
        print(scenario["scenario_id"], len(scenario_rows))


if __name__ == "__main__":
    main()
