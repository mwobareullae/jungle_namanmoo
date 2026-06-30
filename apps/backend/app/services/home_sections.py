from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice, ProductSkinProfile
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect, IngredientEvidence
from app.schemas.home import HomeSection, HomeSectionProduct, HomeSectionsResponse


DEFAULT_HOME_LIMIT_PER_SECTION = 8
MAX_HOME_LIMIT_PER_SECTION = 20


@dataclass(frozen=True)
class _ProductBase:
    db_product_id: int
    product_id: str
    brand: str
    category_code: str
    category_name: str
    name: str
    thumbnail_url: str
    lowest_price: int


@dataclass(frozen=True)
class _ProductSignals:
    key_ingredients: tuple[str, ...]
    effects: tuple[str, ...]
    max_effect_score: float
    max_evidence_score: float


@dataclass(frozen=True)
class _SkinProfileSignals:
    dry_fit: float
    oily_fit: float
    combination_fit: float
    normal_fit: float
    dehydrated_oily_fit: float
    sensitive_fit: float


def get_home_sections_response(
    session: Session,
    *,
    skin_type: str = "중성",
    sensitivity: str = "보통",
    category_code: str | None = None,
    limit_per_section: int = DEFAULT_HOME_LIMIT_PER_SECTION,
) -> HomeSectionsResponse:
    normalized_skin_type = _normalize_skin_type(skin_type)
    normalized_sensitivity = _normalize_sensitivity(sensitivity)
    normalized_limit = max(1, min(MAX_HOME_LIMIT_PER_SECTION, limit_per_section))

    products = _load_products(session, category_code=category_code)
    product_ids = [product.db_product_id for product in products]
    signals_by_product_id = _load_product_signals(session, product_ids)
    skin_profiles_by_product_id = _load_skin_profiles(session, product_ids)
    purchase_urls_by_product_id = _load_purchase_urls(session, product_ids)

    sections = [
        _build_section(
            "best_sellers",
            "지금 인기있는 제품",
            "가격, 성분 근거, 데이터 완성도를 함께 본 메인 후보",
            "commerce_rank",
            "home_v0_quality_price_evidence",
            products,
            signals_by_product_id,
            skin_profiles_by_product_id,
            purchase_urls_by_product_id,
            normalized_skin_type,
            normalized_sensitivity,
            normalized_limit,
        ),
        _build_section(
            "evidence_picks",
            "성분 근거가 좋은 제품",
            "효능 성분과 근거 점수가 잘 잡힌 제품",
            "evidence_rank",
            "home_v0_ingredient_evidence",
            products,
            signals_by_product_id,
            skin_profiles_by_product_id,
            purchase_urls_by_product_id,
            normalized_skin_type,
            normalized_sensitivity,
            normalized_limit,
        ),
        _build_section(
            "recommended_for_you",
            "너에게 추천하는 제품",
            "피부 타입과 민감도 기준을 함께 본 맞춤 후보",
            "personalized_rank",
            "home_v0_skin_profile_evidence",
            products,
            signals_by_product_id,
            skin_profiles_by_product_id,
            purchase_urls_by_product_id,
            normalized_skin_type,
            normalized_sensitivity,
            normalized_limit,
        ),
    ]

    return HomeSectionsResponse(
        skin_type=normalized_skin_type,
        sensitivity=normalized_sensitivity,
        category_code=category_code,
        sections=sections,
    )


def _load_products(session: Session, *, category_code: str | None) -> list[_ProductBase]:
    lowest_price = func.min(ProductPrice.price)
    statement = (
        select(
            Product.id,
            Product.product_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            Product.product_name,
            Product.thumbnail_url,
            lowest_price.label("lowest_price"),
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
        .group_by(
            Product.id,
            Product.product_code,
            Brand.name,
            ProductCategory.category_code,
            ProductCategory.name,
            Product.product_name,
            Product.thumbnail_url,
        )
    )
    if category_code:
        statement = statement.where(ProductCategory.category_code == category_code)

    rows = session.execute(statement).all()
    return [
        _ProductBase(
            db_product_id=int(row.id),
            product_id=row.product_code,
            brand=row.brand_name,
            category_code=row.category_code,
            category_name=row.category_name,
            name=row.product_name,
            thumbnail_url=row.thumbnail_url or "",
            lowest_price=int(row.lowest_price or 0),
        )
        for row in rows
    ]


def _load_product_signals(
    session: Session,
    product_ids: list[int],
) -> dict[int, _ProductSignals]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(
            ProductIngredient.product_id,
            Ingredient.name_ko,
            Effect.name,
            IngredientEffect.effect_score,
            IngredientEvidence.evidence_score,
        )
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .outerjoin(IngredientEffect, IngredientEffect.ingredient_id == Ingredient.id)
        .outerjoin(Effect, IngredientEffect.effect_id == Effect.id)
        .outerjoin(
            IngredientEvidence,
            and_(
                IngredientEvidence.ingredient_id == Ingredient.id,
                IngredientEvidence.effect_id == IngredientEffect.effect_id,
            ),
        )
        .where(ProductIngredient.product_id.in_(product_ids))
        .order_by(ProductIngredient.display_order.asc(), ProductIngredient.id.asc())
    ).all()

    ingredients_by_product_id: dict[int, list[str]] = {}
    effects_by_product_id: dict[int, list[str]] = {}
    max_effect_score_by_product_id: dict[int, float] = {}
    max_evidence_score_by_product_id: dict[int, float] = {}

    for product_id, ingredient_name, effect_name, effect_score, evidence_score in rows:
        db_product_id = int(product_id)
        if ingredient_name:
            ingredients_by_product_id.setdefault(db_product_id, []).append(str(ingredient_name))
        if effect_name:
            effects_by_product_id.setdefault(db_product_id, []).append(str(effect_name))
        max_effect_score_by_product_id[db_product_id] = max(
            max_effect_score_by_product_id.get(db_product_id, 0.0),
            _decimal_score_to_unit(effect_score),
        )
        max_evidence_score_by_product_id[db_product_id] = max(
            max_evidence_score_by_product_id.get(db_product_id, 0.0),
            _decimal_score_to_unit(evidence_score),
        )

    return {
        product_id: _ProductSignals(
            key_ingredients=tuple(_dedupe(ingredients_by_product_id.get(product_id, []))[:3]),
            effects=tuple(_dedupe(effects_by_product_id.get(product_id, []))[:3]),
            max_effect_score=max_effect_score_by_product_id.get(product_id, 0.0),
            max_evidence_score=max_evidence_score_by_product_id.get(product_id, 0.0),
        )
        for product_id in product_ids
    }


def _load_skin_profiles(
    session: Session,
    product_ids: list[int],
) -> dict[int, _SkinProfileSignals]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(ProductSkinProfile).where(ProductSkinProfile.product_id.in_(product_ids))
    ).scalars()
    return {
        row.product_id: _SkinProfileSignals(
            dry_fit=_decimal_to_unit(row.dry_fit),
            oily_fit=_decimal_to_unit(row.oily_fit),
            combination_fit=_decimal_to_unit(row.combination_fit),
            normal_fit=_decimal_to_unit(row.normal_fit),
            dehydrated_oily_fit=_decimal_to_unit(row.dehydrated_oily_fit),
            sensitive_fit=_decimal_to_unit(row.sensitive_fit),
        )
        for row in rows
    }


def _load_purchase_urls(session: Session, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}

    rows = session.execute(
        select(ProductPrice.product_id, ProductPrice.product_url)
        .where(ProductPrice.product_id.in_(product_ids))
        .order_by(ProductPrice.product_id.asc(), ProductPrice.is_lowest.desc(), ProductPrice.price.asc())
    ).all()
    urls_by_product_id: dict[int, str] = {}
    for product_id, product_url in rows:
        urls_by_product_id.setdefault(int(product_id), product_url)
    return urls_by_product_id


def _build_section(
    section_id: str,
    title: str,
    subtitle: str,
    section_type: str,
    algorithm: str,
    products: list[_ProductBase],
    signals_by_product_id: dict[int, _ProductSignals],
    skin_profiles_by_product_id: dict[int, _SkinProfileSignals],
    purchase_urls_by_product_id: dict[int, str],
    skin_type: str,
    sensitivity: str,
    limit: int,
) -> HomeSection:
    ranked = sorted(
        (
            (
                _section_score(
                    section_id,
                    product,
                    signals_by_product_id.get(product.db_product_id, _empty_signals()),
                    skin_profiles_by_product_id.get(product.db_product_id),
                    skin_type,
                    sensitivity,
                ),
                product,
            )
            for product in products
        ),
        key=lambda item: (-item[0], item[1].product_id),
    )

    section_products = [
        _build_section_product(
            section_id,
            product,
            signals_by_product_id.get(product.db_product_id, _empty_signals()),
            purchase_urls_by_product_id.get(product.db_product_id),
            score,
        )
        for score, product in ranked[:limit]
    ]
    return HomeSection(
        section_id=section_id,
        title=title,
        subtitle=subtitle,
        section_type=section_type,
        algorithm=algorithm,
        products=section_products,
    )


def _section_score(
    section_id: str,
    product: _ProductBase,
    signals: _ProductSignals,
    skin_profile: _SkinProfileSignals | None,
    skin_type: str,
    sensitivity: str,
) -> float:
    evidence_score = signals.max_evidence_score
    effect_score = signals.max_effect_score
    price_score = _affordability_score(product.lowest_price)
    quality_score = _data_quality_score(product, signals)
    skin_score = _skin_profile_score(skin_profile, skin_type, sensitivity)

    if section_id == "evidence_picks":
        return evidence_score * 0.50 + effect_score * 0.35 + quality_score * 0.15
    if section_id == "recommended_for_you":
        return skin_score * 0.45 + evidence_score * 0.25 + effect_score * 0.20 + price_score * 0.10
    return evidence_score * 0.35 + effect_score * 0.25 + price_score * 0.20 + quality_score * 0.20


def _build_section_product(
    section_id: str,
    product: _ProductBase,
    signals: _ProductSignals,
    purchase_url: str | None,
    score: float,
) -> HomeSectionProduct:
    return HomeSectionProduct(
        product_id=product.product_id,
        brand=product.brand,
        name=product.name,
        category_code=product.category_code,
        category_name=product.category_name,
        thumbnail_url=product.thumbnail_url,
        lowest_price=product.lowest_price,
        original_price=None,
        discount_rate=None,
        purchase_url=purchase_url,
        badges=_build_badges(section_id, score, signals),
        tags=_build_tags(signals),
        reason_summary=_build_reason_summary(section_id, signals, product),
        display_score=_unit_to_percent(score),
    )


def _build_badges(section_id: str, score: float, signals: _ProductSignals) -> list[str]:
    badges: list[str] = []
    if section_id == "best_sellers":
        badges.append("BEST")
    if section_id == "recommended_for_you":
        badges.append("맞춤")
    if signals.max_evidence_score >= 0.8:
        badges.append("근거")
    if score >= 0.75:
        badges.append("추천")
    return _dedupe(badges)[:3]


def _build_tags(signals: _ProductSignals) -> list[str]:
    tags = [*signals.effects[:2], *signals.key_ingredients[:3]]
    return _dedupe(tags)[:4]


def _build_reason_summary(section_id: str, signals: _ProductSignals, product: _ProductBase) -> str:
    primary_effect = signals.effects[0] if signals.effects else ""
    primary_ingredient = signals.key_ingredients[0] if signals.key_ingredients else ""

    if section_id == "recommended_for_you":
        if primary_effect:
            return f"{primary_effect} 근거와 피부 타입 적합도를 함께 본 맞춤 후보예요."
        return "피부 타입 적합도와 상품 정보를 함께 본 맞춤 후보예요."
    if section_id == "evidence_picks":
        if primary_ingredient and primary_effect:
            return f"{primary_ingredient} 성분의 {primary_effect} 근거가 보여 우선 노출했어요."
        return "성분 근거 데이터가 비교적 잘 잡힌 상품이에요."
    if primary_effect:
        return f"{product.category_name} 상품 중 {primary_effect} 근거와 가격 조건을 함께 봤어요."
    return "가격, 이미지, 상품 데이터를 기준으로 메인 노출 후보에 포함했어요."


def _skin_profile_score(
    profile: _SkinProfileSignals | None,
    skin_type: str,
    sensitivity: str,
) -> float:
    if profile is None:
        return 0.5

    skin_scores = {
        "건성": profile.dry_fit,
        "지성": profile.oily_fit,
        "복합성": profile.combination_fit,
        "중성": profile.normal_fit,
        "수부지": profile.dehydrated_oily_fit,
    }
    skin_score = skin_scores.get(skin_type, profile.normal_fit)
    sensitivity_score = profile.sensitive_fit if sensitivity == "민감" else 0.75 + profile.sensitive_fit * 0.25
    return _clamp(skin_score * 0.75 + sensitivity_score * 0.25)


def _affordability_score(price: int) -> float:
    if price <= 0:
        return 0.0
    if price <= 15_000:
        return 1.0
    if price <= 30_000:
        return 0.85
    if price <= 50_000:
        return 0.65
    if price <= 80_000:
        return 0.45
    return 0.30


def _data_quality_score(product: _ProductBase, signals: _ProductSignals) -> float:
    score = 0.4
    if product.thumbnail_url:
        score += 0.25
    if product.lowest_price > 0:
        score += 0.20
    if signals.key_ingredients:
        score += 0.15
    return _clamp(score)


def _normalize_skin_type(value: str | None) -> str:
    if value is None or not value.strip():
        return "중성"
    normalized = value.strip()
    aliases = {
        "보통": "중성",
        "normal": "중성",
        "dry": "건성",
        "oily": "지성",
        "combination": "복합성",
        "dehydrated_oily": "수부지",
    }
    return aliases.get(normalized.casefold(), normalized)


def _normalize_sensitivity(value: str | None) -> str:
    if value is None or not value.strip():
        return "보통"
    normalized = value.strip()
    aliases = {
        "sensitive": "민감",
        "normal": "보통",
    }
    return aliases.get(normalized.casefold(), normalized)


def _empty_signals() -> _ProductSignals:
    return _ProductSignals(
        key_ingredients=(),
        effects=(),
        max_effect_score=0.0,
        max_evidence_score=0.0,
    )


def _decimal_score_to_unit(value: Decimal | float | int | None) -> float:
    number = _decimal_to_float(value)
    if number > 1:
        number /= 100
    return _clamp(number)


def _decimal_to_unit(value: Decimal | float | int | None) -> float:
    return _clamp(_decimal_to_float(value))


def _decimal_to_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _unit_to_percent(value: float) -> int:
    return int(round(_clamp(value) * 100))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result
