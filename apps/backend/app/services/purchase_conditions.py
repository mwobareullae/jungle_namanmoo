import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class MatchedCategory:
    category_code: str
    name: str
    matched_text: str


@dataclass(frozen=True)
class MatchedBrand:
    brand_code: str
    name: str
    matched_text: str


@dataclass(frozen=True)
class ParsedPurchaseConditions:
    categories: tuple[MatchedCategory, ...]
    brands: tuple[MatchedBrand, ...]
    price_min: int | None
    price_max: int | None
    price_text: str | None
    price_max_text: str | None

    @property
    def has_constraints(self) -> bool:
        return bool(self.categories or self.brands or self.price_min is not None or self.price_max is not None)


@dataclass(frozen=True)
class CategoryAliasGroup:
    category_code: str
    name: str
    exact_aliases: tuple[str, ...]
    suffix_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrandAliasGroup:
    brand_code: str
    name: str
    aliases: tuple[str, ...]


# Current product seed categories are serum, cream, toner, lotion.
# Do not emit unsupported category codes here, because these become hard filters.
DEFAULT_CATEGORY_ALIASES: tuple[CategoryAliasGroup, ...] = (
    CategoryAliasGroup(
        "serum",
        "세럼",
        ("serum", "ampoule", "ampule", "essence"),
        ("세럼", "새럼", "쎄럼", "앰플", "엠플", "에센스"),
    ),
    CategoryAliasGroup(
        "toner",
        "토너",
        ("스킨", "닦토", "toner", "skin"),
        ("토너",),
    ),
    CategoryAliasGroup(
        "lotion",
        "로션",
        ("lotion", "emulsion"),
        ("로션", "로숀", "에멀전", "에멀젼", "에멀션"),
    ),
    CategoryAliasGroup(
        "cream",
        "크림",
        ("cream",),
        ("크림",),
    ),
)

BRAND_ALIAS_OVERRIDES: dict[str, tuple[str, ...]] = {
    "라운드랩": ("라운드랩", "라운드 랩", "round lab", "roundlab"),
    "닥터지": ("닥터지", "닥터 지", "dr.g", "dr g", "drg"),
    "토리든": ("토리든", "torriden"),
    "아누아": ("아누아", "anua"),
    "에스트라": ("에스트라", "aestura"),
    "제로이드": ("제로이드", "zeroid"),
    "디오디너리": ("디오디너리", "the ordinary", "ordinary"),
    "라로슈포제": ("라로슈포제", "라 로슈 포제", "la roche posay", "larocheposay"),
    "폴라초이스": ("폴라초이스", "폴라 초이스", "paula's choice", "paulas choice"),
}

PRICE_RANGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<amount>\d+)\s*만\s*원?\s*대"),
)

PRICE_MAX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*만\s*원?\s*(?P<bound>이하|미만|까지|이내|아래|안쪽|under)"),
    re.compile(r"(?P<amount>\d{4,})\s*원?\s*(?P<bound>이하|미만|까지|이내|아래|안쪽|under)"),
)


def parse_purchase_conditions(
    text: str | None,
    *,
    category_aliases: tuple[CategoryAliasGroup, ...] = DEFAULT_CATEGORY_ALIASES,
    brand_aliases: tuple[BrandAliasGroup, ...] | None = None,
) -> ParsedPurchaseConditions:
    normalized_text = _normalize_text(text or "")
    if not normalized_text:
        return ParsedPurchaseConditions(
            categories=(),
            brands=(),
            price_min=None,
            price_max=None,
            price_text=None,
            price_max_text=None,
        )

    price_min, price_max, price_text = _match_price_condition(normalized_text)
    return ParsedPurchaseConditions(
        categories=_match_categories(normalized_text, category_aliases),
        brands=_match_brands(normalized_text, brand_aliases or get_default_brand_aliases()),
        price_min=price_min,
        price_max=price_max,
        price_text=price_text,
        price_max_text=price_text,
    )


@lru_cache(maxsize=1)
def get_default_brand_aliases() -> tuple[BrandAliasGroup, ...]:
    brand_names = _load_brand_names_from_products(Path(settings.data_dir))
    override_names = tuple(BRAND_ALIAS_OVERRIDES.keys())
    return build_brand_aliases((*brand_names, *override_names))


def build_brand_aliases(brand_names: tuple[str, ...]) -> tuple[BrandAliasGroup, ...]:
    groups_by_code: dict[str, BrandAliasGroup] = {}
    for brand_name in brand_names:
        name = brand_name.strip()
        if not name:
            continue

        aliases = _unique_aliases((name, *BRAND_ALIAS_OVERRIDES.get(name, ())))
        brand_code = _code_from_text(name)
        groups_by_code[brand_code] = BrandAliasGroup(
            brand_code=brand_code,
            name=name,
            aliases=aliases,
        )

    return tuple(groups_by_code.values())


def _load_brand_names_from_products(data_dir: Path) -> tuple[str, ...]:
    products_paths = _resolve_product_csv_paths(data_dir)
    if not products_paths:
        return ()

    brand_names: list[str] = []
    for products_path in products_paths:
        with products_path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            brand_names.extend(
                row["brand"].strip()
                for row in reader
                if row.get("brand") and row["brand"].strip()
            )
    return tuple(brand_names)


def _resolve_product_csv_paths(data_dir: Path) -> tuple[Path, ...]:
    products_path = data_dir / "products.csv"
    products_dir = data_dir / "products"

    if products_path.exists():
        return (products_path,)
    if not products_dir.exists():
        return ()
    return tuple(sorted(path for path in products_dir.glob("*.csv") if path.is_file()))


def _match_categories(
    normalized_text: str,
    category_aliases: tuple[CategoryAliasGroup, ...],
) -> tuple[MatchedCategory, ...]:
    matched: list[MatchedCategory] = []
    seen_codes: set[str] = set()
    for group in category_aliases:
        alias = _find_first_category_alias(normalized_text, group)
        if alias is None or group.category_code in seen_codes:
            continue
        matched.append(
            MatchedCategory(
                category_code=group.category_code,
                name=group.name,
                matched_text=alias,
            )
        )
        seen_codes.add(group.category_code)
    return tuple(matched)


def _find_first_category_alias(normalized_text: str, group: CategoryAliasGroup) -> str | None:
    matches: list[tuple[str, int]] = []
    for alias in group.exact_aliases:
        match = _match_exact_alias(normalized_text, alias)
        if match is not None:
            matches.append((alias, match.start()))

    for alias in group.suffix_aliases:
        match = _match_suffix_alias(normalized_text, alias)
        if match is not None:
            matches.append((alias, match.start()))

    if not matches:
        return None
    return min(matches, key=lambda item: item[1])[0]


def _match_brands(
    normalized_text: str,
    brand_aliases: tuple[BrandAliasGroup, ...],
) -> tuple[MatchedBrand, ...]:
    matched: list[MatchedBrand] = []
    seen_codes: set[str] = set()
    for group in brand_aliases:
        alias = _find_first_alias(normalized_text, group.aliases)
        if alias is None or group.brand_code in seen_codes:
            continue
        matched.append(
            MatchedBrand(
                brand_code=group.brand_code,
                name=group.name,
                matched_text=alias,
            )
        )
        seen_codes.add(group.brand_code)
    return tuple(matched)


def _match_price_condition(normalized_text: str) -> tuple[int | None, int | None, str | None]:
    range_min, range_max, range_text = _match_price_range(normalized_text)
    if range_text is not None:
        return range_min, range_max, range_text

    price_max, price_text = _match_price_max(normalized_text)
    return None, price_max, price_text


def _match_price_range(normalized_text: str) -> tuple[int | None, int | None, str | None]:
    for pattern in PRICE_RANGE_PATTERNS:
        match = pattern.search(normalized_text)
        if match is None:
            continue

        amount = int(match.group("amount")) * 10000
        return amount, amount + 9999, match.group(0).strip()

    return None, None, None


def _match_price_max(normalized_text: str) -> tuple[int | None, str | None]:
    for pattern in PRICE_MAX_PATTERNS:
        match = pattern.search(normalized_text)
        if match is None:
            continue

        amount_text = match.group("amount")
        multiplier = 10000 if re.search(r"\d+(?:\.\d+)?\s*만", match.group(0)) else 1
        amount = int(float(amount_text) * multiplier)
        if match.group("bound") in {"미만", "아래", "under"}:
            amount -= 1
        return amount, match.group(0).strip()

    return None, None


def _find_first_alias(normalized_text: str, aliases: tuple[str, ...]) -> str | None:
    matches = [alias for alias in aliases if _matches_alias(normalized_text, alias)]
    if not matches:
        return None
    return min(matches, key=lambda alias: _alias_position(normalized_text, alias))


def _matches_alias(normalized_text: str, alias: str) -> bool:
    return _match_exact_alias(normalized_text, alias) is not None


def _match_exact_alias(normalized_text: str, alias: str) -> re.Match[str] | None:
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return None

    pattern = _boundary_pattern(normalized_alias)
    return pattern.search(normalized_text)


def _match_suffix_alias(normalized_text: str, alias: str) -> re.Match[str] | None:
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return None

    pattern = _suffix_pattern(normalized_alias)
    return pattern.search(normalized_text)


def _alias_position(normalized_text: str, alias: str) -> int:
    match = _boundary_pattern(_normalize_text(alias)).search(normalized_text)
    return match.start() if match is not None else len(normalized_text)


def _boundary_pattern(normalized_alias: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![0-9a-zA-Z가-힣]){re.escape(normalized_alias)}(?![0-9a-zA-Z가-힣])"
    )


def _suffix_pattern(normalized_alias: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(normalized_alias)}(?![0-9a-zA-Z가-힣])")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _code_from_text(text: str) -> str:
    return "".join(text.casefold().split())


def _unique_aliases(values: tuple[str, ...]) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in seen:
            aliases.append(value)
            seen.add(normalized)
    return tuple(aliases)

