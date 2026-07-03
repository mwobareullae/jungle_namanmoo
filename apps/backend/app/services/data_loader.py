import csv
import json
import logging
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from app.models.data_contract import (
    ConcernEffect,
    ConcernTag,
    DataCatalog,
    Ingredient,
    IngredientAlias,
    IngredientEffect,
    IngredientEffectRange,
    IngredientEvidence,
    Product,
    ProductImageAsset,
    ProductInventory,
    ProductIngredient,
    ProductPrice,
    ProductSkinProfile,
    RiskFlag,
    SearchDocument,
)


logger = logging.getLogger(__name__)


class DataLoadError(ValueError):
    pass


CSV_HEADERS = {
    "products.csv": {
        "product_id",
        "brand",
        "name",
        "category",
        "skin_type_tags",
        "thumbnail_url",
        "image_urls",
        "functional_review_text",
        "functional_cosmetic_status",
        "functional_cosmetic_claims",
        "functional_claim_confidence",
        "functional_claim_basis",
    },
    "product_prices.csv": {
        "product_id",
        "mall_name",
        "price",
        "product_url",
        "is_lowest",
        "currency",
    },
    "product_image_assets.csv": {
        "product_id",
        "image_type",
        "display_order",
        "storage_key",
    },
    "product_inventory.csv": {
        "product_id",
        "stock_quantity",
        "sales_status",
        "safety_stock",
        "inventory_source",
    },
    "product_ingredients.csv": {
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
    },
    "product_skin_profiles.csv": {
        "product_id",
        "dry_fit",
        "oily_fit",
        "combination_fit",
        "normal_fit",
        "dehydrated_oily_fit",
        "sensitive_fit",
        "sensitivity_tag",
        "confidence",
        "reason",
    },
    "ingredients.csv": {"ingredient_id", "name_ko", "name_en", "description"},
    "ingredient_aliases.csv": {"alias", "canonical_id", "alias_type", "confidence", "source"},
    "ingredient_effect.csv": {"ingredient_id", "effect_id", "effect_name", "effect_score"},
    "ingredient_effect_ranges.csv": {
        "ingredient_id",
        "effect_id",
        "unit",
        "meaningful_min",
        "optimal_min",
        "optimal_max",
        "excessive_min",
        "range_confidence",
        "source_type",
        "source_url",
        "note",
    },
    "ingredient_evidence.csv": {
        "ingredient_id",
        "effect_id",
        "evidence_level",
        "evidence_score",
        "source_title",
        "source_url",
        "summary",
        "source_type",
        "pmid",
        "doi",
        "source_authority_score",
    },
    "risk_flags.csv": {
        "ingredient_id",
        "risk_type",
        "display_text",
        "severity",
        "severity_score",
        "applies_to",
        "condition",
        "source_type",
        "source_url",
    },
    "vector_docs.csv": {"doc_id", "source_type", "source_id", "text"},
}

CONTENT_CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
CONCENTRATION_CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
PROFILE_CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
RANGE_CONFIDENCE_VALUES = {"high", "medium", "low", "unknown"}
EVIDENCE_LEVEL_VALUES = {"high", "medium", "low"}
ALIAS_TYPE_VALUES = {"ko", "en", "inci", "abbrev", "typo", "synonym"}
ALIAS_CONFIDENCE_VALUES = {"high", "medium", "low"}
ALIAS_CONFIDENCE_ALIASES = {"med": "medium"}
SALES_STATUS_VALUES = {"ON_SALE", "SOLD_OUT", "HIDDEN"}

T = TypeVar("T")


def load_data_catalog(data_dir: str | Path) -> DataCatalog:
    base_path = Path(data_dir)

    products = _load_csv(base_path, "products.csv", _parse_product)
    product_prices = _load_csv(base_path, "product_prices.csv", _parse_product_price)
    product_image_assets = _load_optional_csv(
        base_path,
        "product_image_assets.csv",
        _parse_product_image_asset,
    )
    product_inventories = _load_optional_csv(
        base_path,
        "product_inventory.csv",
        _parse_product_inventory,
    )
    product_ingredients = _load_csv(
        base_path,
        "product_ingredients.csv",
        _parse_product_ingredient,
    )
    product_skin_profiles = _load_csv(
        base_path,
        "product_skin_profiles.csv",
        _parse_product_skin_profile,
    )
    ingredients = _load_csv(base_path, "ingredients.csv", _parse_ingredient)
    ingredient_aliases = _load_optional_csv(
        base_path,
        "ingredient_aliases.csv",
        _parse_ingredient_alias,
    )
    ingredient_effects = _load_csv(
        base_path,
        "ingredient_effect.csv",
        _parse_ingredient_effect,
    )
    ingredient_effect_ranges = _load_csv(
        base_path,
        "ingredient_effect_ranges.csv",
        _parse_ingredient_effect_range,
    )
    ingredient_evidence = _load_csv(
        base_path,
        "ingredient_evidence.csv",
        _parse_ingredient_evidence,
    )
    risk_flags = _load_csv(base_path, "risk_flags.csv", _parse_risk_flag)
    search_documents = _load_csv(base_path, "vector_docs.csv", _parse_search_document)
    concern_tags = _load_tags(base_path)
    concern_effects = _load_concern_effects(base_path)

    catalog = DataCatalog(
        products=products,
        product_prices=product_prices,
        product_image_assets=product_image_assets,
        product_inventories=product_inventories,
        product_ingredients=product_ingredients,
        product_skin_profiles=product_skin_profiles,
        ingredients=ingredients,
        ingredient_aliases=ingredient_aliases,
        ingredient_effects=ingredient_effects,
        ingredient_effect_ranges=ingredient_effect_ranges,
        ingredient_evidence=ingredient_evidence,
        risk_flags=risk_flags,
        concern_tags=concern_tags,
        concern_effects=concern_effects,
        search_documents=search_documents,
    )
    _validate_catalog(catalog)
    return catalog


def load_concern_tags(data_dir: str | Path) -> tuple[ConcernTag, ...]:
    return _load_tags(Path(data_dir))


def load_concern_effects(data_dir: str | Path) -> tuple[ConcernEffect, ...]:
    return _load_concern_effects(Path(data_dir))


def _load_csv(
    base_path: Path,
    file_name: str,
    parser: Callable[[dict[str, str], str, int], T],
) -> tuple[T, ...]:
    file_path = base_path / file_name
    if not file_path.exists():
        raise DataLoadError(f"필수 데이터 파일이 없습니다: {file_name}")

    with file_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = set(reader.fieldnames or [])
        missing_headers = sorted(CSV_HEADERS[file_name] - headers)
        if missing_headers:
            missing = ", ".join(missing_headers)
            raise DataLoadError(f"{file_name} 필수 컬럼이 없습니다: {missing}")

        return tuple(parser(row, file_name, line_number) for line_number, row in enumerate(reader, 2))


def _load_optional_csv(
    base_path: Path,
    file_name: str,
    parser: Callable[[dict[str, str], str, int], T],
) -> tuple[T, ...]:
    file_path = base_path / file_name
    if not file_path.exists():
        logger.warning("선택 데이터 파일이 없습니다: %s", file_name)
        return ()

    return _load_csv(base_path, file_name, parser)


def _load_tags(base_path: Path) -> tuple[ConcernTag, ...]:
    records = _load_json_records(base_path, "tags.json", {"tag_id", "name", "synonyms"})
    return tuple(
        ConcernTag(
            tag_id=_required_text(record, "tag_id", "tags.json", index),
            name=_required_text(record, "name", "tags.json", index),
            synonyms=tuple(_required_list(record, "synonyms", "tags.json", index)),
        )
        for index, record in enumerate(records)
    )


def _load_concern_effects(base_path: Path) -> tuple[ConcernEffect, ...]:
    records = _load_json_records(
        base_path,
        "concern_to_effect.json",
        {"tag_id", "effect_id", "effect_name", "weight"},
    )
    return tuple(
        ConcernEffect(
            tag_id=_required_text(record, "tag_id", "concern_to_effect.json", index),
            effect_id=_required_text(record, "effect_id", "concern_to_effect.json", index),
            effect_name=_required_text(record, "effect_name", "concern_to_effect.json", index),
            weight=_required_float(record, "weight", "concern_to_effect.json", index),
        )
        for index, record in enumerate(records)
    )


def _load_json_records(
    base_path: Path,
    file_name: str,
    required_keys: set[str],
) -> list[dict]:
    file_path = base_path / file_name
    if not file_path.exists():
        raise DataLoadError(f"필수 데이터 파일이 없습니다: {file_name}")

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"{file_name} JSON 형식이 올바르지 않습니다.") from exc

    if not isinstance(payload, list):
        raise DataLoadError(f"{file_name} 최상위 값은 배열이어야 합니다.")

    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise DataLoadError(f"{file_name} {index}번째 항목은 객체여야 합니다.")
        missing_keys = sorted(required_keys - set(record))
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise DataLoadError(f"{file_name} {index}번째 항목에 필수 키가 없습니다: {missing}")

    return payload


def _parse_product(row: dict[str, str], file_name: str, line_number: int) -> Product:
    return Product(
        product_id=_required_text(row, "product_id", file_name, line_number),
        brand=_required_text(row, "brand", file_name, line_number),
        name=_required_text(row, "name", file_name, line_number),
        category=_required_text(row, "category", file_name, line_number),
        skin_type_tags=_split_values(row.get("skin_type_tags", "")),
        thumbnail_url=_optional_text(row.get("thumbnail_url")),
        image_urls=_split_values(row.get("image_urls", "")),
        functional_review_text=_optional_text(row.get("functional_review_text")),
        functional_cosmetic_status=_optional_text(row.get("functional_cosmetic_status")),
        functional_cosmetic_claims=_split_values(row.get("functional_cosmetic_claims", "")),
        functional_claim_confidence=_optional_text(row.get("functional_claim_confidence")),
        functional_claim_basis=_optional_text(row.get("functional_claim_basis")),
    )


def _parse_product_price(row: dict[str, str], file_name: str, line_number: int) -> ProductPrice:
    return ProductPrice(
        product_id=_required_text(row, "product_id", file_name, line_number),
        mall_name=_required_text(row, "mall_name", file_name, line_number),
        price=_required_int(row, "price", file_name, line_number),
        product_url=_required_text(row, "product_url", file_name, line_number),
        is_lowest=_required_bool(row, "is_lowest", file_name, line_number),
        currency=_optional_text(row.get("currency")) or "KRW",
    )


def _parse_product_image_asset(row: dict[str, str], file_name: str, line_number: int) -> ProductImageAsset:
    image_type = _required_text(row, "image_type", file_name, line_number)
    if image_type not in {"thumbnail", "detail"}:
        raise DataLoadError(f"{file_name}:{line_number} image_type은 thumbnail 또는 detail이어야 합니다.")
    return ProductImageAsset(
        product_id=_required_text(row, "product_id", file_name, line_number),
        image_type=image_type,
        display_order=_required_int(row, "display_order", file_name, line_number),
        storage_key=_required_text(row, "storage_key", file_name, line_number),
    )


def _parse_product_inventory(row: dict[str, str], file_name: str, line_number: int) -> ProductInventory:
    sales_status = _required_text(row, "sales_status", file_name, line_number)
    if sales_status not in SALES_STATUS_VALUES:
        allowed = ", ".join(sorted(SALES_STATUS_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} sales_status는 {allowed} 중 하나여야 합니다.")
    return ProductInventory(
        product_id=_required_text(row, "product_id", file_name, line_number),
        stock_quantity=_required_non_negative_int(row, "stock_quantity", file_name, line_number),
        sales_status=sales_status,
        safety_stock=_required_non_negative_int(row, "safety_stock", file_name, line_number),
        inventory_source=_required_text(row, "inventory_source", file_name, line_number),
    )


def _parse_product_ingredient(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> ProductIngredient:
    confidence = _required_text(row, "content_confidence", file_name, line_number)
    if confidence not in CONTENT_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(CONTENT_CONFIDENCE_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} content_confidence는 {allowed} 중 하나여야 합니다.")
    concentration_confidence = _required_text(row, "concentration_confidence", file_name, line_number)
    if concentration_confidence not in CONCENTRATION_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(CONCENTRATION_CONFIDENCE_VALUES))
        raise DataLoadError(
            f"{file_name}:{line_number} concentration_confidence는 {allowed} 중 하나여야 합니다."
        )

    return ProductIngredient(
        product_id=_required_text(row, "product_id", file_name, line_number),
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        ingredient_name=_required_text(row, "ingredient_name", file_name, line_number),
        content_confidence=confidence,
        display_order=_required_int(row, "display_order", file_name, line_number),
        concentration_text=_optional_text(row.get("concentration_text")),
        concentration_value=_optional_float(
            row.get("concentration_value"),
            "concentration_value",
            file_name,
            line_number,
        ),
        concentration_unit=_optional_text(row.get("concentration_unit")),
        concentration_confidence=concentration_confidence,
        normalized_concentration_value=_optional_float(
            row.get("normalized_concentration_value"),
            "normalized_concentration_value",
            file_name,
            line_number,
        ),
        normalized_concentration_unit=_optional_text(row.get("normalized_concentration_unit")),
    )


def _parse_product_skin_profile(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> ProductSkinProfile:
    confidence = _required_text(row, "confidence", file_name, line_number)
    if confidence not in PROFILE_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(PROFILE_CONFIDENCE_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} confidence는 {allowed} 중 하나여야 합니다.")

    return ProductSkinProfile(
        product_id=_required_text(row, "product_id", file_name, line_number),
        dry_fit=_required_unit_score(row, "dry_fit", file_name, line_number),
        oily_fit=_required_unit_score(row, "oily_fit", file_name, line_number),
        combination_fit=_required_unit_score(row, "combination_fit", file_name, line_number),
        normal_fit=_required_unit_score(row, "normal_fit", file_name, line_number),
        dehydrated_oily_fit=_required_unit_score(row, "dehydrated_oily_fit", file_name, line_number),
        sensitive_fit=_required_unit_score(row, "sensitive_fit", file_name, line_number),
        sensitivity_tag=_required_text(row, "sensitivity_tag", file_name, line_number),
        confidence=confidence,
        reason=_optional_text(row.get("reason")) or "",
    )


def _parse_ingredient(row: dict[str, str], file_name: str, line_number: int) -> Ingredient:
    return Ingredient(
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        name_ko=_required_text(row, "name_ko", file_name, line_number),
        name_en=_optional_text(row.get("name_en")) or "",
        description=_optional_text(row.get("description")) or "",
        source_url=_optional_text(row.get("source_url")),
    )


def _parse_ingredient_alias(row: dict[str, str], file_name: str, line_number: int) -> IngredientAlias:
    alias_type = _required_text(row, "alias_type", file_name, line_number)
    if alias_type not in ALIAS_TYPE_VALUES:
        allowed = ", ".join(sorted(ALIAS_TYPE_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} alias_type은 {allowed} 중 하나여야 합니다.")

    confidence = _canonical_alias_confidence(_required_text(row, "confidence", file_name, line_number))
    if confidence not in ALIAS_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted((*ALIAS_CONFIDENCE_VALUES, *ALIAS_CONFIDENCE_ALIASES)))
        raise DataLoadError(f"{file_name}:{line_number} confidence는 {allowed} 중 하나여야 합니다.")

    return IngredientAlias(
        ingredient_id=_required_text(row, "canonical_id", file_name, line_number),
        alias=_required_text(row, "alias", file_name, line_number),
        alias_type=alias_type,
        confidence=confidence,
        source=_optional_text(row.get("source")) or "",
    )


def _parse_ingredient_effect(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> IngredientEffect:
    return IngredientEffect(
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        effect_id=_required_text(row, "effect_id", file_name, line_number),
        effect_name=_required_text(row, "effect_name", file_name, line_number),
        effect_score=_required_int(row, "effect_score", file_name, line_number),
    )


def _parse_ingredient_effect_range(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> IngredientEffectRange:
    range_confidence = _required_text(row, "range_confidence", file_name, line_number)
    if range_confidence not in RANGE_CONFIDENCE_VALUES:
        allowed = ", ".join(sorted(RANGE_CONFIDENCE_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} range_confidence는 {allowed} 중 하나여야 합니다.")

    # range_confidence가 unknown이면 농도 근거가 없는 행 → 범위 값 공란 허용 (중립 처리 대상)
    if range_confidence == "unknown":
        meaningful_min = _optional_float(row.get("meaningful_min"), "meaningful_min", file_name, line_number)
        optimal_min = _optional_float(row.get("optimal_min"), "optimal_min", file_name, line_number)
        optimal_max = _optional_float(row.get("optimal_max"), "optimal_max", file_name, line_number)
    else:
        meaningful_min = _required_float_from_row(row, "meaningful_min", file_name, line_number)
        optimal_min = _required_float_from_row(row, "optimal_min", file_name, line_number)
        optimal_max = _required_float_from_row(row, "optimal_max", file_name, line_number)

    return IngredientEffectRange(
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        effect_id=_required_text(row, "effect_id", file_name, line_number),
        unit=_required_text(row, "unit", file_name, line_number),
        meaningful_min=meaningful_min,
        optimal_min=optimal_min,
        optimal_max=optimal_max,
        excessive_min=_optional_float(row.get("excessive_min"), "excessive_min", file_name, line_number),
        range_confidence=range_confidence,
        source_type=_required_text(row, "source_type", file_name, line_number),
        source_url=_optional_text(row.get("source_url")),
        note=_optional_text(row.get("note")) or "",
    )


def _parse_ingredient_evidence(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> IngredientEvidence:
    evidence_level = _required_text(row, "evidence_level", file_name, line_number)
    if evidence_level not in EVIDENCE_LEVEL_VALUES:
        allowed = ", ".join(sorted(EVIDENCE_LEVEL_VALUES))
        raise DataLoadError(f"{file_name}:{line_number} evidence_level은 {allowed} 중 하나여야 합니다.")

    return IngredientEvidence(
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        effect_id=_required_text(row, "effect_id", file_name, line_number),
        evidence_level=evidence_level,
        evidence_score=_required_int(row, "evidence_score", file_name, line_number),
        source_title=_required_text(row, "source_title", file_name, line_number),
        source_url=_optional_text(row.get("source_url")),
        summary=_required_text(row, "summary", file_name, line_number),
        source_type=_optional_text(row.get("source_type")),
        pmid=_optional_text(row.get("pmid")),
        doi=_optional_text(row.get("doi")),
        source_authority_score=_optional_float(
            row.get("source_authority_score"),
            "source_authority_score",
            file_name,
            line_number,
        ),
    )


def _parse_risk_flag(row: dict[str, str], file_name: str, line_number: int) -> RiskFlag:
    return RiskFlag(
        ingredient_id=_required_text(row, "ingredient_id", file_name, line_number),
        risk_type=_required_text(row, "risk_type", file_name, line_number),
        display_text=_required_text(row, "display_text", file_name, line_number),
        severity=_required_text(row, "severity", file_name, line_number),
        severity_score=_optional_float(row.get("severity_score"), "severity_score", file_name, line_number),
        applies_to=_split_values(row.get("applies_to", "")),
        condition=_optional_text(row.get("condition")),
        source_type=_optional_text(row.get("source_type")),
        source_url=_optional_text(row.get("source_url")),
    )


def _parse_search_document(
    row: dict[str, str],
    file_name: str,
    line_number: int,
) -> SearchDocument:
    return SearchDocument(
        doc_id=_required_text(row, "doc_id", file_name, line_number),
        source_type=_required_text(row, "source_type", file_name, line_number),
        source_id=_required_text(row, "source_id", file_name, line_number),
        text=_required_text(row, "text", file_name, line_number),
    )


def _validate_catalog(catalog: DataCatalog) -> None:
    product_ids = {product.product_id for product in catalog.products}
    ingredient_ids = {ingredient.ingredient_id for ingredient in catalog.ingredients}
    effect_ids = {effect.effect_id for effect in catalog.ingredient_effects}
    tag_ids = {tag.tag_id for tag in catalog.concern_tags}

    _validate_references(
        "product_prices.csv",
        "product_id",
        (price.product_id for price in catalog.product_prices),
        product_ids,
    )
    _validate_references(
        "product_image_assets.csv",
        "product_id",
        (image.product_id for image in catalog.product_image_assets),
        product_ids,
    )
    _validate_references(
        "product_inventory.csv",
        "product_id",
        (inventory.product_id for inventory in catalog.product_inventories),
        product_ids,
    )
    _validate_references(
        "product_ingredients.csv",
        "product_id",
        (ingredient.product_id for ingredient in catalog.product_ingredients),
        product_ids,
    )
    _validate_references(
        "product_skin_profiles.csv",
        "product_id",
        (profile.product_id for profile in catalog.product_skin_profiles),
        product_ids,
    )
    _validate_references(
        "product_ingredients.csv",
        "ingredient_id",
        (ingredient.ingredient_id for ingredient in catalog.product_ingredients),
        ingredient_ids,
    )
    _validate_references(
        "ingredient_aliases.csv",
        "canonical_id",
        (alias.ingredient_id for alias in catalog.ingredient_aliases),
        ingredient_ids,
    )
    _validate_alias_conflicts(catalog.ingredient_aliases)
    _validate_references(
        "ingredient_effect.csv",
        "ingredient_id",
        (effect.ingredient_id for effect in catalog.ingredient_effects),
        ingredient_ids,
    )
    _validate_references(
        "ingredient_effect_ranges.csv",
        "ingredient_id",
        (effect_range.ingredient_id for effect_range in catalog.ingredient_effect_ranges),
        ingredient_ids,
    )
    _validate_references(
        "ingredient_effect_ranges.csv",
        "effect_id",
        (effect_range.effect_id for effect_range in catalog.ingredient_effect_ranges),
        effect_ids,
    )
    _validate_references(
        "ingredient_evidence.csv",
        "ingredient_id",
        (evidence.ingredient_id for evidence in catalog.ingredient_evidence),
        ingredient_ids,
    )
    _validate_references(
        "ingredient_evidence.csv",
        "effect_id",
        (evidence.effect_id for evidence in catalog.ingredient_evidence),
        effect_ids,
    )
    _validate_references(
        "risk_flags.csv",
        "ingredient_id",
        (risk_flag.ingredient_id for risk_flag in catalog.risk_flags),
        ingredient_ids,
    )
    _validate_references(
        "concern_to_effect.json",
        "tag_id",
        (effect.tag_id for effect in catalog.concern_effects),
        tag_ids,
    )


def _validate_references(
    file_name: str,
    field_name: str,
    values: Iterable[str],
    allowed_values: set[str],
) -> None:
    missing_values = sorted({value for value in values if value not in allowed_values})
    if missing_values:
        missing = ", ".join(missing_values)
        raise DataLoadError(f"{file_name}의 {field_name} 참조를 찾을 수 없습니다: {missing}")


def _validate_alias_conflicts(ingredient_aliases: tuple[IngredientAlias, ...]) -> None:
    owners_by_alias: dict[str, str] = {}
    for alias in ingredient_aliases:
        normalized_alias = _normalize_alias(alias.alias)
        owner = owners_by_alias.get(normalized_alias)
        if owner is not None and owner != alias.ingredient_id:
            raise DataLoadError(
                "ingredient_aliases.csv의 alias가 둘 이상의 canonical_id에 매핑됩니다: "
                f"{alias.alias}"
            )
        owners_by_alias[normalized_alias] = alias.ingredient_id


def _normalize_alias(value: str) -> str:
    return "".join(value.casefold().split())


def _canonical_alias_confidence(value: str) -> str:
    normalized_value = value.casefold().strip()
    return ALIAS_CONFIDENCE_ALIASES.get(normalized_value, normalized_value)


def _required_text(row: dict, key: str, file_name: str, line_number: int) -> str:
    value = _optional_text(row.get(key))
    if value is None:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값이 비어 있습니다.")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_int(row: dict[str, str], key: str, file_name: str, line_number: int) -> int:
    value = _optional_int(row.get(key), key, file_name, line_number)
    if value is None:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값이 비어 있습니다.")
    return value


def _required_non_negative_int(row: dict[str, str], key: str, file_name: str, line_number: int) -> int:
    value = _required_int(row, key, file_name, line_number)
    if value < 0:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값은 0 이상이어야 합니다.")
    return value


def _required_unit_score(row: dict[str, str], key: str, file_name: str, line_number: int) -> float:
    value = _optional_float(row.get(key), key, file_name, line_number)
    if value is None:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값이 비어 있습니다.")
    if not 0.0 <= value <= 1.0:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값은 0.0~1.0 사이여야 합니다.")
    return value


def _required_float_from_row(row: dict[str, str], key: str, file_name: str, line_number: int) -> float:
    value = _optional_float(row.get(key), key, file_name, line_number)
    if value is None:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값이 비어 있습니다.")
    return value


def _required_bool(row: dict[str, str], key: str, file_name: str, line_number: int) -> bool:
    value = _required_text(row, key, file_name, line_number).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise DataLoadError(f"{file_name}:{line_number} {key} 값은 true 또는 false여야 합니다.")


def _optional_int(value: object, key: str, file_name: str, line_number: int) -> int | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값은 정수여야 합니다.") from exc


def _optional_float(value: object, key: str, file_name: str, line_number: int) -> float | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise DataLoadError(f"{file_name}:{line_number} {key} 값은 숫자여야 합니다.") from exc


def _required_float(record: dict, key: str, file_name: str, index: int) -> float:
    value = record.get(key)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DataLoadError(f"{file_name} {index}번째 항목의 {key} 값은 숫자여야 합니다.") from exc


def _required_list(record: dict, key: str, file_name: str, index: int) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DataLoadError(f"{file_name} {index}번째 항목의 {key} 값은 문자열 배열이어야 합니다.")
    return [item.strip() for item in value if item.strip()]


def _split_values(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(";") if item.strip())
