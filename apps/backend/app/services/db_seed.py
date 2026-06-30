from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.db.models.search import SearchDocument as SearchDocumentRow
from app.db.models.taxonomy import (
    Concern as ConcernRow,
    ConcernAlias as ConcernAliasRow,
    ConcernEffect as ConcernEffectRow,
    Effect as EffectRow,
    Ingredient as IngredientRow,
    IngredientEffect as IngredientEffectRow,
    IngredientEffectRange as IngredientEffectRangeRow,
    IngredientEvidence as IngredientEvidenceRow,
    RiskFlag as RiskFlagRow,
)
from app.models.data_contract import DataCatalog
from app.services.data_loader import load_data_catalog


@dataclass(frozen=True)
class SeedResult:
    concerns: int
    effects: int
    ingredients: int
    brands: int
    categories: int
    products: int
    product_ingredients: int
    product_skin_profiles: int
    ingredient_effect_ranges: int
    ingredient_evidence: int
    search_documents: int


ModelT = TypeVar("ModelT")


def seed_database(session: Session, data_dir: str | Path) -> SeedResult:
    catalog = load_data_catalog(data_dir)
    return seed_catalog(session, catalog)


def seed_catalog(session: Session, catalog: DataCatalog) -> SeedResult:
    effects_by_code = _seed_effects(session, catalog)
    concerns_by_code = _seed_concerns(session, catalog)
    _seed_concern_effects(session, catalog, concerns_by_code, effects_by_code)

    ingredients_by_code = _seed_ingredients(session, catalog)
    _seed_ingredient_effects(session, catalog, ingredients_by_code, effects_by_code)
    _seed_ingredient_effect_ranges(session, catalog, ingredients_by_code, effects_by_code)
    evidence_rows = _seed_ingredient_evidence(session, catalog, ingredients_by_code, effects_by_code)
    _seed_risk_flags(session, catalog, ingredients_by_code)

    brands_by_name = _seed_brands(session, catalog)
    categories_by_code = _seed_categories(session, catalog)
    products_by_code = _seed_products(session, catalog, brands_by_name, categories_by_code)
    _seed_product_images(session, catalog, products_by_code)
    _seed_product_prices(session, catalog, products_by_code)
    product_ingredient_count = _seed_product_ingredients(session, catalog, products_by_code, ingredients_by_code)
    _seed_product_skin_profiles(session, catalog, products_by_code)
    _seed_search_documents(session, catalog, products_by_code, ingredients_by_code, evidence_rows)

    return SeedResult(
        concerns=len(catalog.concern_tags),
        effects=len(effects_by_code),
        ingredients=len(catalog.ingredients),
        brands=len(brands_by_name),
        categories=len(categories_by_code),
        products=len(catalog.products),
        product_ingredients=product_ingredient_count,
        product_skin_profiles=len(catalog.product_skin_profiles),
        ingredient_effect_ranges=len(catalog.ingredient_effect_ranges),
        ingredient_evidence=len(catalog.ingredient_evidence),
        search_documents=len(catalog.search_documents),
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
            )
            session.add(row)
        else:
            row.evidence_level = record.evidence_level
            row.evidence_score = Decimal(str(record.evidence_score))
            row.source_url = record.source_url
            row.summary = record.summary
        evidence_rows[(record.ingredient_id, record.effect_id)] = row

    session.flush()
    return evidence_rows


def _seed_risk_flags(
    session: Session,
    catalog: DataCatalog,
    ingredients_by_code: dict[str, IngredientRow],
) -> None:
    for record in catalog.risk_flags:
        ingredient = ingredients_by_code[record.ingredient_id]
        row = _one_or_none(
            session,
            RiskFlagRow,
            RiskFlagRow.ingredient_id == ingredient.id,
            RiskFlagRow.risk_type == record.risk_type,
            RiskFlagRow.display_text == record.display_text,
        )
        if row is None:
            session.add(
                RiskFlagRow(
                    ingredient_id=ingredient.id,
                    risk_type=record.risk_type,
                    display_text=record.display_text,
                    severity=record.severity,
                )
            )
        else:
            row.severity = record.severity
    session.flush()


def _seed_brands(session: Session, catalog: DataCatalog) -> dict[str, BrandRow]:
    brands_by_name: dict[str, BrandRow] = {}
    brand_names = sorted({product.brand for product in catalog.products})
    for brand_name in brand_names:
        normalized_name = _normalize_text(brand_name)
        row = _one_or_none(session, BrandRow, BrandRow.brand_code == normalized_name)
        if row is None:
            row = BrandRow(
                brand_code=normalized_name,
                name=brand_name,
                normalized_name=normalized_name,
            )
            session.add(row)
        else:
            row.name = brand_name
            row.normalized_name = normalized_name
            row.is_active = True
        brands_by_name[brand_name] = row

    session.flush()

    for brand_name, brand in brands_by_name.items():
        normalized_alias = _normalize_text(brand_name)
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


def _seed_products(
    session: Session,
    catalog: DataCatalog,
    brands_by_name: dict[str, BrandRow],
    categories_by_code: dict[str, ProductCategoryRow],
) -> dict[str, ProductRow]:
    products_by_code: dict[str, ProductRow] = {}
    for product in catalog.products:
        brand = brands_by_name[product.brand]
        category = categories_by_code[product.category]
        row = _one_or_none(session, ProductRow, ProductRow.product_code == product.product_id)
        skin_type_tags = _join_values(product.skin_type_tags)
        if row is None:
            row = ProductRow(
                product_code=product.product_id,
                brand_id=brand.id,
                category_id=category.id,
                product_name=product.name,
                skin_type_tags=skin_type_tags,
                thumbnail_url=product.thumbnail_url,
            )
            session.add(row)
        else:
            row.brand_id = brand.id
            row.category_id = category.id
            row.product_name = product.name
            row.skin_type_tags = skin_type_tags
            row.thumbnail_url = product.thumbnail_url
            row.is_active = True
        products_by_code[product.product_id] = row

    session.flush()
    return products_by_code


def _seed_product_images(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
) -> None:
    for product in catalog.products:
        product_row = products_by_code[product.product_id]
        for display_order, image_url in enumerate(product.image_urls, 1):
            row = _one_or_none(
                session,
                ProductImageRow,
                ProductImageRow.product_id == product_row.id,
                ProductImageRow.image_url == image_url,
            )
            if row is None:
                session.add(
                    ProductImageRow(
                        product_id=product_row.id,
                        image_url=image_url,
                        display_order=display_order,
                    )
                )
            else:
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


def _seed_product_ingredients(
    session: Session,
    catalog: DataCatalog,
    products_by_code: dict[str, ProductRow],
    ingredients_by_code: dict[str, IngredientRow],
) -> int:
    seen_pairs: set[tuple[int, int]] = set()
    for record in catalog.product_ingredients:
        product = products_by_code[record.product_id]
        ingredient = ingredients_by_code[record.ingredient_id]
        pair = (product.id, ingredient.id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        row = _one_or_none(
            session,
            ProductIngredientRow,
            ProductIngredientRow.product_id == product.id,
            ProductIngredientRow.ingredient_id == ingredient.id,
        )
        if row is None:
            session.add(
                ProductIngredientRow(
                    product_id=product.id,
                    ingredient_id=ingredient.id,
                    ingredient_name=record.ingredient_name,
                    content_confidence=record.content_confidence,
                    display_order=record.display_order,
                    concentration_text=record.concentration_text,
                    concentration_value=_decimal_or_none(record.concentration_value),
                    concentration_unit=record.concentration_unit,
                    concentration_confidence=record.concentration_confidence,
                    normalized_concentration_value=_decimal_or_none(record.normalized_concentration_value),
                    normalized_concentration_unit=record.normalized_concentration_unit,
                )
            )
        else:
            row.ingredient_name = record.ingredient_name
            row.content_confidence = record.content_confidence
            row.display_order = record.display_order
            row.concentration_text = record.concentration_text
            row.concentration_value = _decimal_or_none(record.concentration_value)
            row.concentration_unit = record.concentration_unit
            row.concentration_confidence = record.concentration_confidence
            row.normalized_concentration_value = _decimal_or_none(record.normalized_concentration_value)
            row.normalized_concentration_unit = record.normalized_concentration_unit
    session.flush()
    return len(seen_pairs)


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


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _join_values(values: tuple[str, ...]) -> str | None:
    return ";".join(values) if values else None
