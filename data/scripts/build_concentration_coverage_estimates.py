from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "reconciliation" / "concentration_coverage_estimates.csv"


FIELDNAMES = [
    "product_id",
    "ingredient_id",
    "ingredient_name",
    "display_order",
    "concentration_type",
    "value_min",
    "value_max",
    "unit",
    "confidence",
    "visibility",
    "basis",
    "source",
]


TYPE_PRIORITY = {
    "exact": 100,
    "range": 90,
    "regulatory_anchor": 80,
    "legal_upper_bound": 70,
    "lower_bound": 60,
    "marker_upper_bound": 50,
    "prior_estimate": 10,
}


FUNCTIONAL_RANGES = {
    ("niacinamide", "미백"): ("range", "2", "5", "%", "medium", "기능성 표시 + 나이아신아마이드 미백 고시 2~5%; exact 아님"),
    ("arbutin", "미백"): ("range", "2", "5", "%", "medium", "기능성 표시 + 알부틴 미백 고시 2~5%; exact 아님"),
    ("adenosine", "주름개선"): ("regulatory_anchor", "0.04", "0.04", "%", "medium", "기능성 표시 + 아데노신 주름개선 고시 0.04%; exact 아님"),
    ("bisabolol", "미백"): ("regulatory_anchor", "0.5", "0.5", "%", "medium", "기능성 표시 + 알파-비사보롤 미백 고시 0.5%; exact 아님"),
    ("licorice_extract", "미백"): ("regulatory_anchor", "0.05", "0.05", "%", "low", "기능성 표시 + 유용성감초추출물 미백 고시 0.05%; exact 아님"),
    ("ascorbic_acid", "미백"): ("regulatory_anchor", "2", "2", "%", "low", "기능성 표시 + 비타민C 계열 고시 앵커 후보; 순수 L-AA 여부 확인 필요"),
    ("retinol", "주름개선"): ("regulatory_anchor", "", "", "IU/g", "low", "기능성 표시 + 레티놀 주름개선 고시 2,500 IU/g; % 직접 변환 보류"),
}


LEGAL_UPPER_BOUNDS_BY_NAME = {
    "페녹시에탄올": ("", "1", "%", "high", "화장품 안전기준 별표2 보존제 사용한도"),
    "벤질알코올": ("", "1", "%", "high", "화장품 안전기준 별표2 보존제 사용한도"),
    "클로페네신": ("", "0.3", "%", "high", "화장품 안전기준 별표2 보존제 사용한도"),
    "메틸파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "메칠파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "에틸파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "에칠파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "프로필파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "부틸파라벤": ("", "0.4", "%", "high", "화장품 안전기준 별표2 파라벤 단일 사용한도"),
    "징크옥사이드": ("", "25", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "티타늄디옥사이드": ("", "25", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "에칠헥실메톡시신나메이트": ("", "7.5", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "에틸헥실메톡시신나메이트": ("", "7.5", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "옥토크릴렌": ("", "10", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "부틸메톡시디벤조일메탄": ("", "5", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
    "에칠헥실살리실레이트": ("", "5", "%", "high", "화장품 안전기준 별표2 자외선차단성분 사용한도"),
}


MARKER_NAMES = {
    "페녹시에탄올",
    "카보머",
    "소듐카보머",
    "잔탄검",
    "다이소듐이디티에이",
    "디소듐이디티에이",
    "트라이소듐이디티에이",
    "트리소듐이디티에이",
    "테트라소듐이디티에이",
    "토코페롤",
    "토코페릴아세테이트",
}


ALLERGEN_NAMES = {
    "아밀신남알",
    "벤질알코올",
    "신나밀알코올",
    "시트랄",
    "유제놀",
    "하이드록시시트로넬알",
    "이소유제놀",
    "아밀신나밀알코올",
    "벤질살리실레이트",
    "신남알",
    "쿠마린",
    "제라니올",
    "아니스에탄올",
    "벤질신나메이트",
    "파네솔",
    "부틸페닐메칠프로피오날",
    "리날룰",
    "벤질벤조에이트",
    "시트로넬롤",
    "헥실신남알",
    "리모넨",
    "메칠2-옥티노에이트",
    "알파-이소메칠이오논",
    "참나무이끼추출물",
    "나무이끼추출물",
}


RINSE_OFF_CATEGORIES = {"cleanser", "cleansing", "wash", "shampoo", "bodywash"}


@dataclass(frozen=True)
class Estimate:
    product_id: str
    ingredient_id: str
    ingredient_name: str
    display_order: int
    concentration_type: str
    value_min: str
    value_max: str
    unit: str
    confidence: str
    visibility: str
    basis: str
    source: str

    @property
    def priority(self) -> int:
        return TYPE_PRIORITY[self.concentration_type]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def normalize_name(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value or "").lower()


def parse_order(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 9999


def parse_percent(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def split_values(value: str) -> set[str]:
    return {part.strip() for part in (value or "").split(";") if part.strip()}


def is_functional_product(product: dict[str, str]) -> bool:
    status = (product.get("functional_cosmetic_status") or "").strip()
    return status not in {"", "NOT_FUNCTIONAL", "UNKNOWN"}


def is_rinse_off(product: dict[str, str]) -> bool:
    category = normalize_name(product.get("category", ""))
    return any(token in category for token in RINSE_OFF_CATEGORIES)


def choose(existing: Estimate | None, candidate: Estimate) -> Estimate:
    if existing is None:
        return candidate
    if candidate.priority > existing.priority:
        return candidate
    if candidate.priority == existing.priority and candidate.confidence == "high" and existing.confidence != "high":
        return candidate
    return existing


def add_estimate(best: dict[tuple[str, str], Estimate], estimate: Estimate) -> None:
    key = (estimate.product_id, estimate.ingredient_id)
    best[key] = choose(best.get(key), estimate)


def build_estimates() -> list[dict[str, str]]:
    products = {row["product_id"]: row for row in read_csv(DATA_DIR / "products.csv")}
    product_ingredients = read_csv(DATA_DIR / "product_ingredients.csv")
    ingredients_by_product: dict[str, list[dict[str, str]]] = {}
    for row in product_ingredients:
        ingredients_by_product.setdefault(row["product_id"], []).append(row)

    first_marker_by_product: dict[str, int] = {}
    for product_id, rows in ingredients_by_product.items():
        marker_orders = [
            parse_order(row.get("display_order", ""))
            for row in rows
            if row.get("ingredient_name", "").strip() in MARKER_NAMES
        ]
        if marker_orders:
            first_marker_by_product[product_id] = min(marker_orders)

    best: dict[tuple[str, str], Estimate] = {}

    for row in product_ingredients:
        value = (row.get("normalized_concentration_value") or "").strip()
        if not value:
            continue
        display_order = parse_order(row.get("display_order", ""))
        percent_value = parse_percent(value)
        first_marker_order = first_marker_by_product.get(row["product_id"])
        if (
            percent_value is not None
            and percent_value > 1
            and first_marker_order is not None
            and display_order >= first_marker_order
        ):
            # A >1% exact claim after a 1% marker conflicts with ingredient-order logic.
            # Treat it as marketing/sub-formula parsing noise and let weaker heuristics apply.
            continue
        add_estimate(
            best,
            Estimate(
                product_id=row["product_id"],
                ingredient_id=row["ingredient_id"],
                ingredient_name=row["ingredient_name"],
                display_order=display_order,
                concentration_type="exact",
                value_min=value,
                value_max=value,
                unit=row.get("normalized_concentration_unit") or "%",
                confidence=row.get("concentration_confidence") or "medium",
                visibility="public",
                basis=row.get("concentration_text") or "상품 원문 함량 표기",
                source="product_ingredients.normalized_concentration_value",
            ),
        )

    for product_id, rows in ingredients_by_product.items():
        product = products.get(product_id, {})
        claims = split_values(product.get("functional_cosmetic_claims", ""))
        if is_functional_product(product):
            for row in rows:
                for claim in claims:
                    functional = FUNCTIONAL_RANGES.get((row["ingredient_id"], claim))
                    if not functional:
                        continue
                    ctype, value_min, value_max, unit, confidence, basis = functional
                    add_estimate(
                        best,
                        Estimate(
                            product_id=product_id,
                            ingredient_id=row["ingredient_id"],
                            ingredient_name=row["ingredient_name"],
                            display_order=parse_order(row.get("display_order", "")),
                            concentration_type=ctype,
                            value_min=value_min,
                            value_max=value_max,
                            unit=unit,
                            confidence=confidence,
                            visibility="public",
                            basis=basis,
                            source="functional_cosmetic_status + MFDS functional standard",
                        ),
                    )

        fragrance_orders = [
            parse_order(row.get("display_order", ""))
            for row in rows
            if normalize_name(row.get("ingredient_name", "")).startswith(normalize_name("향료"))
        ]
        first_fragrance_order = min(fragrance_orders) if fragrance_orders else None
        marker_orders = [
            parse_order(row.get("display_order", ""))
            for row in rows
            if row.get("ingredient_name", "").strip() in MARKER_NAMES
        ]
        first_marker_order = min(marker_orders) if marker_orders else None

        for row in rows:
            name = row["ingredient_name"].strip()
            if name in LEGAL_UPPER_BOUNDS_BY_NAME:
                value_min, value_max, unit, confidence, basis = LEGAL_UPPER_BOUNDS_BY_NAME[name]
                add_estimate(
                    best,
                    Estimate(
                        product_id=product_id,
                        ingredient_id=row["ingredient_id"],
                        ingredient_name=name,
                        display_order=parse_order(row.get("display_order", "")),
                        concentration_type="legal_upper_bound",
                        value_min=value_min,
                        value_max=value_max,
                        unit=unit,
                        confidence=confidence,
                        visibility="public",
                        basis=basis,
                        source="MFDS cosmetic safety standard annex 2",
                    ),
                )

            order = parse_order(row.get("display_order", ""))
            if first_marker_order is not None and order >= first_marker_order:
                add_estimate(
                    best,
                    Estimate(
                        product_id=product_id,
                        ingredient_id=row["ingredient_id"],
                        ingredient_name=name,
                        display_order=order,
                        concentration_type="marker_upper_bound",
                        value_min="",
                        value_max="1",
                        unit="%",
                        confidence="medium",
                        visibility="internal",
                        basis="1% marker ingredient appears before or at this ingredient; upper-bound heuristic only",
                        source="Cosmetics Act enforcement rule ingredient order + marker heuristic",
                    ),
                )

            if (
                first_fragrance_order is not None
                and order > first_fragrance_order
                and name in ALLERGEN_NAMES
            ):
                lower = "0.01" if is_rinse_off(product) else "0.001"
                add_estimate(
                    best,
                    Estimate(
                        product_id=product_id,
                        ingredient_id=row["ingredient_id"],
                        ingredient_name=name,
                        display_order=order,
                        concentration_type="lower_bound",
                        value_min=lower,
                        value_max="",
                        unit="%",
                        confidence="medium",
                        visibility="public_tentative",
                        basis="향료 이후 알레르기 유발 착향제 개별 표기 기준; 일반 원료 직접 배합은 아님",
                        source="MFDS allergen fragrance labeling rule",
                    ),
                )

        if rows:
            first = min(rows, key=lambda item: parse_order(item.get("display_order", "")))
            if first.get("ingredient_name") == "정제수":
                category = normalize_name(product.get("category", ""))
                value_min, value_max = ("60", "90")
                if "cream" in category or "크림" in category:
                    value_min, value_max = ("40", "80")
                add_estimate(
                    best,
                    Estimate(
                        product_id=product_id,
                        ingredient_id=first["ingredient_id"],
                        ingredient_name=first["ingredient_name"],
                        display_order=parse_order(first.get("display_order", "")),
                        concentration_type="prior_estimate",
                        value_min=value_min,
                        value_max=value_max,
                        unit="%",
                        confidence="low",
                        visibility="internal",
                        basis="제형 기반 정제수 prior; 법정/라벨 근거 아님",
                        source="formulation prior heuristic",
                    ),
                )

    estimates = sorted(
        best.values(),
        key=lambda item: (item.product_id, item.display_order, -item.priority, item.ingredient_name),
    )
    return [
        {
            "product_id": estimate.product_id,
            "ingredient_id": estimate.ingredient_id,
            "ingredient_name": estimate.ingredient_name,
            "display_order": str(estimate.display_order),
            "concentration_type": estimate.concentration_type,
            "value_min": estimate.value_min,
            "value_max": estimate.value_max,
            "unit": estimate.unit,
            "confidence": estimate.confidence,
            "visibility": estimate.visibility,
            "basis": estimate.basis,
            "source": estimate.source,
        }
        for estimate in estimates
    ]


def main() -> None:
    rows = build_estimates()
    write_csv(OUT_PATH, rows)
    public_types = {"exact", "range", "regulatory_anchor", "legal_upper_bound"}
    internal_types = public_types | {"marker_upper_bound", "prior_estimate"}
    total_rows = len(read_csv(DATA_DIR / "product_ingredients.csv"))
    public_count = sum(1 for row in rows if row["concentration_type"] in public_types)
    internal_count = sum(1 for row in rows if row["concentration_type"] in internal_types)
    print(f"wrote {OUT_PATH}")
    print(f"total product ingredient rows: {total_rows}")
    print(f"coverage rows: {len(rows)}")
    print(f"public KPI rows: {public_count} ({public_count / total_rows:.1%})")
    print(f"internal KPI rows: {internal_count} ({internal_count / total_rows:.1%})")


if __name__ == "__main__":
    main()
