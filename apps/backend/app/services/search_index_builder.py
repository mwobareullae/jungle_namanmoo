from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductSkinProfile
from app.db.models.search import SearchDocument
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect, RiskFlag


DOCUMENT_CODE_PREFIX = "idx_prod_join_"
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class ProductSearchIndexBuildResult:
    scanned: int
    upserted: int
    unchanged: int
    pending_ingredients_skipped: int
    dry_run: bool
    document_code_prefix: str = DOCUMENT_CODE_PREFIX

    def __str__(self) -> str:
        return (
            "ProductSearchIndexBuildResult("
            f"scanned={self.scanned}, "
            f"upserted={self.upserted}, "
            f"unchanged={self.unchanged}, "
            f"pending_ingredients_skipped={self.pending_ingredients_skipped}, "
            f"dry_run={self.dry_run}, "
            f"document_code_prefix='{self.document_code_prefix}'"
            ")"
        )


@dataclass(frozen=True)
class _ProductRow:
    product: Product
    brand: Brand
    category: ProductCategory
    skin_profile: ProductSkinProfile | None


@dataclass
class _IngredientFeature:
    name_ko: str
    name_en: str | None
    ingredient_code: str
    display_name: str
    content_confidence: str | None
    display_order: int | None
    concentration_text: str | None
    normalized_concentration_value: Decimal | None
    normalized_concentration_unit: str | None
    concentration_confidence: str | None
    effects: set[str]
    effect_codes: set[str]
    risk_texts: set[str]
    risk_types: set[str]


@dataclass(frozen=True)
class _BuiltSearchDocument:
    document_code: str
    product_db_id: int
    title: str
    content: str
    keywords: str


def build_product_search_index_documents(
    session: Session,
    *,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> ProductSearchIndexBuildResult:
    """Build product join search documents without changing the scoring formula."""

    scanned = 0
    upserted = 0
    unchanged = 0
    pending_ingredients_skipped = 0
    last_product_id = 0
    remaining = limit

    while remaining is None or remaining > 0:
        current_batch_size = max(1, batch_size)
        if remaining is not None:
            current_batch_size = min(current_batch_size, remaining)

        product_rows = _load_product_batch(
            session,
            last_product_id=last_product_id,
            batch_size=current_batch_size,
        )
        if not product_rows:
            break

        scanned += len(product_rows)
        if remaining is not None:
            remaining -= len(product_rows)
        last_product_id = product_rows[-1].product.id

        ingredient_features_result = _load_ingredient_features_by_product_id(
            session,
            [product_row.product.id for product_row in product_rows],
        )
        pending_ingredients_skipped += ingredient_features_result.pending_ingredients_skipped
        built_documents = _build_documents(
            product_rows,
            ingredient_features_by_product_id=ingredient_features_result.features_by_product_id,
        )
        existing_documents = _load_existing_documents(session, [document.document_code for document in built_documents])

        for built_document in built_documents:
            existing_document = existing_documents.get(built_document.document_code)
            if existing_document is not None and _document_is_unchanged(existing_document, built_document):
                unchanged += 1
                continue
            upserted += 1
            if dry_run:
                continue
            _upsert_document(session, built_document, existing_document)

        if not dry_run:
            session.flush()

    return ProductSearchIndexBuildResult(
        scanned=scanned,
        upserted=upserted,
        unchanged=unchanged,
        pending_ingredients_skipped=pending_ingredients_skipped,
        dry_run=dry_run,
    )


def _load_product_batch(
    session: Session,
    *,
    last_product_id: int,
    batch_size: int,
) -> list[_ProductRow]:
    rows = session.execute(
        select(Product, Brand, ProductCategory, ProductSkinProfile)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(ProductSkinProfile, ProductSkinProfile.product_id == Product.id)
        .where(Product.is_active.is_(True), Product.id > last_product_id)
        .order_by(Product.id.asc())
        .limit(batch_size)
    ).all()
    return [
        _ProductRow(
            product=product,
            brand=brand,
            category=category,
            skin_profile=skin_profile,
        )
        for product, brand, category, skin_profile in rows
    ]


@dataclass(frozen=True)
class _IngredientFeaturesResult:
    features_by_product_id: dict[int, list[_IngredientFeature]]
    pending_ingredients_skipped: int


def _load_ingredient_features_by_product_id(
    session: Session,
    product_db_ids: list[int],
) -> _IngredientFeaturesResult:
    if not product_db_ids:
        return _IngredientFeaturesResult(features_by_product_id={}, pending_ingredients_skipped=0)

    rows = session.execute(
        select(ProductIngredient, Ingredient, IngredientEffect, Effect)
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .outerjoin(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .outerjoin(Effect, IngredientEffect.effect_id == Effect.id)
        .where(ProductIngredient.product_id.in_(product_db_ids))
        .order_by(ProductIngredient.product_id.asc(), ProductIngredient.display_order.asc(), ProductIngredient.id.asc())
    ).all()

    features_by_product_id: dict[int, dict[int, _IngredientFeature]] = {}
    ingredient_db_ids: set[int] = set()
    pending_ingredients_skipped = 0
    for product_ingredient, ingredient, ingredient_effect, effect in rows:
        if _is_pending_ingredient_code(ingredient.ingredient_code):
            pending_ingredients_skipped += 1
            continue
        ingredient_db_ids.add(ingredient.id)
        product_features = features_by_product_id.setdefault(product_ingredient.product_id, {})
        feature = product_features.get(ingredient.id)
        if feature is None:
            feature = _IngredientFeature(
                name_ko=ingredient.name_ko,
                name_en=ingredient.name_en,
                ingredient_code=ingredient.ingredient_code,
                display_name=product_ingredient.ingredient_name or ingredient.name_ko,
                content_confidence=product_ingredient.content_confidence,
                display_order=product_ingredient.display_order,
                concentration_text=product_ingredient.concentration_text,
                normalized_concentration_value=product_ingredient.normalized_concentration_value,
                normalized_concentration_unit=product_ingredient.normalized_concentration_unit,
                concentration_confidence=product_ingredient.concentration_confidence,
                effects=set(),
                effect_codes=set(),
                risk_texts=set(),
                risk_types=set(),
            )
            product_features[ingredient.id] = feature
        if ingredient_effect is not None and effect is not None:
            feature.effects.add(effect.name)
            feature.effect_codes.add(effect.effect_code)

    risk_flags_by_ingredient_id = _load_risk_flags_by_ingredient_id(session, ingredient_db_ids)
    for product_features in features_by_product_id.values():
        for ingredient_id, feature in product_features.items():
            for risk_flag in risk_flags_by_ingredient_id.get(ingredient_id, ()):
                feature.risk_texts.add(risk_flag.display_text)
                feature.risk_types.add(risk_flag.risk_type)

    return _IngredientFeaturesResult(
        features_by_product_id={
            product_id: sorted(
                product_features.values(),
                key=lambda feature: (
                    feature.display_order is None,
                    feature.display_order or 0,
                    feature.ingredient_code,
                ),
            )
            for product_id, product_features in features_by_product_id.items()
        },
        pending_ingredients_skipped=pending_ingredients_skipped,
    )


def _is_pending_ingredient_code(ingredient_code: str) -> bool:
    return ingredient_code.startswith(("ing_pending_", "foreign_pending_"))


def _load_risk_flags_by_ingredient_id(
    session: Session,
    ingredient_db_ids: set[int],
) -> dict[int, tuple[RiskFlag, ...]]:
    if not ingredient_db_ids:
        return {}

    rows = session.execute(
        select(RiskFlag)
        .where(RiskFlag.ingredient_id.in_(ingredient_db_ids))
        .order_by(RiskFlag.ingredient_id.asc(), RiskFlag.id.asc())
    ).scalars()

    risk_flags_by_ingredient_id: dict[int, list[RiskFlag]] = {}
    for risk_flag in rows:
        risk_flags_by_ingredient_id.setdefault(risk_flag.ingredient_id, []).append(risk_flag)

    return {
        ingredient_id: tuple(risk_flags)
        for ingredient_id, risk_flags in risk_flags_by_ingredient_id.items()
    }


def _build_documents(
    product_rows: list[_ProductRow],
    *,
    ingredient_features_by_product_id: dict[int, list[_IngredientFeature]],
) -> list[_BuiltSearchDocument]:
    return [
        _build_document(
            product_row,
            ingredient_features=ingredient_features_by_product_id.get(product_row.product.id, []),
        )
        for product_row in product_rows
    ]


def _build_document(
    product_row: _ProductRow,
    *,
    ingredient_features: list[_IngredientFeature],
) -> _BuiltSearchDocument:
    product = product_row.product
    document_code = f"{DOCUMENT_CODE_PREFIX}{product.product_code}"[:80]
    title = f"{product_row.brand.name} {product.product_name}".strip()

    content_parts = [
        f"상품명: {product.product_name}",
        f"브랜드: {product_row.brand.name}",
        f"카테고리: {product_row.category.name} ({product_row.category.category_code})",
    ]
    if product.skin_type_tags:
        content_parts.append(f"피부 태그: {product.skin_type_tags}")
    if product.description:
        content_parts.append(f"상품 설명: {product.description}")
    if product.functional_cosmetic_status:
        content_parts.append(f"기능성 상태: {product.functional_cosmetic_status}")
    if product.functional_cosmetic_claims:
        content_parts.append(f"기능성 클레임: {product.functional_cosmetic_claims}")
    if product.functional_claim_basis:
        content_parts.append(f"기능성 근거: {product.functional_claim_basis}")
    if product_row.skin_profile is not None:
        content_parts.append(_format_skin_profile(product_row.skin_profile))
    if ingredient_features:
        content_parts.append(_format_ingredient_summary(ingredient_features))

    keywords = _join_unique_terms(
        (
            product.product_code,
            product.product_name,
            product_row.brand.name,
            product_row.brand.brand_code,
            product_row.category.name,
            product_row.category.category_code,
            *(product.skin_type_tags or "").split(";"),
            *(product.functional_cosmetic_claims or "").split(";"),
            *(feature.display_name for feature in ingredient_features),
            *(feature.name_ko for feature in ingredient_features),
            *(feature.name_en or "" for feature in ingredient_features),
            *(feature.ingredient_code for feature in ingredient_features),
            *(effect for feature in ingredient_features for effect in sorted(feature.effects)),
            *(effect_code for feature in ingredient_features for effect_code in sorted(feature.effect_codes)),
            *(risk_type for feature in ingredient_features for risk_type in sorted(feature.risk_types)),
        )
    )

    return _BuiltSearchDocument(
        document_code=document_code,
        product_db_id=product.id,
        title=title,
        content="\n".join(part for part in content_parts if part),
        keywords=keywords,
    )


def _format_skin_profile(skin_profile: ProductSkinProfile) -> str:
    values = {
        "건성": skin_profile.dry_fit,
        "지성": skin_profile.oily_fit,
        "복합성": skin_profile.combination_fit,
        "중성": skin_profile.normal_fit,
        "수부지": skin_profile.dehydrated_oily_fit,
        "민감": skin_profile.sensitive_fit,
    }
    ranked_profiles = sorted(
        values.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    profile_text = ", ".join(f"{label} {float(score):.2f}" for label, score in ranked_profiles)
    extra_parts = [
        f"피부 적합도: {profile_text}",
    ]
    if skin_profile.sensitivity_tag:
        extra_parts.append(f"민감도 태그: {skin_profile.sensitivity_tag}")
    if skin_profile.reason:
        extra_parts.append(f"피부 적합 근거: {skin_profile.reason}")
    return "\n".join(extra_parts)


def _format_ingredient_summary(ingredient_features: list[_IngredientFeature]) -> str:
    lines = ["성분 조인 요약:"]
    for feature in ingredient_features:
        detail_parts = [feature.display_name]
        if feature.name_en:
            detail_parts.append(feature.name_en)
        if feature.effects:
            detail_parts.append("효능 " + ", ".join(sorted(feature.effects)))
        concentration = _format_concentration(feature)
        if concentration:
            detail_parts.append(concentration)
        if feature.content_confidence:
            detail_parts.append(f"성분 신뢰도 {feature.content_confidence}")
        if feature.risk_texts:
            detail_parts.append("주의 " + " / ".join(sorted(feature.risk_texts)))
        lines.append("- " + " | ".join(detail_parts))
    return "\n".join(lines)


def _format_concentration(feature: _IngredientFeature) -> str | None:
    if feature.concentration_text:
        return f"함량 단서 {feature.concentration_text}"
    if feature.normalized_concentration_value is not None and feature.normalized_concentration_unit:
        return f"함량 단서 {feature.normalized_concentration_value:g}{feature.normalized_concentration_unit}"
    if feature.concentration_confidence:
        return f"함량 신뢰도 {feature.concentration_confidence}"
    return None


def _load_existing_documents(
    session: Session,
    document_codes: list[str],
) -> dict[str, SearchDocument]:
    if not document_codes:
        return {}
    documents = session.execute(
        select(SearchDocument).where(SearchDocument.document_code.in_(document_codes))
    ).scalars()
    return {
        document.document_code: document
        for document in documents
    }


def _document_is_unchanged(
    existing_document: SearchDocument,
    built_document: _BuiltSearchDocument,
) -> bool:
    return (
        existing_document.document_type == "product"
        and existing_document.product_id == built_document.product_db_id
        and existing_document.ingredient_id is None
        and existing_document.ingredient_evidence_id is None
        and existing_document.title == built_document.title
        and existing_document.content == built_document.content
        and (existing_document.keywords or "") == built_document.keywords
    )


def _upsert_document(
    session: Session,
    built_document: _BuiltSearchDocument,
    existing_document: SearchDocument | None,
) -> None:
    if existing_document is None:
        session.add(
            SearchDocument(
                document_code=built_document.document_code,
                document_type="product",
                product_id=built_document.product_db_id,
                ingredient_id=None,
                ingredient_evidence_id=None,
                title=built_document.title,
                content=built_document.content,
                keywords=built_document.keywords,
            )
        )
        return

    existing_document.document_type = "product"
    existing_document.product_id = built_document.product_db_id
    existing_document.ingredient_id = None
    existing_document.ingredient_evidence_id = None
    existing_document.title = built_document.title
    existing_document.content = built_document.content
    existing_document.keywords = built_document.keywords
    existing_document.embedding = None
    existing_document.embedding_model = None
    existing_document.embedding_dimensions = None
    existing_document.embedding_updated_at = None


def _join_unique_terms(values: tuple[str | None, ...]) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        term = str(value).strip()
        if not term:
            continue
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    return " ".join(terms)
