from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice, ProductSkinProfile
from app.db.models.commerce import Inventory, ProductPopularityMetric
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect, IngredientEvidence
from app.schemas.home import (
    HomeLayoutResponse,
    HomeLayoutSection,
    HomeProductSectionResponse,
    HomeSection,
    HomeSectionProduct,
)
from app.schemas.product import PopularProductItem
from app.services.popular_products_service import DEFAULT_POPULAR_WINDOW_DAYS, get_popular_product_items
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.product_availability import build_product_availability
from app.services.scoring import (
    BEHAVIOR_AFFINITY_COMPONENT_WEIGHTS,
    BEHAVIOR_NEGATIVE_GUARD_WEIGHT,
    BEHAVIOR_POSITIVE_SOURCE_WEIGHTS,
    BehaviorPersonalizationContext,
    SkinTestScoringContext,
    load_behavior_personalization_context,
    load_skin_test_scoring_context,
)
from app.services.skin_profile_service import load_skin_profile_for_user


DEFAULT_HOME_LIMIT_PER_SECTION = 8
MAX_HOME_LIMIT_PER_SECTION = 20
MAX_HOME_LOOKUP_IDS = 10_000


HOME_LAYOUT_SECTIONS = (
    HomeLayoutSection(
        section_id="market_popular",
        title="지금 인기있는 제품",
        subtitle="최근 행동, 구매, 리뷰 신호를 함께 본 인기 상품",
        section_type="market_popular",
        endpoint="/api/home/market-popular",
    ),
    HomeLayoutSection(
        section_id="evidence_picks",
        title="성분 근거가 좋은 제품",
        subtitle="효능 성분과 근거 점수가 잘 잡힌 제품",
        section_type="evidence_rank",
        endpoint="/api/home/evidence-picks",
    ),
    HomeLayoutSection(
        section_id="for_you",
        title="너를 위한 추천",
        subtitle="피부 프로필과 행동 신호를 함께 본 맞춤 후보",
        section_type="personalized_rank",
        endpoint="/api/home/for-you",
    ),
)

# Keep the personalized section directly below the market-popular section on home.
HOME_LAYOUT_SECTIONS = (HOME_LAYOUT_SECTIONS[0], HOME_LAYOUT_SECTIONS[2], HOME_LAYOUT_SECTIONS[1])


@dataclass(frozen=True)
class _ProductBase:
    db_product_id: int
    product_id: str
    brand: str
    brand_code: str
    category_code: str
    category_name: str
    name: str
    thumbnail_url: str
    lowest_price: int
    sales_status: str
    stock_status: str
    available_quantity: int | None
    in_stock: bool


@dataclass(frozen=True)
class _ProductSignals:
    key_ingredients: tuple[str, ...]
    effects: tuple[str, ...]
    tag_effect: str
    tag_ingredient: str
    ingredient_codes: tuple[str, ...]
    effect_codes: tuple[str, ...]
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


@dataclass(frozen=True)
class _ForYouContext:
    skin_type: str
    sensitivity: str
    request_skin_type: str | None
    request_sensitivity: str | None
    concern: str | None
    effect: str | None
    manual_skin_type: str | None
    manual_sensitivity: str | None
    skin_test_context: SkinTestScoringContext | None
    behavior_context: BehaviorPersonalizationContext | None
    sources: tuple[str, ...]


def get_home_layout_response() -> HomeLayoutResponse:
    return HomeLayoutResponse(sections=list(HOME_LAYOUT_SECTIONS))


def get_market_popular_response(
    session: Session,
    *,
    category_code: str | None = None,
    limit: int = DEFAULT_HOME_LIMIT_PER_SECTION,
) -> HomeProductSectionResponse:
    normalized_limit = _normalize_limit(limit)
    popular_products = get_popular_product_items(
        session,
        window_days=DEFAULT_POPULAR_WINDOW_DAYS,
        limit=normalized_limit,
        category_code=category_code,
        recommendable_only=True,
    )
    return _section_to_response(
        _build_popular_section(popular_products),
        category_code=category_code,
        limit=normalized_limit,
    )


def get_evidence_picks_response(
    session: Session,
    *,
    category_code: str | None = None,
    limit: int = DEFAULT_HOME_LIMIT_PER_SECTION,
) -> HomeProductSectionResponse:
    normalized_limit = _normalize_limit(limit)
    products = _load_products(session, category_code=category_code)
    product_ids = [product.db_product_id for product in products]
    signals_by_product_id = _load_product_signals(session, product_ids)
    purchase_urls_by_product_id = _load_purchase_urls(session, product_ids)
    section = _build_section(
        "evidence_picks",
        "성분 근거가 좋은 제품",
        "효능 성분과 근거 점수가 잘 잡힌 제품",
        "evidence_rank",
        "home_v0_ingredient_evidence",
        products,
        signals_by_product_id,
        {},
        purchase_urls_by_product_id,
        "중성",
        "보통",
        normalized_limit,
    )
    return _section_to_response(section, category_code=category_code, limit=normalized_limit)


def get_for_you_response(
    session: Session,
    *,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    concern: str | None = None,
    effect: str | None = None,
    category_code: str | None = None,
    limit: int = DEFAULT_HOME_LIMIT_PER_SECTION,
    current_user: User | None = None,
) -> HomeProductSectionResponse:
    normalized_limit = _normalize_limit(limit)
    context = _build_for_you_context(
        session,
        current_user=current_user,
        skin_type=skin_type,
        sensitivity=sensitivity,
        concern=concern,
        effect=effect,
    )
    products = _load_products(session, category_code=category_code)
    product_ids = [product.db_product_id for product in products]
    signals_by_product_id = _load_product_signals(session, product_ids)
    skin_profiles_by_product_id = _load_skin_profiles(session, product_ids)
    purchase_urls_by_product_id = _load_purchase_urls(session, product_ids)
    popularity_scores_by_product_id = _load_market_popularity_scores(session, product_ids)

    ranked = sorted(
        (
            (
                _for_you_score(
                    product,
                    signals_by_product_id.get(product.db_product_id, _empty_signals()),
                    skin_profiles_by_product_id.get(product.db_product_id),
                    popularity_scores_by_product_id.get(product.db_product_id),
                    context,
                ),
                product,
            )
            for product in products
        ),
        key=lambda item: (-item[0], item[1].product_id),
    )
    section = HomeSection(
        section_id="for_you",
        title="너를 위한 추천",
        subtitle="피부 프로필과 행동 신호를 함께 본 맞춤 후보",
        section_type="personalized_rank",
        algorithm="home_v1_for_you_personalized",
        products=[
            _build_section_product(
                "recommended_for_you",
                product,
                signals_by_product_id.get(product.db_product_id, _empty_signals()),
                purchase_urls_by_product_id.get(product.db_product_id),
                score,
            )
            for score, product in ranked[:normalized_limit]
        ],
    )
    return _section_to_response(
        section,
        category_code=category_code,
        limit=normalized_limit,
        skin_type=context.skin_type,
        sensitivity=context.sensitivity,
        personalization_sources=context.sources,
    )


def _build_for_you_context(
    session: Session,
    *,
    current_user: User | None,
    skin_type: str | None,
    sensitivity: str | None,
    concern: str | None,
    effect: str | None,
) -> _ForYouContext:
    request_skin_type = _normalize_skin_type_or_none(skin_type)
    request_sensitivity = _normalize_sensitivity_or_none(sensitivity)
    normalized_concern = _normalize_optional_text(concern)
    normalized_effect = _normalize_optional_text(effect)

    saved_profile = load_skin_profile_for_user(session, current_user.id) if current_user is not None else None
    manual_skin_type = _manual_skin_type_from_profile(saved_profile)
    manual_sensitivity = _manual_sensitivity_from_profile(saved_profile)
    skin_test_context = load_skin_test_scoring_context(
        session,
        current_user.id if current_user is not None else None,
    )
    behavior_context = load_behavior_personalization_context(
        session,
        current_user.id if current_user is not None else None,
    )

    resolved_skin_type = (
        request_skin_type
        or manual_skin_type
        or (skin_test_context.mapped_skin_type if skin_test_context is not None else None)
        or "중성"
    )
    resolved_sensitivity = (
        request_sensitivity
        or manual_sensitivity
        or (skin_test_context.mapped_sensitivity if skin_test_context is not None else None)
        or "보통"
    )

    sources: list[str] = []
    if request_skin_type or request_sensitivity or normalized_concern or normalized_effect:
        sources.append("request_context")
    if manual_skin_type or manual_sensitivity:
        sources.append("manual_skin_profile")
    if skin_test_context is not None:
        sources.append("skin_test_context")
    if behavior_context is not None:
        sources.append("behavior_affinity")
    if not sources:
        sources.append("fallback")

    return _ForYouContext(
        skin_type=resolved_skin_type,
        sensitivity=resolved_sensitivity,
        request_skin_type=request_skin_type,
        request_sensitivity=request_sensitivity,
        concern=normalized_concern,
        effect=normalized_effect,
        manual_skin_type=manual_skin_type,
        manual_sensitivity=manual_sensitivity,
        skin_test_context=skin_test_context,
        behavior_context=behavior_context,
        sources=tuple(sources),
    )


def _for_you_score(
    product: _ProductBase,
    signals: _ProductSignals,
    skin_profile: _SkinProfileSignals | None,
    popularity_score: float | None,
    context: _ForYouContext,
) -> float:
    components: list[tuple[float, float]] = []

    manual_score = _manual_profile_fit_score(skin_profile, context)
    if manual_score is not None:
        components.append((manual_score, 0.22))

    behavior_score = _behavior_affinity_score(product, signals, context.behavior_context)
    if behavior_score is not None:
        components.append((behavior_score, 0.22))

    selected_score = _selected_context_fit_score(product, signals, skin_profile, context)
    if selected_score is not None:
        components.append((selected_score, 0.16))

    skin_test_score = _skin_test_context_fit_score(product, signals, skin_profile, context.skin_test_context)
    if skin_test_score is not None:
        components.append((skin_test_score, 0.12))

    components.extend(
        [
            (signals.max_effect_score, 0.10),
            (signals.max_evidence_score, 0.08),
            (_affordability_score(product.lowest_price), 0.04),
        ]
    )
    if popularity_score is not None:
        components.append((popularity_score, 0.06))

    return _weighted_average(tuple(components))


def _manual_profile_fit_score(
    skin_profile: _SkinProfileSignals | None,
    context: _ForYouContext,
) -> float | None:
    if context.manual_skin_type is None and context.manual_sensitivity is None:
        return None
    return _skin_profile_score(
        skin_profile,
        context.manual_skin_type or context.skin_type,
        context.manual_sensitivity or context.sensitivity,
    )


def _selected_context_fit_score(
    product: _ProductBase,
    signals: _ProductSignals,
    skin_profile: _SkinProfileSignals | None,
    context: _ForYouContext,
) -> float | None:
    components: list[tuple[float, float]] = []
    if context.request_skin_type is not None or context.request_sensitivity is not None:
        components.append(
            (
                _skin_profile_score(
                    skin_profile,
                    context.request_skin_type or context.skin_type,
                    context.request_sensitivity or context.sensitivity,
                ),
                0.65,
            )
        )

    desired_terms = _desired_effect_terms(context.concern, context.effect)
    effect_score = _effect_term_match_score(signals, desired_terms)
    if effect_score is not None:
        components.append((effect_score, 0.35))

    if not components:
        return None
    return _weighted_average(tuple(components))


def _skin_test_context_fit_score(
    product: _ProductBase,
    signals: _ProductSignals,
    skin_profile: _SkinProfileSignals | None,
    skin_test_context: SkinTestScoringContext | None,
) -> float | None:
    if skin_test_context is None:
        return None

    components: list[tuple[float, float]] = [
        (
            _soft_context_score(
                _skin_profile_score(
                    skin_profile,
                    skin_test_context.mapped_skin_type,
                    skin_test_context.mapped_sensitivity,
                ),
                _axis_strength(skin_test_context, "OD") or _axis_strength(skin_test_context, "SR"),
            ),
            0.45,
        )
    ]

    category_code = _commerce_code(skin_test_context, "category_preference")
    if category_code:
        category_score = 1.0 if _category_matches_preference(product.category_code, category_code) else 0.35
        components.append((category_score, 0.15))

    pn_terms = ("미백", "톤", "잡티", "색소", "brightening") if _axis_winner(skin_test_context, "PN") == "P" else ()
    pn_score = _effect_term_match_score(signals, pn_terms)
    if pn_score is not None:
        components.append((_soft_context_score(pn_score, _axis_strength(skin_test_context, "PN")), 0.15))

    wt_terms = ("주름", "탄력", "wrinkle") if _axis_winner(skin_test_context, "WT") == "W" else ()
    wt_score = _effect_term_match_score(signals, wt_terms)
    if wt_score is not None:
        components.append((_soft_context_score(wt_score, _axis_strength(skin_test_context, "WT")), 0.15))

    if _axis_winner(skin_test_context, "SR") == "S":
        safety_score = skin_profile.sensitive_fit if skin_profile is not None else 0.5
        components.append((_soft_context_score(safety_score, _axis_strength(skin_test_context, "SR")), 0.10))

    return _weighted_average(tuple(components))


def _behavior_affinity_score(
    product: _ProductBase,
    signals: _ProductSignals,
    context: BehaviorPersonalizationContext | None,
) -> float | None:
    if context is None:
        return None

    source_scores: dict[str, float] = {}
    for source, source_weight in BEHAVIOR_POSITIVE_SOURCE_WEIGHTS.items():
        profile = context.source_profiles.get(source)
        if profile is None or profile.total_weight <= 0:
            continue
        components = {
            "effect": _profile_set_score(signals.effect_codes, profile.effect_scores, max_matches=3),
            "ingredient": _profile_set_score(signals.ingredient_codes, profile.ingredient_scores, max_matches=5),
            "category": _profile_value_score(product.category_code, profile.category_scores),
            "price_band": _profile_value_score(_price_band(product.lowest_price), profile.price_band_scores),
            "brand": _profile_value_score(product.brand_code, profile.brand_scores),
        }
        source_scores[source] = _weighted_average(
            tuple(
                (components[component], weight)
                for component, weight in BEHAVIOR_AFFINITY_COMPONENT_WEIGHTS.items()
            )
        ) * source_weight

    if source_scores:
        positive_weight = sum(
            BEHAVIOR_POSITIVE_SOURCE_WEIGHTS[source]
            for source in source_scores
        )
        positive_score = sum(source_scores.values()) / positive_weight if positive_weight > 0 else 0.0
    elif context.negative_profile is not None:
        positive_score = 0.5
    else:
        return None

    negative_guard_score = _behavior_negative_guard_score(product, signals, context)
    return _clamp(
        positive_score * (1.0 - BEHAVIOR_NEGATIVE_GUARD_WEIGHT)
        + negative_guard_score * BEHAVIOR_NEGATIVE_GUARD_WEIGHT
    )


def _behavior_negative_guard_score(
    product: _ProductBase,
    signals: _ProductSignals,
    context: BehaviorPersonalizationContext,
) -> float:
    negative_profile = context.negative_profile
    if negative_profile is None or negative_profile.total_weight <= 0:
        return 1.0
    if product.db_product_id in set(negative_profile.product_ids):
        return 0.0

    components = {
        "effect": _profile_set_score(signals.effect_codes, negative_profile.effect_scores, max_matches=3),
        "ingredient": _profile_set_score(signals.ingredient_codes, negative_profile.ingredient_scores, max_matches=5),
        "category": _profile_value_score(product.category_code, negative_profile.category_scores),
        "price_band": _profile_value_score(_price_band(product.lowest_price), negative_profile.price_band_scores),
        "brand": _profile_value_score(product.brand_code, negative_profile.brand_scores),
    }
    negative_affinity = _weighted_average(
        tuple(
            (components[component], weight)
            for component, weight in BEHAVIOR_AFFINITY_COMPONENT_WEIGHTS.items()
        )
    )
    return _clamp(1.0 - negative_affinity * 0.70)


def _build_popular_section(products: list[PopularProductItem]) -> HomeSection:
    return HomeSection(
        section_id="market_popular",
        title="지금 인기있는 제품",
        subtitle="최근 행동, 구매, 리뷰 신호를 함께 본 인기 상품",
        section_type="market_popular",
        algorithm="product_popularity_metrics_v1",
        products=[_build_popular_section_product(product) for product in products],
    )


def _build_popular_section_product(product: PopularProductItem) -> HomeSectionProduct:
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
        purchase_url=product.purchase_url,
        badges=["인기"],
        tags=[],
        reason_summary="최근 조회, 장바구니, 구매, 리뷰 신호를 기준으로 선정한 인기 상품입니다.",
        display_score=int(round(product.popularity_score)),
        sales_status=product.sales_status,
        stock_status=product.stock_status,
        available_quantity=product.available_quantity,
        in_stock=product.in_stock,
    )


def _section_to_response(
    section: HomeSection,
    *,
    category_code: str | None,
    limit: int,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    personalization_sources: tuple[str, ...] = (),
) -> HomeProductSectionResponse:
    return HomeProductSectionResponse(
        section_id=section.section_id,
        title=section.title,
        subtitle=section.subtitle,
        section_type=section.section_type,
        algorithm=section.algorithm,
        category_code=category_code,
        limit=limit,
        products=section.products,
        skin_type=skin_type,
        sensitivity=sensitivity,
        personalization_sources=list(personalization_sources),
    )


def _load_products(session: Session, *, category_code: str | None) -> list[_ProductBase]:
    lowest_price = func.min(ProductPrice.price)
    statement = (
        select(
            Product.id,
            Product.product_code,
            Brand.brand_code,
            Brand.name.label("brand_name"),
            ProductCategory.category_code,
            ProductCategory.name.label("category_name"),
            Product.product_name,
            lowest_price.label("lowest_price"),
            Inventory.id.label("inventory_id"),
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Product.is_recommendable.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            (Inventory.id.is_(None)) | (Inventory.sales_status != "HIDDEN"),
        )
        .group_by(
            Product.id,
            Product.product_code,
            Brand.brand_code,
            Brand.name,
            ProductCategory.category_code,
            ProductCategory.name,
            Product.product_name,
            Inventory.id,
            Inventory.stock_quantity,
            Inventory.reserved_quantity,
            Inventory.safety_stock,
            Inventory.sales_status,
        )
    )
    if category_code:
        statement = statement.where(ProductCategory.category_code == category_code)

    rows = session.execute(statement).all()
    thumbnail_storage_keys = load_thumbnail_storage_keys(session, [int(row.id) for row in rows])
    products: list[_ProductBase] = []
    for row in rows:
        availability = build_product_availability(
            inventory_exists=row.inventory_id is not None,
            sales_status=row.sales_status,
            stock_quantity=row.stock_quantity,
            reserved_quantity=row.reserved_quantity,
            safety_stock=row.safety_stock,
        )
        products.append(_ProductBase(
            db_product_id=int(row.id),
            product_id=row.product_code,
            brand=row.brand_name,
            brand_code=row.brand_code,
            category_code=row.category_code,
            category_name=row.category_name,
            name=row.product_name,
            thumbnail_url=thumbnail_storage_keys.get(int(row.id), ""),
            lowest_price=int(row.lowest_price or 0),
            sales_status=availability.sales_status,
            stock_status=availability.stock_status,
            available_quantity=availability.available_quantity,
            in_stock=availability.in_stock,
        ))
    return products


def _load_product_signals(
    session: Session,
    product_ids: list[int],
) -> dict[int, _ProductSignals]:
    if not product_ids:
        return {}

    ingredients_by_product_id: dict[int, list[str]] = {}
    effects_by_product_id: dict[int, list[str]] = {}
    tag_candidates_by_product_id: dict[int, list[tuple[float, float, int, str, str]]] = {}
    ingredient_codes_by_product_id: dict[int, list[str]] = {}
    effect_codes_by_product_id: dict[int, list[str]] = {}
    max_effect_score_by_product_id: dict[int, float] = {}
    max_evidence_score_by_product_id: dict[int, float] = {}

    for product_id_chunk in _chunks(product_ids, MAX_HOME_LOOKUP_IDS):
        rows = session.execute(
            select(
                ProductIngredient.product_id,
                ProductIngredient.display_order,
                Ingredient.name_ko,
                Ingredient.ingredient_code,
                Effect.name,
                Effect.effect_code,
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
            .where(ProductIngredient.product_id.in_(product_id_chunk))
            .order_by(ProductIngredient.display_order.asc(), ProductIngredient.id.asc())
        ).all()

        for (
            product_id,
            display_order,
            ingredient_name,
            ingredient_code,
            effect_name,
            effect_code,
            effect_score,
            evidence_score,
        ) in rows:
            db_product_id = int(product_id)
            if ingredient_name:
                ingredients_by_product_id.setdefault(db_product_id, []).append(str(ingredient_name))
            if ingredient_code:
                ingredient_codes_by_product_id.setdefault(db_product_id, []).append(str(ingredient_code))
            if effect_name:
                effects_by_product_id.setdefault(db_product_id, []).append(str(effect_name))
            if effect_code:
                effect_codes_by_product_id.setdefault(db_product_id, []).append(str(effect_code))
            if ingredient_name and effect_name:
                tag_candidates_by_product_id.setdefault(db_product_id, []).append(
                    (
                        _decimal_score_to_unit(evidence_score),
                        _decimal_score_to_unit(effect_score),
                        int(display_order),
                        str(effect_name),
                        str(ingredient_name),
                    )
                )
            max_effect_score_by_product_id[db_product_id] = max(
                max_effect_score_by_product_id.get(db_product_id, 0.0),
                _decimal_score_to_unit(effect_score),
            )
            max_evidence_score_by_product_id[db_product_id] = max(
                max_evidence_score_by_product_id.get(db_product_id, 0.0),
                _decimal_score_to_unit(evidence_score),
            )

    signals_by_product_id: dict[int, _ProductSignals] = {}
    for product_id in product_ids:
        tag_candidates = sorted(
            tag_candidates_by_product_id.get(product_id, []),
            key=lambda candidate: (-candidate[0], -candidate[1], candidate[2], candidate[3], candidate[4]),
        )
        tag_effect, tag_ingredient = (tag_candidates[0][3], tag_candidates[0][4]) if tag_candidates else ("", "")
        signals_by_product_id[product_id] = _ProductSignals(
            key_ingredients=tuple(_dedupe(ingredients_by_product_id.get(product_id, []))[:3]),
            effects=tuple(_dedupe(effects_by_product_id.get(product_id, []))[:3]),
            tag_effect=tag_effect,
            tag_ingredient=tag_ingredient,
            ingredient_codes=tuple(_dedupe(ingredient_codes_by_product_id.get(product_id, []))[:8]),
            effect_codes=tuple(_dedupe(effect_codes_by_product_id.get(product_id, []))[:8]),
            max_effect_score=max_effect_score_by_product_id.get(product_id, 0.0),
            max_evidence_score=max_evidence_score_by_product_id.get(product_id, 0.0),
        )
    return signals_by_product_id


def _load_skin_profiles(
    session: Session,
    product_ids: list[int],
) -> dict[int, _SkinProfileSignals]:
    if not product_ids:
        return {}

    skin_profiles_by_product_id: dict[int, _SkinProfileSignals] = {}
    for product_id_chunk in _chunks(product_ids, MAX_HOME_LOOKUP_IDS):
        rows = session.execute(
            select(ProductSkinProfile).where(ProductSkinProfile.product_id.in_(product_id_chunk))
        ).scalars()
        skin_profiles_by_product_id.update(
            {
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
        )
    return skin_profiles_by_product_id


def _load_purchase_urls(session: Session, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}

    urls_by_product_id: dict[int, str] = {}
    for product_id_chunk in _chunks(product_ids, MAX_HOME_LOOKUP_IDS):
        rows = session.execute(
            select(ProductPrice.product_id, ProductPrice.product_url)
            .where(ProductPrice.product_id.in_(product_id_chunk))
            .order_by(ProductPrice.product_id.asc(), ProductPrice.is_lowest.desc(), ProductPrice.price.asc())
        ).all()
        for product_id, product_url in rows:
            urls_by_product_id.setdefault(int(product_id), product_url)
    return urls_by_product_id


def _load_market_popularity_scores(session: Session, product_ids: list[int]) -> dict[int, float]:
    if not product_ids:
        return {}

    scores: dict[int, float] = {}
    for product_id_chunk in _chunks(product_ids, MAX_HOME_LOOKUP_IDS):
        rows = session.execute(
            select(ProductPopularityMetric.product_id, ProductPopularityMetric.popularity_score).where(
                ProductPopularityMetric.window_days == DEFAULT_POPULAR_WINDOW_DAYS,
                ProductPopularityMetric.product_id.in_(product_id_chunk),
            )
        ).all()
        for product_id, score in rows:
            scores[int(product_id)] = _decimal_score_to_unit(score)
    return scores


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
        sales_status=product.sales_status,
        stock_status=product.stock_status,
        available_quantity=product.available_quantity,
        in_stock=product.in_stock,
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
    return _dedupe([signals.tag_effect, signals.tag_ingredient])


def _build_reason_summary(section_id: str, signals: _ProductSignals, product: _ProductBase) -> str:
    primary_effect = signals.tag_effect
    primary_ingredient = signals.tag_ingredient

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
    sensitivity_score = profile.sensitive_fit if sensitivity == "높음" else 0.75 + profile.sensitive_fit * 0.25
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


def _normalize_skin_type_or_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return _normalize_skin_type(value)


def _normalize_limit(value: int) -> int:
    return max(1, min(MAX_HOME_LIMIT_PER_SECTION, value))


def _normalize_sensitivity(value: str | None) -> str:
    if value is None or not value.strip():
        return "보통"
    normalized = value.strip()
    aliases = {
        "low": "낮음",
        "medium": "보통",
        "mid": "보통",
        "high": "높음",
        "sensitive": "높음",
        "민감": "높음",
        "민감성": "높음",
        "예민": "높음",
        "예민함": "높음",
        "normal": "보통",
    }
    return aliases.get(normalized.casefold(), normalized)


def _normalize_sensitivity_or_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return _normalize_sensitivity(value)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _manual_skin_type_from_profile(profile: object | None) -> str | None:
    if profile is None:
        return None
    explicit_skin_type = _normalize_skin_type_or_none(getattr(profile, "explicit_skin_type", None))
    if explicit_skin_type is not None:
        return explicit_skin_type
    if getattr(profile, "skin_type_source", None) == "manual":
        return _normalize_skin_type_or_none(getattr(profile, "skin_type", None))
    return None


def _manual_sensitivity_from_profile(profile: object | None) -> str | None:
    if profile is None:
        return None
    explicit_sensitivity = _normalize_sensitivity_or_none(getattr(profile, "explicit_sensitivity", None))
    if explicit_sensitivity is not None:
        return explicit_sensitivity
    if getattr(profile, "sensitivity_source", None) == "manual":
        return _normalize_sensitivity_or_none(getattr(profile, "sensitivity", None))
    return None


def _desired_effect_terms(concern: str | None, effect: str | None) -> tuple[str, ...]:
    terms: list[str] = []
    if effect:
        terms.append(effect)
    concern_value = (concern or "").casefold()
    concern_map = {
        ("트러블", "여드름", "피지", "모공"): ("트러블", "여드름", "피지", "모공", "진정"),
        ("건조", "속건조", "보습", "장벽"): ("보습", "장벽", "수분"),
        ("민감", "진정", "자극"): ("진정", "장벽", "민감"),
        ("색소", "잡티", "미백", "톤"): ("미백", "톤", "잡티", "색소", "brightening"),
        ("주름", "탄력", "안티에이징"): ("주름", "탄력", "wrinkle"),
    }
    for triggers, mapped_terms in concern_map.items():
        if any(trigger in concern_value for trigger in triggers):
            terms.extend(mapped_terms)
    return tuple(_dedupe(terms))


def _effect_term_match_score(signals: _ProductSignals, terms: tuple[str, ...]) -> float | None:
    if not terms:
        return None

    normalized_terms = tuple(term.casefold().strip() for term in terms if term.strip())
    if not normalized_terms:
        return None

    effect_values = tuple(value.casefold() for value in (*signals.effects, *signals.effect_codes))
    matched = any(
        term in effect_value or effect_value in term
        for term in normalized_terms
        for effect_value in effect_values
    )
    if matched:
        return max(0.70, signals.max_effect_score)
    return 0.30


def _soft_context_score(score: float, strength: str | None) -> float:
    multiplier = 1.0 if strength == "strong" else 0.6
    return _clamp(0.5 + (_clamp(score) - 0.5) * multiplier)


def _axis_winner(skin_test_context: SkinTestScoringContext, axis: str) -> str | None:
    axis_score = skin_test_context.axis_scores.get(axis, {})
    if not isinstance(axis_score, dict):
        return None
    winner = axis_score.get("winner")
    return str(winner) if winner else None


def _axis_strength(skin_test_context: SkinTestScoringContext, axis: str) -> str | None:
    axis_score = skin_test_context.axis_scores.get(axis, {})
    if not isinstance(axis_score, dict):
        return None
    strength = axis_score.get("strength")
    return str(strength) if strength else None


def _commerce_code(skin_test_context: SkinTestScoringContext, key: str) -> str | None:
    value = skin_test_context.commerce_profile.get(key)
    if isinstance(value, dict):
        code = value.get("code")
        return str(code) if code else None
    return None


def _category_matches_preference(category_code: str, preferred_code: str) -> bool:
    aliases = {
        "toner_pad": {"toner", "pad", "toner_pad"},
        "ampoule_serum_essence": {"ampoule", "serum", "essence"},
        "lotion_cream": {"lotion", "cream"},
        "suncare": {"suncare", "sun", "sunscreen"},
    }
    return category_code in aliases.get(preferred_code, {preferred_code})


def _profile_set_score(
    candidate_values: tuple[str, ...],
    profile_scores: dict[str, float],
    *,
    max_matches: int,
) -> float:
    if not candidate_values or not profile_scores:
        return 0.0
    values = tuple(dict.fromkeys(value for value in candidate_values if value))
    matched_score = sum(profile_scores.get(value, 0.0) for value in values)
    best_possible = sum(sorted(profile_scores.values(), reverse=True)[: max(1, max_matches)])
    if best_possible <= 0:
        return 0.0
    return _clamp(matched_score / best_possible)


def _profile_value_score(candidate_value: str | None, profile_scores: dict[str, float]) -> float:
    if not candidate_value or not profile_scores:
        return 0.0
    max_score = max(profile_scores.values(), default=0.0)
    if max_score <= 0:
        return 0.0
    return _clamp(profile_scores.get(candidate_value, 0.0) / max_score)


def _price_band(price: int | None) -> str | None:
    if price is None or price <= 0:
        return None
    if price <= 15_000:
        return "under_15000"
    if price <= 30_000:
        return "15000_30000"
    if price <= 50_000:
        return "30000_50000"
    if price <= 80_000:
        return "50000_80000"
    return "over_80000"


def _empty_signals() -> _ProductSignals:
    return _ProductSignals(
        key_ingredients=(),
        effects=(),
        tag_effect="",
        tag_ingredient="",
        ingredient_codes=(),
        effect_codes=(),
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


def _weighted_average(items: tuple[tuple[float, float], ...]) -> float:
    total_weight = sum(max(0.0, weight) for _score, weight in items)
    if total_weight <= 0:
        return 0.0
    return _clamp(
        sum(_clamp(score) * max(0.0, weight) for score, weight in items)
        / total_weight
    )


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result
