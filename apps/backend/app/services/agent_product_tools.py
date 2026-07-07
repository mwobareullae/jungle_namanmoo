from dataclasses import dataclass
from decimal import Decimal
import secrets
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import (
    Brand,
    Product,
    ProductCategory,
    ProductIngredient,
    ProductPrice,
    ProductSkinProfile,
)
from app.db.models.commerce import Inventory, Seller
from app.db.models.taxonomy import Effect, Ingredient, IngredientEffect, RiskFlag
from app.schemas.agent import AgentChatResponse, AgentResponseItem, AgentUiAction
from app.schemas.common import ApiError
from app.services.agent_policy import (
    validate_result_item_count,
    validate_tool_access,
    validate_tool_ui_action,
)
from app.services.product_image_service import load_thumbnail_storage_keys


FIND_SIMILAR_PRODUCTS_TOOL = "find_similar_products"
COMPARE_PRODUCTS_TOOL = "compare_products"
REFINE_PRODUCT_RESULTS_TOOL = "refine_product_results"
DEFAULT_SIMILAR_LIMIT = 2
DEFAULT_REFINE_LIMIT = 10
SIMILAR_CANDIDATE_POOL_SIZE = 200
SIMILAR_CATEGORY_WEIGHT = 20
SIMILAR_PRICE_WEIGHT = 5
SIMILAR_SKIN_PROFILE_WEIGHT = 20
SIMILAR_EFFECT_WEIGHT = 25
SIMILAR_INGREDIENT_WEIGHT = 30


@dataclass(frozen=True)
class _ProductSnapshot:
    db_product_id: int
    product_id: str
    brand: str
    category_code: str
    category_name: str
    name: str
    thumbnail_storage_key: str | None
    lowest_price: int | None
    currency: str | None
    seller_status: str
    sales_status: str
    stock_status: str
    available_quantity: int | None
    skin_profile: dict[str, float]
    sensitivity_tag: str | None
    skin_type_tags: tuple[str, ...]
    ingredients: tuple[str, ...]
    effects: tuple[str, ...]
    risk_flags: tuple[str, ...]

    @property
    def can_purchase(self) -> bool:
        return (
            self.seller_status == "ACTIVE"
            and self.sales_status == "ON_SALE"
            and self.available_quantity is not None
            and self.available_quantity > 0
            and self.lowest_price is not None
        )


@dataclass(frozen=True)
class _SimilarityResult:
    snapshot: _ProductSnapshot
    score: int
    reasons: tuple[str, ...]


def find_similar_products(
    session: Session,
    *,
    product_id: str,
    conversation_id: str | None = None,
    limit: int = DEFAULT_SIMILAR_LIMIT,
    min_price: int | None = None,
    max_price: int | None = None,
) -> AgentChatResponse:
    validate_tool_access(FIND_SIMILAR_PRODUCTS_TOOL, user_id=None)
    normalized_limit = _normalize_limit(limit, DEFAULT_SIMILAR_LIMIT)
    validate_result_item_count(FIND_SIMILAR_PRODUCTS_TOOL, normalized_limit)

    source = _load_single_snapshot(session, product_id)
    candidates = _load_similarity_candidate_snapshots(session, source)
    candidates = [
        candidate
        for candidate in candidates
        if candidate.product_id != source.product_id
        and candidate.can_purchase
        and _matches_price_filter(candidate, min_price=min_price, max_price=max_price)
    ]
    ranked = sorted(
        (_score_similarity(source, candidate) for candidate in candidates),
        key=lambda item: (-item.score, item.snapshot.product_id),
    )[:normalized_limit]

    action = AgentUiAction(
        type="show_products",
        target="similar_products",
        payload={
            "source_product_id": source.product_id,
            "layout_hint": "side_panel",
            "algorithm": "agent_similarity_v1",
            "products": [_to_product_payload(result.snapshot) for result in ranked],
        },
    )
    validate_tool_ui_action(FIND_SIMILAR_PRODUCTS_TOOL, action)
    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message="Similar products were found.",
        tool_name=FIND_SIMILAR_PRODUCTS_TOOL,
        ui_action=action,
        items=[
            _to_product_response_item(
                result.snapshot,
                metadata={
                    "similarity_score": result.score,
                    "match_reasons": list(result.reasons),
                },
            )
            for result in ranked
        ],
    )


def compare_products(
    session: Session,
    *,
    product_ids: list[str],
    conversation_id: str | None = None,
) -> AgentChatResponse:
    validate_tool_access(COMPARE_PRODUCTS_TOOL, user_id=None)
    normalized_product_ids = _normalize_product_ids(product_ids)
    validate_result_item_count(COMPARE_PRODUCTS_TOOL, len(normalized_product_ids))
    if len(normalized_product_ids) < 2:
        raise ApiError(400, "AGENT_COMPARE_REQUIRES_TWO_PRODUCTS", "At least two products are required.")

    snapshots = _load_snapshots_by_product_codes(session, normalized_product_ids)
    ordered_snapshots = _order_snapshots(snapshots, normalized_product_ids)
    payload = _build_comparison_payload(ordered_snapshots)
    action = AgentUiAction(
        type="show_product_comparison",
        target="product_comparison",
        payload=payload,
    )
    validate_tool_ui_action(COMPARE_PRODUCTS_TOOL, action)
    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message="Selected products were compared.",
        tool_name=COMPARE_PRODUCTS_TOOL,
        ui_action=action,
        items=[_to_product_response_item(snapshot) for snapshot in ordered_snapshots],
    )


def refine_product_results(
    session: Session,
    *,
    base_product_ids: list[str],
    conversation_id: str | None = None,
    limit: int = DEFAULT_REFINE_LIMIT,
    min_price: int | None = None,
    max_price: int | None = None,
    category_code: str | None = None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    effect_keywords: list[str] | None = None,
) -> AgentChatResponse:
    validate_tool_access(REFINE_PRODUCT_RESULTS_TOOL, user_id=None)
    normalized_limit = _normalize_limit(limit, DEFAULT_REFINE_LIMIT)
    validate_result_item_count(REFINE_PRODUCT_RESULTS_TOOL, normalized_limit)
    normalized_product_ids = _normalize_product_ids(base_product_ids)
    if not normalized_product_ids:
        raise ApiError(400, "AGENT_REFINE_PRODUCTS_REQUIRED", "base_product_ids is required.")

    snapshots = _load_snapshots_by_product_codes(session, normalized_product_ids)
    ordered_snapshots = _order_snapshots(snapshots, normalized_product_ids)
    filtered = [
        snapshot
        for snapshot in ordered_snapshots
        if snapshot.can_purchase
        and _matches_price_filter(snapshot, min_price=min_price, max_price=max_price)
        and _matches_category_filter(snapshot, category_code)
        and _matches_skin_filter(snapshot, skin_type=skin_type, sensitivity=sensitivity)
        and _matches_effect_filter(snapshot, effect_keywords)
    ][:normalized_limit]

    action = AgentUiAction(
        type="show_products",
        target="refined_products",
        payload={
            "layout_hint": "side_panel",
            "source_product_ids": normalized_product_ids,
            "filters": {
                "min_price": min_price,
                "max_price": max_price,
                "category_code": category_code,
                "skin_type": skin_type,
                "sensitivity": sensitivity,
                "effect_keywords": effect_keywords or [],
            },
            "products": [_to_product_payload(snapshot) for snapshot in filtered],
        },
    )
    validate_tool_ui_action(REFINE_PRODUCT_RESULTS_TOOL, action)
    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message="Product results were refined.",
        tool_name=REFINE_PRODUCT_RESULTS_TOOL,
        ui_action=action,
        items=[_to_product_response_item(snapshot) for snapshot in filtered],
    )


def _load_single_snapshot(session: Session, product_code: str) -> _ProductSnapshot:
    normalized_code = product_code.strip()
    if not normalized_code:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "Product was not found.")
    snapshots = _load_snapshots_by_product_codes(session, [normalized_code])
    if not snapshots:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "Product was not found.")
    return snapshots[0]


def _load_similarity_candidate_snapshots(
    session: Session,
    source: _ProductSnapshot,
) -> list[_ProductSnapshot]:
    lowest_prices = _lowest_price_subquery()
    category_match_order = case(
        (ProductCategory.category_code == source.category_code, 0),
        else_=1,
    )
    price_distance_order = func.abs(func.coalesce(lowest_prices.c.lowest_price, 0) - (source.lowest_price or 0))
    rows = session.execute(
        select(Product.product_code)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            Seller.status == "ACTIVE",
            Product.product_code != source.product_id,
        )
        .order_by(category_match_order.asc(), price_distance_order.asc(), Product.id.asc())
        .limit(SIMILAR_CANDIDATE_POOL_SIZE)
    ).scalars().all()
    return _load_snapshots_by_product_codes(session, list(rows))


def _load_snapshots_by_product_codes(
    session: Session,
    product_codes: list[str],
) -> list[_ProductSnapshot]:
    normalized_codes = _normalize_product_ids(product_codes)
    if not normalized_codes:
        return []

    lowest_prices = _lowest_price_subquery()
    rows = session.execute(
        select(
            Product,
            Brand,
            ProductCategory,
            Seller,
            Inventory,
            lowest_prices.c.lowest_price,
            lowest_prices.c.currency,
        )
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .outerjoin(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(
            Product.product_code.in_(normalized_codes),
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
        )
        .order_by(Product.id.asc())
    ).all()

    if len(rows) != len(set(normalized_codes)):
        found_codes = {row[0].product_code for row in rows}
        missing = [code for code in normalized_codes if code not in found_codes]
        raise ApiError(404, "PRODUCT_NOT_FOUND", f"Product was not found: {missing[0]}")

    product_db_ids = [int(row[0].id) for row in rows]
    thumbnails = load_thumbnail_storage_keys(session, product_db_ids)
    skin_profiles = _load_skin_profiles(session, product_db_ids)
    ingredients = _load_ingredients(session, product_db_ids)
    effects = _load_effects(session, product_db_ids)
    risk_flags = _load_risk_flags(session, product_db_ids)

    return [
        _ProductSnapshot(
            db_product_id=int(product.id),
            product_id=product.product_code,
            brand=brand.name,
            category_code=category.category_code,
            category_name=category.name,
            name=product.product_name,
            thumbnail_storage_key=thumbnails.get(int(product.id)),
            lowest_price=int(lowest_price) if lowest_price is not None else None,
            currency=currency,
            seller_status=seller.status,
            sales_status=inventory.sales_status if inventory is not None else "UNKNOWN",
            stock_status=_stock_status(inventory),
            available_quantity=_available_quantity(inventory),
            skin_profile=_numeric_skin_profile(skin_profiles.get(int(product.id), {})),
            sensitivity_tag=_sensitivity_tag(skin_profiles.get(int(product.id), {})),
            skin_type_tags=_parse_skin_type_tags(product.skin_type_tags),
            ingredients=ingredients.get(int(product.id), ()),
            effects=effects.get(int(product.id), ()),
            risk_flags=risk_flags.get(int(product.id), ()),
        )
        for product, brand, category, seller, inventory, lowest_price, currency in rows
    ]


def _lowest_price_subquery():
    return (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("lowest_price"),
            func.min(ProductPrice.currency).label("currency"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )


def _load_skin_profiles(
    session: Session,
    product_db_ids: list[int],
) -> dict[int, dict[str, float | str | None]]:
    if not product_db_ids:
        return {}
    rows = session.execute(
        select(ProductSkinProfile).where(ProductSkinProfile.product_id.in_(product_db_ids))
    ).scalars()
    return {
        int(row.product_id): {
            "dry_fit": _decimal_to_float(row.dry_fit),
            "oily_fit": _decimal_to_float(row.oily_fit),
            "combination_fit": _decimal_to_float(row.combination_fit),
            "normal_fit": _decimal_to_float(row.normal_fit),
            "dehydrated_oily_fit": _decimal_to_float(row.dehydrated_oily_fit),
            "sensitive_fit": _decimal_to_float(row.sensitive_fit),
            "sensitivity_tag": row.sensitivity_tag,
        }
        for row in rows
    }


def _load_ingredients(
    session: Session,
    product_db_ids: list[int],
) -> dict[int, tuple[str, ...]]:
    if not product_db_ids:
        return {}
    rows = session.execute(
        select(ProductIngredient.product_id, ProductIngredient.ingredient_name, Ingredient.name_ko)
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .where(ProductIngredient.product_id.in_(product_db_ids))
        .order_by(ProductIngredient.product_id.asc(), ProductIngredient.display_order.asc(), ProductIngredient.id.asc())
    ).all()
    grouped: dict[int, list[str]] = {}
    for product_id, ingredient_name, fallback_name in rows:
        grouped.setdefault(int(product_id), []).append(ingredient_name or fallback_name)
    return {
        product_id: tuple(_dedupe(values)[:6])
        for product_id, values in grouped.items()
    }


def _load_effects(
    session: Session,
    product_db_ids: list[int],
) -> dict[int, tuple[str, ...]]:
    if not product_db_ids:
        return {}
    rows = session.execute(
        select(ProductIngredient.product_id, Effect.name, IngredientEffect.effect_score)
        .join(IngredientEffect, ProductIngredient.ingredient_id == IngredientEffect.ingredient_id)
        .join(Effect, IngredientEffect.effect_id == Effect.id)
        .where(ProductIngredient.product_id.in_(product_db_ids))
        .order_by(ProductIngredient.product_id.asc(), IngredientEffect.effect_score.desc(), Effect.name.asc())
    ).all()
    grouped: dict[int, list[str]] = {}
    for product_id, effect_name, _ in rows:
        grouped.setdefault(int(product_id), []).append(effect_name)
    return {
        product_id: tuple(_dedupe(values)[:6])
        for product_id, values in grouped.items()
    }


def _load_risk_flags(
    session: Session,
    product_db_ids: list[int],
) -> dict[int, tuple[str, ...]]:
    if not product_db_ids:
        return {}
    rows = session.execute(
        select(ProductIngredient.product_id, RiskFlag.display_text)
        .join(RiskFlag, ProductIngredient.ingredient_id == RiskFlag.ingredient_id)
        .where(ProductIngredient.product_id.in_(product_db_ids))
        .order_by(ProductIngredient.product_id.asc(), RiskFlag.id.asc())
    ).all()
    grouped: dict[int, list[str]] = {}
    for product_id, display_text in rows:
        grouped.setdefault(int(product_id), []).append(display_text)
    return {
        product_id: tuple(_dedupe(values)[:4])
        for product_id, values in grouped.items()
    }


def _score_similarity(
    source: _ProductSnapshot,
    candidate: _ProductSnapshot,
) -> _SimilarityResult:
    reasons: list[str] = []
    score = 0.0

    if source.category_code == candidate.category_code:
        score += SIMILAR_CATEGORY_WEIGHT
        reasons.append("same_category")

    price_similarity = _price_similarity(source.lowest_price, candidate.lowest_price)
    score += price_similarity * SIMILAR_PRICE_WEIGHT
    if price_similarity >= 0.8:
        reasons.append("similar_price")

    skin_similarity = _skin_profile_similarity(source.skin_profile, candidate.skin_profile)
    score += skin_similarity * SIMILAR_SKIN_PROFILE_WEIGHT
    if skin_similarity >= 0.75:
        reasons.append("similar_skin_profile")

    effect_similarity = _jaccard(source.effects, candidate.effects)
    score += effect_similarity * SIMILAR_EFFECT_WEIGHT
    if effect_similarity > 0:
        reasons.append("shared_effects")

    ingredient_similarity = _jaccard(source.ingredients, candidate.ingredients)
    score += ingredient_similarity * SIMILAR_INGREDIENT_WEIGHT
    if ingredient_similarity > 0:
        reasons.append("shared_ingredients")

    return _SimilarityResult(
        snapshot=candidate,
        score=int(round(score)),
        reasons=tuple(reasons[:5]),
    )


def _build_comparison_payload(snapshots: list[_ProductSnapshot]) -> dict[str, Any]:
    products = [_to_product_payload(snapshot) for snapshot in snapshots]
    cheapest = min(
        (snapshot for snapshot in snapshots if snapshot.lowest_price is not None),
        key=lambda item: item.lowest_price or 0,
        default=None,
    )
    most_expensive = max(
        (snapshot for snapshot in snapshots if snapshot.lowest_price is not None),
        key=lambda item: item.lowest_price or 0,
        default=None,
    )
    shared_effects = _shared_values([snapshot.effects for snapshot in snapshots])
    shared_ingredients = _shared_values([snapshot.ingredients for snapshot in snapshots])
    unavailable = [snapshot.product_id for snapshot in snapshots if not snapshot.can_purchase]
    caution_products = [snapshot.product_id for snapshot in snapshots if snapshot.risk_flags]

    return {
        "layout_hint": "bottom_panel",
        "products": products,
        "highlights": {
            "cheapest_product_id": cheapest.product_id if cheapest else None,
            "most_expensive_product_id": most_expensive.product_id if most_expensive else None,
            "shared_effects": shared_effects,
            "shared_ingredients": shared_ingredients,
            "caution_product_ids": caution_products,
            "unavailable_product_ids": unavailable,
            "different_points": _build_difference_points(snapshots, cheapest),
        },
    }


def _build_difference_points(
    snapshots: list[_ProductSnapshot],
    cheapest: _ProductSnapshot | None,
) -> list[str]:
    points: list[str] = []
    categories = {snapshot.category_code for snapshot in snapshots}
    if len(categories) > 1:
        points.append("Products are from different categories.")
    if cheapest is not None:
        points.append(f"{cheapest.product_id} has the lowest price.")
    for snapshot in snapshots:
        if snapshot.risk_flags:
            points.append(f"{snapshot.product_id} has caution flags.")
    return points[:5]


def _to_product_response_item(
    snapshot: _ProductSnapshot,
    *,
    metadata: dict[str, Any] | None = None,
) -> AgentResponseItem:
    base_metadata = {
        "brand": snapshot.brand,
        "category_code": snapshot.category_code,
        "category_name": snapshot.category_name,
        "sales_status": snapshot.sales_status,
        "stock_status": snapshot.stock_status,
        "effects": list(snapshot.effects[:4]),
        "ingredients": list(snapshot.ingredients[:4]),
    }
    if metadata:
        base_metadata.update(metadata)
    return AgentResponseItem(
        item_type="product",
        id=snapshot.product_id,
        title=snapshot.name,
        subtitle=snapshot.brand,
        image_storage_key=snapshot.thumbnail_storage_key,
        price=snapshot.lowest_price,
        currency=snapshot.currency,
        metadata=base_metadata,
    )


def _to_product_payload(snapshot: _ProductSnapshot) -> dict[str, Any]:
    return {
        "product_id": snapshot.product_id,
        "brand": snapshot.brand,
        "name": snapshot.name,
        "category_code": snapshot.category_code,
        "category_name": snapshot.category_name,
        "price": snapshot.lowest_price,
        "currency": snapshot.currency,
        "thumbnail_storage_key": snapshot.thumbnail_storage_key,
        "sales_status": snapshot.sales_status,
        "stock_status": snapshot.stock_status,
        "available_quantity": snapshot.available_quantity,
        "skin_types": _top_skin_types(snapshot.skin_profile),
        "skin_profile": snapshot.skin_profile,
        "sensitivity": snapshot.sensitivity_tag,
        "effects": list(snapshot.effects),
        "key_ingredients": list(snapshot.ingredients),
        "caution_flags": list(snapshot.risk_flags),
        "summary": _build_product_summary(snapshot),
    }


def _build_product_summary(snapshot: _ProductSnapshot) -> str:
    effects = ", ".join(snapshot.effects[:2])
    ingredients = ", ".join(snapshot.ingredients[:2])
    if effects and ingredients:
        return f"Effect focus: {effects}. Key ingredients: {ingredients}."
    if effects:
        return f"Effect focus: {effects}."
    if ingredients:
        return f"Key ingredients: {ingredients}."
    return "Candidate based on product profile."


def _order_snapshots(
    snapshots: list[_ProductSnapshot],
    product_ids: list[str],
) -> list[_ProductSnapshot]:
    by_product_id = {snapshot.product_id: snapshot for snapshot in snapshots}
    return [by_product_id[product_id] for product_id in product_ids]


def _normalize_product_ids(product_ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for product_id in product_ids:
        normalized = product_id.strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _normalize_limit(limit: int, default: int) -> int:
    if limit <= 0:
        return default
    return limit


def _matches_price_filter(
    snapshot: _ProductSnapshot,
    *,
    min_price: int | None,
    max_price: int | None,
) -> bool:
    if snapshot.lowest_price is None:
        return False
    if min_price is not None and snapshot.lowest_price < min_price:
        return False
    if max_price is not None and snapshot.lowest_price > max_price:
        return False
    return True


def _matches_category_filter(snapshot: _ProductSnapshot, category_code: str | None) -> bool:
    return category_code is None or snapshot.category_code == category_code


def _matches_skin_filter(
    snapshot: _ProductSnapshot,
    *,
    skin_type: str | None,
    sensitivity: str | None,
) -> bool:
    if skin_type:
        profile_key = _skin_type_to_profile_key(skin_type)
        if profile_key and snapshot.skin_profile.get(profile_key, 0.0) < 0.7:
            return False
    if sensitivity and sensitivity.casefold() == "sensitive":
        if snapshot.skin_profile.get("sensitive_fit", 0.0) < 0.7:
            return False
    return True


def _matches_effect_filter(
    snapshot: _ProductSnapshot,
    effect_keywords: list[str] | None,
) -> bool:
    keywords = [keyword.strip().casefold() for keyword in effect_keywords or [] if keyword.strip()]
    if not keywords:
        return True
    haystack = " ".join([*snapshot.effects, *snapshot.ingredients]).casefold()
    return all(keyword in haystack for keyword in keywords)


def _skin_type_to_profile_key(skin_type: str) -> str | None:
    aliases = {
        "dry": "dry_fit",
        "oily": "oily_fit",
        "combination": "combination_fit",
        "normal": "normal_fit",
        "dehydrated_oily": "dehydrated_oily_fit",
    }
    return aliases.get(skin_type.strip().casefold())


def _numeric_skin_profile(profile: dict[str, Any]) -> dict[str, float]:
    return {
        key: float(profile.get(key, 0.0))
        for key in (
            "dry_fit",
            "oily_fit",
            "combination_fit",
            "normal_fit",
            "dehydrated_oily_fit",
            "sensitive_fit",
        )
    }


def _sensitivity_tag(profile: dict[str, Any]) -> str | None:
    value = profile.get("sensitivity_tag")
    return str(value) if value is not None else None


def _price_similarity(source_price: int | None, candidate_price: int | None) -> float:
    if not source_price or not candidate_price:
        return 0.0
    difference_ratio = abs(source_price - candidate_price) / max(source_price, candidate_price)
    return _clamp(1.0 - difference_ratio)


def _skin_profile_similarity(source: dict[str, Any], candidate: dict[str, Any]) -> float:
    keys = [
        "dry_fit",
        "oily_fit",
        "combination_fit",
        "normal_fit",
        "dehydrated_oily_fit",
        "sensitive_fit",
    ]
    if not source or not candidate:
        return 0.0
    differences = [abs(float(source.get(key, 0.0)) - float(candidate.get(key, 0.0))) for key in keys]
    return _clamp(1.0 - sum(differences) / len(keys))


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = {value.casefold() for value in left if value}
    right_set = {value.casefold() for value in right if value}
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _shared_values(groups: list[tuple[str, ...]]) -> list[str]:
    if not groups:
        return []
    shared = set(groups[0])
    for group in groups[1:]:
        shared &= set(group)
    return sorted(shared)[:6]


def _top_skin_types(profile: dict[str, Any]) -> list[str]:
    mapping = {
        "dry_fit": "DRY",
        "oily_fit": "OILY",
        "combination_fit": "COMBINATION",
        "normal_fit": "NORMAL",
        "dehydrated_oily_fit": "DEHYDRATED_OILY",
    }
    ranked = sorted(
        (
            (label, float(profile.get(key, 0.0)))
            for key, label in mapping.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return [label for label, score in ranked if score >= 0.7][:3]


def _parse_skin_type_tags(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(_dedupe(value.replace(",", ";").split(";")))


def _stock_status(inventory: Inventory | None) -> str:
    if inventory is None:
        return "UNKNOWN"
    available_quantity = _available_quantity(inventory)
    if inventory.sales_status == "HIDDEN":
        return "HIDDEN"
    if inventory.sales_status == "SOLD_OUT" or available_quantity is None or available_quantity <= 0:
        return "SOLD_OUT"
    if available_quantity <= 5:
        return "LOW_STOCK"
    return "IN_STOCK"


def _available_quantity(inventory: Inventory | None) -> int | None:
    if inventory is None:
        return None
    return max(inventory.stock_quantity - inventory.reserved_quantity - inventory.safety_stock, 0)


def _decimal_to_float(value: Decimal | float | int | str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _resolve_conversation_id(conversation_id: str | None) -> str:
    if conversation_id and conversation_id.strip():
        return conversation_id.strip()
    return f"conv_{secrets.token_urlsafe(12).replace('-', '').replace('_', '')[:16]}"
