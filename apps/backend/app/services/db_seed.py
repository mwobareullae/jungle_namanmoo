from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import math
import os
from pathlib import Path
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.catalog import (
    Brand as BrandRow,
    BrandAlias as BrandAliasRow,
    Product as ProductRow,
    ProductCategory as ProductCategoryRow,
    ProductCategoryAlias as ProductCategoryAliasRow,
    ProductImage as ProductImageRow,
    ProductIngredient as ProductIngredientRow,
    ProductPrice as ProductPriceRow,
    ProductSkinProfile as ProductSkinProfileRow,
)
from app.db.models.commerce import Inventory as InventoryRow
from app.db.models.commerce import InventoryMovement as InventoryMovementRow
from app.db.models.commerce import ProductPopularityMetric as ProductPopularityMetricRow
from app.db.models.commerce import Seller as SellerRow
from app.db.models.search import SearchDocument as SearchDocumentRow
from app.db.models.taxonomy import (
    Concern as ConcernRow,
    ConcernAlias as ConcernAliasRow,
    ConcernEffect as ConcernEffectRow,
    Effect as EffectRow,
    Ingredient as IngredientRow,
    IngredientAlias as IngredientAliasRow,
    IngredientEffect as IngredientEffectRow,
    IngredientEffectRange as IngredientEffectRangeRow,
    IngredientEvidence as IngredientEvidenceRow,
    RiskFlag as RiskFlagRow,
)
from app.models.data_contract import DataCatalog
from app.services.data_loader import count_csv_records, iter_product_ingredients, load_data_catalog


@dataclass(frozen=True)
class SeedResult:
    concerns: int
    effects: int
    ingredients: int
    ingredient_aliases: int
    brands: int
    categories: int
    sellers: int
    products: int
    inventories: int
    popularity_metrics: int
    product_ingredients: int
    product_skin_profiles: int
    ingredient_effect_ranges: int
    ingredient_evidence: int
    search_documents: int


ModelT = TypeVar("ModelT")
POPULARITY_WINDOW_DAYS = 7
MOCK_POPULARITY_SCORE_VERSION = "mock_market_signals_v1"
BAYESIAN_RATING_CONFIDENCE_REVIEWS = 50.0
SEED_PROGRESS_INTERVAL_ROWS = 10_000
SEED_PRODUCT_INGREDIENT_BATCH_SIZE = max(1, int(os.getenv("SEED_PRODUCT_INGREDIENT_BATCH_SIZE", "10000")))
SEED_PHASE_COUNT = 7
PRODUCT_INGREDIENT_UPSERT_COLUMNS = (
    "ingredient_name",
    "content_confidence",
    "display_order",
    "concentration_text",
    "concentration_value",
    "concentration_unit",
    "concentration_confidence",
    "normalized_concentration_value",
    "normalized_concentration_unit",
)


def seed_database(session: Session, data_dir: str | Path) -> SeedResult:
    started_at = current_time()
    data_dir_path = Path(data_dir)
    catalog: DataCatalog | None = None
    try:
        catalog = load_data_catalog(data_dir_path, include_product_ingredients=False)
        row_counts = _catalog_row_counts(catalog, data_dir=data_dir_path)
        log_performance_event(
            "seed_catalog_loaded",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "data_dir": str(data_dir_path),
                "row_counts": row_counts,
                "loaded_row_count": sum(row_counts.values()),
            },
        )
        result = seed_catalog(session, catalog, data_dir=str(data_dir_path))
    except Exception as exc:
        metadata: dict[str, object] = {
            "data_dir": str(data_dir_path),
            "error": type(exc).__name__,
            "error_count": 1,
            "failed_row_sample_count": 0,
        }
        if catalog is not None:
            metadata["row_counts"] = _catalog_row_counts(catalog, data_dir=data_dir_path)
        log_performance_event(
            "seed_database_failed",
            duration_ms=elapsed_ms(started_at),
            metadata=metadata,
        )
        raise

    row_counts = _catalog_row_counts(catalog, data_dir=data_dir_path)
    seed_counts = asdict(result)
    log_performance_event(
        "seed_database_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "data_dir": str(data_dir_path),
            "row_counts": row_counts,
            "loaded_row_count": sum(row_counts.values()),
            "seed_counts": seed_counts,
            "seeded_entity_count": sum(seed_counts.values()),
            "error_count": 0,
            "failed_row_sample_count": 0,
            "counting_mode": "loaded_rows_and_final_seed_counts",
        },
    )
    return result


def seed_catalog(session: Session, catalog: DataCatalog, *, data_dir: str | None = None) -> SeedResult:
    phase_started_at = current_time()
    effects_by_code = _seed_effects(session, catalog)
    concerns_by_code = _seed_concerns(session, catalog)
    _seed_concern_effects(session, catalog, concerns_by_code, effects_by_code)
    _log_seed_phase_completed(
        "taxonomy",
        1,
        phase_started_at,
        data_dir=data_dir,
        row_count=len(catalog.concern_tags) + len(catalog.concern_effects),
        concerns_count=len(catalog.concern_tags),
        effects_count=len(effects_by_code),
    )

    phase_started_at = current_time()
    ingredients_by_code = _seed_ingredients(session, catalog)
    ingredient_alias_count = _seed_ingredient_aliases(session, catalog, ingredients_by_code)
    _seed_ingredient_effects(session, catalog, ingredients_by_code, effects_by_code)
    _seed_ingredient_effect_ranges(session, catalog, ingredients_by_code, effects_by_code)
    evidence_rows = _seed_ingredient_evidence(session, catalog, ingredients_by_code, effects_by_code)
    _seed_risk_flags(session, catalog, ingredients_by_code)
    _log_seed_phase_completed(
        "ingredients",
        2,
        phase_started_at,
        data_dir=data_dir,
        row_count=(
            len(catalog.ingredients)
            + len(catalog.ingredient_aliases)
            + len(catalog.ingredient_effects)
            + len(catalog.ingredient_effect_ranges)
            + len(catalog.ingredient_evidence)
            + len(catalog.risk_flags)
        ),
        ingredients_count=len(catalog.ingredients),
        ingredient_aliases_count=ingredient_alias_count,
        ingredient_evidence_count=len(catalog.ingredient_evidence),
    )

    phase_started_at = current_time()
    brands_by_name = _seed_brands(session, catalog)
    categories_by_code = _seed_categories(session, catalog)
    default_seller = _seed_default_seller(session)
    products_by_code = _seed_products(session, catalog, brands_by_name, categories_by_code, default_seller)
    _seed_product_images(session, catalog, products_by_code)
    _seed_product_prices(session, catalog, products_by_code)
    _log_seed_phase_completed(
        "product_catalog",
        3,
        phase_started_at,
        data_dir=data_dir,
        row_count=len(catalog.products) + len(catalog.product_image_assets) + len(catalog.product_prices),
        products_count=len(catalog.products),
        brands_count=len(brands_by_name),
        categories_count=len(categories_by_code),
        image_assets_count=len(catalog.product_image_assets),
        prices_count=len(catalog.product_prices),
    )

    phase_started_at = current_time()
    inventory_count = _seed_product_inventories(session, catalog, products_by_code)
    popularity_metric_count = _seed_product_popularity_metrics(session, catalog, products_by_code)
    _log_seed_phase_completed(
        "commerce_seed",
        4,
        phase_started_at,
        data_dir=data_dir,
        row_count=len(catalog.product_inventories) + len(catalog.product_market_signals),
        inventories_count=inventory_count,
        popularity_metrics_count=popularity_metric_count,
    )

    phase_started_at = current_time()
    product_ingredient_total_row_count = _product_ingredient_row_count(catalog, data_dir)
    product_ingredient_count = _seed_product_ingredients(
        session,
        catalog,
        products_by_code,
        ingredients_by_code,
        total_row_count=product_ingredient_total_row_count,
        data_dir=data_dir,
    )
    _log_seed_phase_completed(
        "product_ingredients",
        5,
        phase_started_at,
        data_dir=data_dir,
        row_count=product_ingredient_total_row_count,
        product_ingredients_count=product_ingredient_count,
    )

    phase_started_at = current_time()
    _seed_product_skin_profiles(session, catalog, products_by_code)
    _log_seed_phase_completed(
        "product_skin_profiles",
        6,
        phase_started_at,
        data_dir=data_dir,
        row_count=len(catalog.product_skin_profiles),
        product_skin_profiles_count=len(catalog.product_skin_profiles),
    )

    phase_started_at = current_time()
    _seed_search_documents(session, catalog, products_by_code, ingredients_by_code, evidence_rows)
    _log_seed_phase_completed(
        "search_documents",
        7,
        phase_started_at,
        data_dir=data_dir,
        row_count=len(catalog.search_documents),
        search_documents_count=len(catalog.search_documents),
    )

    return SeedResult(
        concerns=len(catalog.concern_tags),
        effects=len(effects_by_code),
        ingredients=len(catalog.ingredients),
        ingredient_aliases=ingredient_alias_count,
        brands=len(brands_by_name),
        categories=len(categories_by_code),
        sellers=1,
        products=len(catalog.products),
        inventories=inventory_count,
        popularity_metrics=popularity_metric_count,
        product_ingredients=product_ingredient_count,
        product_skin_profiles=len(catalog.product_skin_profiles),
        ingredient_effect_ranges=len(catalog.ingredient_effect_ranges),
        ingredient_evidence=len(catalog.ingredient_evidence),
        search_documents=len(catalog.search_documents),
    )


def _catalog_row_counts(catalog: DataCatalog, *, data_dir: str | Path | None = None) -> dict[str, int]:
    return {
        "products.csv": len(catalog.products),
        "product_prices.csv": len(catalog.product_prices),
        "product_image_assets.csv": len(catalog.product_image_assets),
        "product_inventory.csv": len(catalog.product_inventories),
        "product_market_signals.csv": len(catalog.product_market_signals),
        "product_ingredients.csv": _product_ingredient_row_count(catalog, data_dir),
        "product_skin_profiles.csv": len(catalog.product_skin_profiles),
        "ingredients.csv": len(catalog.ingredients),
        "ingredient_aliases.csv": len(catalog.ingredient_aliases),
        "ingredient_effect.csv": len(catalog.ingredient_effects),
        "ingredient_effect_ranges.csv": len(catalog.ingredient_effect_ranges),
        "ingredient_evidence.csv": len(catalog.ingredient_evidence),
        "risk_flags.csv": len(catalog.risk_flags),
        "vector_docs.csv": len(catalog.search_documents),
        "tags.json.concerns": len(catalog.concern_tags),
        "tags.json.concern_effects": len(catalog.concern_effects),
    }


def _product_ingredient_row_count(catalog: DataCatalog, data_dir: str | Path | None) -> int:
    if catalog.product_ingredients:
        return len(catalog.product_ingredients)
    if data_dir is None:
        return 0
    return count_csv_records(data_dir, "product_ingredients.csv")


def _log_seed_phase_completed(
    phase: str,
    phase_order: int,
    started_at: float,
    *,
    data_dir: str | None,
    **metadata: object,
) -> None:
    log_metadata = {
        "phase": phase,
        "phase_order": phase_order,
        "phase_count": SEED_PHASE_COUNT,
        **metadata,
    }
    if data_dir is not None:
        log_metadata["data_dir"] = data_dir
    log_performance_event(
        "seed_phase_completed",
        duration_ms=elapsed_ms(started_at),
        metadata=log_metadata,
    )


def _seed_effects(session: Session, catalog: DataCatalog) -> dict[str, EffectRow]:
    effect_names: dict[str, str] = {}
    for concern_effect in catalog.concern_effects:
        effect_names[concern_effect.effect_id] = concern_effect.effect_name
    for ingredient_effect in catalog.ingredient_effects:
        effect_names[ingredient_effect.effect_id] = ingredient_effect.effect_name
    for evidence in catalog.ingredient_evidence:
        effect_names.setdefault(evidence.effect_id, evidence.effect_id)

    effects_by_code: dict[str, EffectRow] = {}
    for effect_code, name in sorted(effect_names.items()):
        effect = _one_or_none(session, EffectRow, EffectRow.effect_code == effect_code)
        if effect is None:
            effect = EffectRow(effect_code=effect_code, name=name)
            session.add(effect)
        else:
            effect.name = name
            effect.is_active = True
        effects_by_code[effect_code] = effect

    session.flush()
    return effects_by_code


def _seed_concerns(session: Session, catalog: DataCatalog) -> dict[str, ConcernRow]:
    concerns_by_code: dict[str, ConcernRow] = {}
    for tag in catalog.concern_tags:
        concern = _one_or_none(session, ConcernRow, ConcernRow.concern_code == tag.tag_id)
        if concern is None:
            concern = ConcernRow(concern_code=tag.tag_id, name=tag.name)
            session.add(concern)
        else:
            concern.name = tag.name
            concern.is_active = True
        concerns_by_code[tag.tag_id] = concern

    session.flush()

    for tag in catalog.concern_tags:
        concern = concerns_by_code[tag.tag_id]
        aliases = _unique_aliases((tag.name, *tag.synonyms))
        for alias in aliases:
            normalized_alias = _normalize_text(alias)
            row = _one_or_none(
                session,
                ConcernAliasRow,
                ConcernAliasRow.concern_id == concern.id,
                ConcernAliasRow.normalized_alias == normalized_alias,
            )
            if row is None:
                session.add(
                    ConcernAliasRow(
                        concern_id=concern.id,
                        alias=alias,
                        normalized_alias=normalized_alias,
                    )
                )
            else:
                row.alias = alias

    session.flush()
    return concerns_by_code


def _seed_concern_effects(
    session: Session,
    catalog: DataCatalog,
    concerns_by_code: dict[str, ConcernRow],
    effects_by_code: dict[str, EffectRow],
) -> None:
    for record in catalog.concern_effects:
        concern = concerns_by_code[record.tag_id]
        effect = effects_by_code[record.effect_id]
        row = _one_or_none(
            session,
            ConcernEffectRow,
            ConcernEffectRow.concern_id == concern.id,
            ConcernEffectRow.effect_id == effect.id,
        )
        if row is None:
            session.add(
                ConcernEffectRow(
                    concern_id=concern.id,
                    effect_id=effect.id,
                    weight=Decimal(str(record.weight)),
                )
            )
        else:
            row.weight = Decimal(str(record.weight))
    session.flush()


def _seed_ingredients(session: Session, catalog: DataCatalog) -> dict[str, IngredientRow]:
    ingredients_by_code: dict[str, IngredientRow] = {}
    for ingredient in catalog.ingredients:
        row = _one_or_none(
            session,
            IngredientRow,
            IngredientRow.ingredient_code == ingredient.ingredient_id,
        )
        if row is None:
            row = IngredientRow(
                ingredient_code=ingredient.ingredient_id,
                name_ko=ingredient.name_ko,
                name_en=ingredient.name_en or None,
                normalized_name=_normalize_text(ingredient.name_ko),
                description=ingredient.description or None,
                source_url=ingredient.source_url,
            )
            session.add(row)
        else:
            row.name_ko = ingredient.name_ko
            row.name_en = ingredient.name_en or None
            row.normalized_name = _normalize_text(ingredient.name_ko)
            row.description = ingredient.description or None
            row.source_url = ingredient.source_url
            row.is_active = True
        ingredients_by_code[ingredient.ingredient_id] = row

    session.flush()
    return ingredients_by_code


def _seed_ingredient_aliases(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
) -> int:
    missing_ingredient_ids = sorted(
        {
            record.ingredient_id
            for record in catalog.ingredient_aliases
            if record.ingredient_id not in ingredients_by_code
        }
    )
    if missing_ingredient_ids:
        missing = ", ".join(missing_ingredient_ids)
        raise ValueError(f"ingredient_aliases.csv의 canonical_id 참조를 찾을 수 없습니다: {missing}")

    seen_normalized_aliases: set[str] = set()
    for record in catalog.ingredient_aliases:
        ingredient = ingredients_by_code[record.ingredient_id]
        normalized_alias = _normalize_text(record.alias)
        if normalized_alias in seen_normalized_aliases:
            continue
        seen_normalized_aliases.add(normalized_alias)
        row = _one_or_none(
            session,
            IngredientAliasRow,
            IngredientAliasRow.normalized_alias == normalized_alias,
        )
        values = {
            "ingredient_id": ingredient.id,
            "alias": record.alias,
            "alias_type": record.alias_type,
            "confidence": record.confidence,
            "source": record.source or None,
        }
        if row is None:
            session.add(
                IngredientAliasRow(
                    normalized_alias=normalized_alias,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)

    session.flush()
    return len({_normalize_text(record.alias) for record in catalog.ingredient_aliases})


def _seed_ingredient_effects(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
    effects_by_code: dict[str, EffectRow],
) -> None:
    for record in catalog.ingredient_effects:
        ingredient = ingredients_by_code[record.ingredient_id]
        effect = effects_by_code[record.effect_id]
        row = _one_or_none(
            session,
            IngredientEffectRow,
            IngredientEffectRow.ingredient_id == ingredient.id,
            IngredientEffectRow.effect_id == effect.id,
        )
        if row is None:
            session.add(
                IngredientEffectRow(
                    ingredient_id=ingredient.id,
                    effect_id=effect.id,
                    effect_score=Decimal(str(record.effect_score)),
                )
            )
        else:
            row.effect_score = Decimal(str(record.effect_score))
    session.flush()


def _seed_ingredient_effect_ranges(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
    effects_by_code: dict[str, EffectRow],
) -> None:
    for record in catalog.ingredient_effect_ranges:
        ingredient = ingredients_by_code[record.ingredient_id]
        effect = effects_by_code[record.effect_id]
        row = _one_or_none(
            session,
            IngredientEffectRangeRow,
            IngredientEffectRangeRow.ingredient_id == ingredient.id,
            IngredientEffectRangeRow.effect_id == effect.id,
            IngredientEffectRangeRow.unit == record.unit,
        )
        values = {
            "meaningful_min": _decimal_or_none(record.meaningful_min),
            "optimal_min": _decimal_or_none(record.optimal_min),
            "optimal_max": _decimal_or_none(record.optimal_max),
            "excessive_min": _decimal_or_none(record.excessive_min),
            "range_confidence": record.range_confidence,
            "source_type": record.source_type,
            "source_url": record.source_url,
            "note": record.note,
        }
        if row is None:
            session.add(
                IngredientEffectRangeRow(
                    ingredient_id=ingredient.id,
                    effect_id=effect.id,
                    unit=record.unit,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()


def _seed_ingredient_evidence(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
    effects_by_code: dict[str, EffectRow],
) -> dict[tuple[str, str], IngredientEvidenceRow]:
    evidence_rows: dict[tuple[str, str], IngredientEvidenceRow] = {}
    for record in catalog.ingredient_evidence:
        ingredient = ingredients_by_code[record.ingredient_id]
        effect = effects_by_code[record.effect_id]
        row = _one_or_none(
            session,
            IngredientEvidenceRow,
            IngredientEvidenceRow.ingredient_id == ingredient.id,
            IngredientEvidenceRow.effect_id == effect.id,
            IngredientEvidenceRow.source_title == record.source_title,
        )
        if row is None:
            row = IngredientEvidenceRow(
                ingredient_id=ingredient.id,
                effect_id=effect.id,
                evidence_level=record.evidence_level,
                evidence_score=Decimal(str(record.evidence_score)),
                source_title=record.source_title,
                source_url=record.source_url,
                summary=record.summary,
                source_type=record.source_type,
                pmid=record.pmid,
                doi=record.doi,
                source_authority_score=_decimal_or_none(record.source_authority_score),
            )
            session.add(row)
        else:
            row.evidence_level = record.evidence_level
            row.evidence_score = Decimal(str(record.evidence_score))
            row.source_url = record.source_url
            row.summary = record.summary
            row.source_type = record.source_type
            row.pmid = record.pmid
            row.doi = record.doi
            row.source_authority_score = _decimal_or_none(record.source_authority_score)
        evidence_rows[(record.ingredient_id, record.effect_id)] = row

    session.flush()
    return evidence_rows


def _seed_risk_flags(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
) -> None:
    alias_to_canonical = _ingredient_alias_canonical_map(catalog)
    ingredient_names_by_code = {
        ingredient.ingredient_id: (ingredient.name_ko, ingredient.name_en)
        for ingredient in catalog.ingredients
    }
    seen_keys: set[tuple[int, str, str]] = set()
    for record in catalog.risk_flags:
        for ingredient_code in _risk_flag_ingredient_codes(
            record.ingredient_id,
            ingredient_names_by_code,
            alias_to_canonical,
        ):
            ingredient = ingredients_by_code[ingredient_code]
            key = (ingredient.id, record.risk_type, record.display_text)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            rows = session.execute(
                select(RiskFlagRow).where(
                    RiskFlagRow.ingredient_id == ingredient.id,
                    RiskFlagRow.risk_type == record.risk_type,
                    RiskFlagRow.display_text == record.display_text,
                )
            ).scalars().all()

            if not rows:
                session.add(
                    RiskFlagRow(
                        ingredient_id=ingredient.id,
                        risk_type=record.risk_type,
                        display_text=record.display_text,
                        severity=record.severity,
                        severity_score=_decimal_or_none(record.severity_score),
                        applies_to=_join_values(record.applies_to),
                        condition=record.condition,
                        source_type=record.source_type,
                        source_url=record.source_url,
                    )
                )
            else:
                row = rows[0]
                for duplicate in rows[1:]:
                    session.delete(duplicate)
                row.severity = record.severity
                row.severity_score = _decimal_or_none(record.severity_score)
                row.applies_to = _join_values(record.applies_to)
                row.condition = record.condition
                row.source_type = record.source_type
                row.source_url = record.source_url
    session.flush()


def _seed_brands(session: Session, catalog: DataCatalog) -> dict[str, BrandRow]:
    brands_by_name: dict[str, BrandRow] = {}
    brand_names_by_code: dict[str, set[str]] = {}
    for product in catalog.products:
        brand_names_by_code.setdefault(_normalize_text(product.brand), set()).add(product.brand)

    brands_by_code: dict[str, BrandRow] = {}
    for brand_code, brand_names in sorted(brand_names_by_code.items()):
        display_name = _pick_display_name(brand_names)
        row = _one_or_none(session, BrandRow, BrandRow.brand_code == brand_code)
        if row is None:
            row = BrandRow(
                brand_code=brand_code,
                name=display_name,
                normalized_name=brand_code,
            )
            session.add(row)
        else:
            row.name = display_name
            row.normalized_name = brand_code
            row.is_active = True
        brands_by_code[brand_code] = row

    session.flush()

    for brand_code, brand_names in brand_names_by_code.items():
        brand = brands_by_code[brand_code]
        seen_normalized_aliases: set[str] = set()
        for brand_name in brand_names:
            brands_by_name[brand_name] = brand
            normalized_alias = _normalize_text(brand_name)
            if normalized_alias in seen_normalized_aliases:
                continue
            seen_normalized_aliases.add(normalized_alias)
            alias = _one_or_none(
                session,
                BrandAliasRow,
                BrandAliasRow.brand_id == brand.id,
                BrandAliasRow.normalized_alias == normalized_alias,
            )
            if alias is None:
                session.add(
                    BrandAliasRow(
                        brand_id=brand.id,
                        alias=brand_name,
                        normalized_alias=normalized_alias,
                    )
                )
            else:
                alias.alias = brand_name
    session.flush()
    return brands_by_name


def _seed_categories(session: Session, catalog: DataCatalog) -> dict[str, ProductCategoryRow]:
    categories_by_code: dict[str, ProductCategoryRow] = {}
    category_codes = sorted({product.category for product in catalog.products})
    for category_code in category_codes:
        normalized_code = _normalize_text(category_code)
        row = _one_or_none(
            session,
            ProductCategoryRow,
            ProductCategoryRow.category_code == normalized_code,
        )
        if row is None:
            row = ProductCategoryRow(
                category_code=normalized_code,
                name=category_code,
            )
            session.add(row)
        else:
            row.name = category_code
            row.is_active = True
        categories_by_code[category_code] = row

    session.flush()

    for category_code, category in categories_by_code.items():
        normalized_alias = _normalize_text(category_code)
        alias = _one_or_none(
            session,
            ProductCategoryAliasRow,
            ProductCategoryAliasRow.category_id == category.id,
            ProductCategoryAliasRow.normalized_alias == normalized_alias,
        )
        if alias is None:
            session.add(
                ProductCategoryAliasRow(
                    category_id=category.id,
                    alias=category_code,
                    normalized_alias=normalized_alias,
                )
            )
        else:
            alias.alias = category_code
    session.flush()
    return categories_by_code


def _seed_default_seller(session: Session) -> SellerRow:
    seller = _one_or_none(session, SellerRow, SellerRow.seller_code == "mwobareullae")
    if seller is None:
        seller = SellerRow(
            seller_code="mwobareullae",
            display_name="뭐바를래",
            seller_type="FIRST_PARTY",
            status="ACTIVE",
        )
        session.add(seller)
    else:
        seller.display_name = "뭐바를래"
        seller.seller_type = "FIRST_PARTY"
        seller.status = "ACTIVE"
    session.flush()
    return seller


def _seed_products(
    session: Session,
    catalog: DataCatalog,
    brands_by_name: dict[str, BrandRow],
    categories_by_code: dict[str, ProductCategoryRow],
    default_seller: SellerRow,
) -> dict[str, ProductRow]:
    products_by_code: dict[str, ProductRow] = {}
    for product in catalog.products:
        brand = brands_by_name[product.brand]
        category = categories_by_code[product.category]
        row = _one_or_none(session, ProductRow, ProductRow.product_code == product.product_id)
        skin_type_tags = _join_values(product.skin_type_tags)
        functional_claims = _join_values(product.functional_cosmetic_claims)
        if row is None:
            row = ProductRow(
                product_code=product.product_id,
                seller_id=default_seller.id,
                brand_id=brand.id,
                category_id=category.id,
                product_name=product.name,
                skin_type_tags=skin_type_tags,
                thumbnail_url=product.thumbnail_url,
                functional_review_text=product.functional_review_text,
                functional_cosmetic_status=product.functional_cosmetic_status,
                functional_cosmetic_claims=functional_claims,
                functional_claim_confidence=product.functional_claim_confidence,
                functional_claim_basis=product.functional_claim_basis,
                is_recommendable=product.is_recommendable,
                recommend_exclude_reason=product.recommend_exclude_reason,
            )
            session.add(row)
        else:
            row.seller_id = default_seller.id
            row.brand_id = brand.id
            row.category_id = category.id
            row.product_name = product.name
            row.skin_type_tags = skin_type_tags
            row.thumbnail_url = product.thumbnail_url
            row.functional_review_text = product.functional_review_text
            row.functional_cosmetic_status = product.functional_cosmetic_status
            row.functional_cosmetic_claims = functional_claims
            row.functional_claim_confidence = product.functional_claim_confidence
            row.functional_claim_basis = product.functional_claim_basis
            row.is_recommendable = product.is_recommendable
            row.recommend_exclude_reason = product.recommend_exclude_reason
            row.is_active = True
        products_by_code[product.product_id] = row

    session.flush()
    return products_by_code


def _seed_product_images(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> None:
    if catalog.product_image_assets:
        existing_rows = session.execute(select(ProductImageRow)).scalars()
        pending_by_storage_key = {(row.product_id, row.storage_key): row for row in existing_rows}
        pending_by_slot_key = {
            (row.product_id, row.image_type, row.display_order): row
            for row in pending_by_storage_key.values()
        }
        for image in catalog.product_image_assets:
            product_row = products_by_code[image.product_id]
            storage_key = (product_row.id, image.storage_key)
            slot_key = (product_row.id, image.image_type, image.display_order)
            row = pending_by_storage_key.get(storage_key) or pending_by_slot_key.get(slot_key)
            values = {
                "image_type": image.image_type,
                "storage_key": image.storage_key,
                "display_order": image.display_order,
            }
            if row is None:
                row = ProductImageRow(
                    product_id=product_row.id,
                    **values,
                )
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            pending_by_storage_key[storage_key] = row
            pending_by_slot_key[slot_key] = row
        session.flush()
        return

    for product in catalog.products:
        product_row = products_by_code[product.product_id]
        for display_order, image_url in enumerate(product.image_urls, 1):
            row = _one_or_none(
                session,
                ProductImageRow,
                ProductImageRow.product_id == product_row.id,
                ProductImageRow.storage_key == image_url,
            )
            if row is None:
                session.add(
                    ProductImageRow(
                        product_id=product_row.id,
                        image_type="detail",
                        storage_key=image_url,
                        display_order=display_order,
                    )
                )
            else:
                row.image_type = "detail"
                row.display_order = display_order
    session.flush()


def _seed_product_prices(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> None:
    for price in catalog.product_prices:
        product = products_by_code[price.product_id]
        row = _one_or_none(
            session,
            ProductPriceRow,
            ProductPriceRow.product_id == product.id,
            ProductPriceRow.mall_name == price.mall_name,
            ProductPriceRow.product_url == price.product_url,
        )
        if row is None:
            session.add(
                ProductPriceRow(
                    product_id=product.id,
                    mall_name=price.mall_name,
                    price=price.price,
                    currency=price.currency,
                    product_url=price.product_url,
                    is_lowest=price.is_lowest,
                )
            )
        else:
            row.price = price.price
            row.currency = price.currency
            row.is_lowest = price.is_lowest
    session.flush()


def _seed_product_inventories(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> int:
    for inventory in catalog.product_inventories:
        product = products_by_code[inventory.product_id]
        row = _one_or_none(session, InventoryRow, InventoryRow.product_id == product.id)
        if row is None:
            row = InventoryRow(
                product_id=product.id,
                stock_quantity=inventory.stock_quantity,
                reserved_quantity=0,
                safety_stock=inventory.safety_stock,
                sales_status=inventory.sales_status,
                inventory_source=inventory.inventory_source,
            )
            session.add(row)
            session.flush()
            session.add(
                InventoryMovementRow(
                    inventory_id=row.id,
                    product_id=product.id,
                    movement_type="SEED",
                    quantity_delta=inventory.stock_quantity,
                    stock_after=inventory.stock_quantity,
                    reason="product_inventory.csv seed",
                    reference_type="product_inventory",
                    reference_id=product.product_code,
                )
            )
            continue

        quantity_delta = inventory.stock_quantity - row.stock_quantity
        row.stock_quantity = inventory.stock_quantity
        row.safety_stock = inventory.safety_stock
        row.sales_status = inventory.sales_status
        row.inventory_source = inventory.inventory_source
        if quantity_delta:
            session.add(
                InventoryMovementRow(
                    inventory_id=row.id,
                    product_id=product.id,
                    movement_type="SEED_ADJUST",
                    quantity_delta=quantity_delta,
                    stock_after=inventory.stock_quantity,
                    reason="product_inventory.csv seed update",
                    reference_type="product_inventory",
                    reference_id=product.product_code,
                )
            )
    session.flush()
    return len(catalog.product_inventories)


def _seed_product_popularity_metrics(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> int:
    signals = [signal for signal in catalog.product_market_signals if _has_market_signal(signal)]
    if not signals:
        return 0

    context = _build_market_popularity_context(signals)
    existing_rows = session.execute(
        select(ProductPopularityMetricRow).where(
            ProductPopularityMetricRow.window_days == POPULARITY_WINDOW_DAYS,
            ProductPopularityMetricRow.product_id.in_([products_by_code[signal.product_id].id for signal in signals]),
        )
    ).scalars()
    existing_by_product_id = {row.product_id: row for row in existing_rows}
    computed_at = datetime.now(timezone.utc)

    for signal in signals:
        product = products_by_code[signal.product_id]
        popularity_score = _market_popularity_score(signal, context)
        row = existing_by_product_id.get(product.id)
        values = {
            "window_days": POPULARITY_WINDOW_DAYS,
            "view_count": signal.recent_view_count,
            "click_count": 0,
            "cart_add_count": signal.cart_add_count,
            "order_count": signal.sales_count,
            "units_sold": signal.sales_count,
            "review_count": signal.review_count,
            "average_rating": _decimal_or_none(signal.average_rating),
            "popularity_score": Decimal(str(popularity_score)),
            "score_version": MOCK_POPULARITY_SCORE_VERSION,
            "computed_at": _parse_datetime_or_default(signal.updated_at, computed_at),
        }
        if row is None:
            session.add(ProductPopularityMetricRow(product_id=product.id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)

    session.flush()
    return len(signals)


def _seed_product_ingredients(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
    ingredients_by_code: dict[str, IngredientRow],
    *,
    total_row_count: int,
    data_dir: str | None = None,
) -> int:
    started_at = current_time()
    batch_values: list[dict[str, object]] = []
    seen_pairs: set[tuple[int, int]] = set()
    records = _iter_product_ingredient_records(catalog, data_dir)

    for processed_row_count, record in enumerate(records, 1):
        product = products_by_code[record.product_id]
        ingredient = ingredients_by_code[record.ingredient_id]
        pair = (product.id, ingredient.id)
        if pair in seen_pairs:
            _log_product_ingredient_progress(
                started_at,
                processed_row_count,
                total_row_count,
                len(seen_pairs),
                len(batch_values),
                data_dir=data_dir,
            )
            continue
        seen_pairs.add(pair)

        batch_values.append(
            {
                "product_id": product.id,
                "ingredient_id": ingredient.id,
                "ingredient_name": record.ingredient_name,
                "content_confidence": record.content_confidence,
                "display_order": record.display_order,
                "concentration_text": record.concentration_text,
                "concentration_value": _decimal_or_none(record.concentration_value),
                "concentration_unit": record.concentration_unit,
                "concentration_confidence": record.concentration_confidence,
                "normalized_concentration_value": _decimal_or_none(record.normalized_concentration_value),
                "normalized_concentration_unit": record.normalized_concentration_unit,
            }
        )
        if len(batch_values) >= SEED_PRODUCT_INGREDIENT_BATCH_SIZE:
            _upsert_product_ingredient_batch(session, batch_values)
            batch_values.clear()

        _log_product_ingredient_progress(
            started_at,
            processed_row_count,
            total_row_count,
            len(seen_pairs),
            len(batch_values),
            data_dir=data_dir,
        )
    if batch_values:
        _upsert_product_ingredient_batch(session, batch_values)
    session.flush()
    return len(seen_pairs)


def _iter_product_ingredient_records(catalog: DataCatalog, data_dir: str | None):
    if catalog.product_ingredients:
        return iter(catalog.product_ingredients)
    if data_dir is None:
        return iter(())
    return iter_product_ingredients(data_dir)


def _upsert_product_ingredient_batch(session: Session, values: list[dict[str, object]]) -> None:
    if not values:
        return

    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(ProductIngredientRow)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ProductIngredientRow)
    else:
        _upsert_product_ingredient_batch_orm(session, values)
        return

    statement = statement.on_conflict_do_update(
        index_elements=["product_id", "ingredient_id"],
        set_={column: getattr(statement.excluded, column) for column in PRODUCT_INGREDIENT_UPSERT_COLUMNS},
    )
    session.execute(statement, values)
    session.flush()


def _upsert_product_ingredient_batch_orm(session: Session, values: list[dict[str, object]]) -> None:
    for value in values:
        row = _one_or_none(
            session,
            ProductIngredientRow,
            ProductIngredientRow.product_id == value["product_id"],
            ProductIngredientRow.ingredient_id == value["ingredient_id"],
        )
        if row is None:
            session.add(ProductIngredientRow(**value))
            continue
        for column in PRODUCT_INGREDIENT_UPSERT_COLUMNS:
            setattr(row, column, value[column])
    session.flush()


def _log_product_ingredient_progress(
    started_at: float,
    processed_row_count: int,
    total_row_count: int,
    deduplicated_pair_count: int,
    pending_batch_count: int,
    *,
    data_dir: str | None,
) -> None:
    if not total_row_count or processed_row_count % SEED_PROGRESS_INTERVAL_ROWS != 0:
        return

    metadata: dict[str, object] = {
        "phase": "product_ingredients",
        "processed_row_count": processed_row_count,
        "total_row_count": total_row_count,
        "deduplicated_pair_count": deduplicated_pair_count,
        "progress_percent": round((processed_row_count / total_row_count) * 100, 2),
        "batch_size": SEED_PRODUCT_INGREDIENT_BATCH_SIZE,
        "pending_batch_count": pending_batch_count,
    }
    if data_dir is not None:
        metadata["data_dir"] = data_dir
    log_performance_event(
        "seed_product_ingredients_progress",
        duration_ms=elapsed_ms(started_at),
        metadata=metadata,
    )


def _seed_product_skin_profiles(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> None:
    for record in catalog.product_skin_profiles:
        product = products_by_code[record.product_id]
        row = _one_or_none(
            session,
            ProductSkinProfileRow,
            ProductSkinProfileRow.product_id == product.id,
        )
        values = {
            "dry_fit": _decimal_or_none(record.dry_fit),
            "oily_fit": _decimal_or_none(record.oily_fit),
            "combination_fit": _decimal_or_none(record.combination_fit),
            "normal_fit": _decimal_or_none(record.normal_fit),
            "dehydrated_oily_fit": _decimal_or_none(record.dehydrated_oily_fit),
            "sensitive_fit": _decimal_or_none(record.sensitive_fit),
            "sensitivity_tag": record.sensitivity_tag,
            "confidence": record.confidence,
            "reason": record.reason,
        }
        if row is None:
            session.add(ProductSkinProfileRow(product_id=product.id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()


def _seed_search_documents(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
    ingredients_by_code: dict[str, IngredientRow],
    evidence_rows: dict[tuple[str, str], IngredientEvidenceRow],
) -> None:
    for document in catalog.search_documents:
        product_id = None
        ingredient_id = None
        evidence_id = None
        if document.source_type == "product" and document.source_id in products_by_code:
            product_id = products_by_code[document.source_id].id
        elif document.source_type == "ingredient" and document.source_id in ingredients_by_code:
            ingredient_id = ingredients_by_code[document.source_id].id
        elif document.source_type in {"evidence", "ingredient_evidence"}:
            evidence = evidence_rows.get(_split_evidence_source_id(document.source_id))
            evidence_id = evidence.id if evidence is not None else None

        row = _one_or_none(
            session,
            SearchDocumentRow,
            SearchDocumentRow.document_code == document.doc_id,
        )
        title = _document_title(document.source_type, document.source_id, products_by_code, ingredients_by_code)
        if row is None:
            session.add(
                SearchDocumentRow(
                    document_code=document.doc_id,
                    document_type=document.source_type,
                    product_id=product_id,
                    ingredient_id=ingredient_id,
                    ingredient_evidence_id=evidence_id,
                    title=title,
                    content=document.text,
                    keywords=_normalize_text(document.text),
                )
            )
        else:
            should_reset_embedding = row.title != title or row.content != document.text
            row.document_type = document.source_type
            row.product_id = product_id
            row.ingredient_id = ingredient_id
            row.ingredient_evidence_id = evidence_id
            row.title = title
            row.content = document.text
            row.keywords = _normalize_text(document.text)
            if should_reset_embedding:
                row.embedding = None
                row.embedding_model = None
                row.embedding_dimensions = None
                row.embedding_updated_at = None
    session.flush()


def _document_title(
    source_type: str,
    source_id: str,
    products_by_code: dict[str, ProductRow],
    ingredients_by_code: dict[str, IngredientRow],
) -> str:
    if source_type == "product" and source_id in products_by_code:
        return products_by_code[source_id].product_name
    if source_type == "ingredient" and source_id in ingredients_by_code:
        return ingredients_by_code[source_id].name_ko
    return source_id


def _split_evidence_source_id(source_id: str) -> tuple[str, str]:
    ingredient_id, _, effect_id = source_id.partition(":")
    return ingredient_id, effect_id


def _one_or_none(
    session: Session,
    model: type[ModelT],
    *criteria,
) -> ModelT | None:
    return session.execute(select(model).where(*criteria)).scalar_one_or_none()


def _normalize_text(value: str) -> str:
    return "".join(value.casefold().split())


def _unique_aliases(values: tuple[str, ...]) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in seen:
            aliases.append(value)
            seen.add(normalized)
    return tuple(aliases)


def _pick_display_name(values: set[str]) -> str:
    return sorted(values, key=lambda value: (value.isupper(), len(value), value))[0]


def _ingredient_alias_canonical_map(catalog: DataCatalog) -> dict[str, str]:
    alias_to_canonical: dict[str, str] = {}
    for alias in catalog.ingredient_aliases:
        normalized_alias = _normalize_text(alias.alias)
        if normalized_alias:
            alias_to_canonical[normalized_alias] = alias.ingredient_id
    return alias_to_canonical


def _risk_flag_ingredient_codes(
    ingredient_code: str,
    ingredient_names_by_code: dict[str, tuple[str, str]],
    alias_to_canonical: dict[str, str],
) -> tuple[str, ...]:
    candidate_codes = [ingredient_code]
    names = ingredient_names_by_code.get(ingredient_code, ("", ""))
    for name in names:
        canonical_code = alias_to_canonical.get(_normalize_text(name))
        if canonical_code:
            candidate_codes.append(canonical_code)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate_code in candidate_codes:
        if candidate_code and candidate_code not in seen:
            deduped.append(candidate_code)
            seen.add(candidate_code)
    return tuple(deduped)


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


@dataclass(frozen=True)
class _MarketPopularityContext:
    max_review_count: float
    max_sales_count: float
    max_recent_signal: float
    max_sales_rank: float
    global_rating: float


def _build_market_popularity_context(signals) -> _MarketPopularityContext:
    weighted_ratings = [
        (signal.average_rating, signal.review_count)
        for signal in signals
        if signal.average_rating is not None and signal.average_rating > 0 and signal.review_count > 0
    ]
    rating_weight = sum(weight for _, weight in weighted_ratings)
    global_rating = (
        sum(rating * weight for rating, weight in weighted_ratings) / rating_weight
        if rating_weight
        else 4.0
    )
    return _MarketPopularityContext(
        max_review_count=max((signal.review_count for signal in signals), default=0),
        max_sales_count=max((signal.sales_count for signal in signals), default=0),
        max_recent_signal=max((_recent_signal_value(signal) for signal in signals), default=0),
        max_sales_rank=max((signal.sales_rank or 0 for signal in signals), default=0),
        global_rating=global_rating,
    )


def _has_market_signal(signal) -> bool:
    return (
        signal.review_count > 0
        or (signal.average_rating is not None and signal.average_rating > 0)
        or signal.sales_count > 0
        or signal.sales_rank is not None
        or signal.recent_view_count > 0
        or signal.wishlist_count > 0
        or signal.cart_add_count > 0
    )


def _market_popularity_score(signal, context: _MarketPopularityContext) -> float:
    review_count_score = _log_normalized_score(signal.review_count, context.max_review_count)
    rating_score = _bayesian_rating_score(
        rating=signal.average_rating or 0.0,
        review_count=signal.review_count,
        global_rating=context.global_rating,
    )
    sales_score = _sales_signal_score(signal, context)
    recent_signal_score = _log_normalized_score(_recent_signal_value(signal), context.max_recent_signal)
    return round(
        _weighted_available_score(
            [
                (review_count_score, 0.30, signal.review_count > 0),
                (rating_score, 0.25, signal.average_rating is not None and signal.average_rating > 0),
                (sales_score, 0.30, signal.sales_count > 0 or signal.sales_rank is not None),
                (recent_signal_score, 0.15, _recent_signal_value(signal) > 0),
            ]
        ),
        2,
    )


def _log_normalized_score(value: float, max_value: float) -> float:
    if value <= 0 or max_value <= 0:
        return 0.0
    return 100.0 * math.log1p(value) / math.log1p(max_value)


def _bayesian_rating_score(
    *,
    rating: float,
    review_count: float,
    global_rating: float,
) -> float:
    if rating <= 0:
        return 0.0
    clipped_rating = min(5.0, max(0.0, rating))
    adjusted = (
        review_count / (review_count + BAYESIAN_RATING_CONFIDENCE_REVIEWS) * clipped_rating
        + BAYESIAN_RATING_CONFIDENCE_REVIEWS
        / (review_count + BAYESIAN_RATING_CONFIDENCE_REVIEWS)
        * global_rating
    )
    return adjusted / 5.0 * 100.0


def _sales_signal_score(signal, context: _MarketPopularityContext) -> float:
    if signal.sales_count > 0:
        return _log_normalized_score(signal.sales_count, context.max_sales_count)
    if signal.sales_rank is None:
        return 0.0
    if context.max_sales_rank <= 1:
        return 100.0
    rank_score = 100.0 * (
        1.0 - (math.log1p(signal.sales_rank - 1.0) / math.log1p(context.max_sales_rank - 1.0))
    )
    return min(100.0, max(0.0, rank_score))


def _recent_signal_value(signal) -> float:
    return signal.recent_view_count + signal.wishlist_count * 3.0 + signal.cart_add_count * 5.0


def _weighted_available_score(scores: list[tuple[float, float, bool]]) -> float:
    available = [(score, weight) for score, weight, is_available in scores if is_available]
    weight_sum = sum(weight for _, weight in available)
    if weight_sum <= 0:
        return 0.0
    return sum(score * weight for score, weight in available) / weight_sum


def _parse_datetime_or_default(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return default


def _join_values(values: tuple[str, ...]) -> str | None:
    return ";".join(values) if values else None
