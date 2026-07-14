from datetime import UTC, datetime, timedelta
from itertools import product as cartesian_product
import secrets

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice, ProductSkinProfile
from app.db.models.commerce import Inventory, Seller
from app.db.models.taxonomy import Ingredient
from app.schemas.agent import AgentChatResponse, AgentResponseItem, AgentToolConfirmResponse, AgentUiAction
from app.schemas.common import ApiError
from app.services.cart_service import add_cart_item, get_cart_response
from app.services.agent_policy import validate_result_item_count, validate_tool_ui_action
from app.services.product_image_service import load_thumbnail_storage_keys
from app.services.skin_profile_service import load_skin_profile_for_user


COMPOSE_CART_TOOL = "compose_cart"
COMPOSE_CART_TTL_MINUTES = 10
CATEGORY_ALIASES = {
    "토너": "toner",
    "toner": "toner",
    "세럼": "serum",
    "앰플": "serum",
    "serum": "serum",
    "크림": "cream",
    "cream": "cream",
}
CATEGORY_LABELS = {"toner": "토너", "serum": "세럼", "cream": "크림"}
SKIN_FIT_COLUMNS = {
    "건성": "dry_fit",
    "지성": "oily_fit",
    "복합성": "combination_fit",
    "중성": "normal_fit",
    "수부지": "dehydrated_oily_fit",
}


def prepare_composed_cart(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    categories: list[str],
    max_budget: int,
    skin_type: str | None,
    sensitivity: str | None,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    category_codes = _normalize_categories(categories)
    profile = load_skin_profile_for_user(session, user.id)
    resolved_skin_type = skin_type or getattr(profile, "skin_type", None) or "중성"
    resolved_sensitivity = sensitivity or getattr(profile, "sensitivity", None) or "보통"
    avoid_ingredients = _normalize_avoid_ingredients(getattr(profile, "avoid_ingredients", None))

    candidates_by_category = {
        category_code: _load_candidates(
            session,
            category_code=category_code,
            skin_type=resolved_skin_type,
            sensitivity=resolved_sensitivity,
            avoid_ingredients=avoid_ingredients,
            max_budget=max_budget,
        )
        for category_code in category_codes
    }
    missing_category = next((code for code, candidates in candidates_by_category.items() if not candidates), None)
    if missing_category is not None:
        raise ApiError(409, "AGENT_CART_COMPOSITION_NOT_FOUND", f"조건에 맞는 {missing_category} 상품을 찾지 못했어요.")

    combinations = cartesian_product(*(candidates_by_category[code] for code in category_codes))
    feasible = [
        combination
        for combination in combinations
        if len({item["product_id"] for item in combination}) == len(combination)
        and sum(item["price"] for item in combination) <= max_budget
    ]
    if not feasible:
        raise ApiError(409, "AGENT_CART_BUDGET_NOT_FOUND", "예산 안에서 요청한 상품 조합을 찾지 못했어요.")

    selected = max(
        feasible,
        key=lambda combination: (
            round(sum(item["fit_score"] for item in combination), 6),
            -sum(item["price"] for item in combination),
        ),
    )
    total = sum(item["price"] for item in selected)
    now = datetime.now(UTC)
    tool_call_id = f"tool_{secrets.token_urlsafe(18)}"
    payload = {
        "tool_call_id": tool_call_id,
        "categories": category_codes,
        "max_budget": max_budget,
        "total": total,
        "skin_type": resolved_skin_type,
        "sensitivity": resolved_sensitivity,
        "avoid_ingredients": avoid_ingredients,
        "selections": list(selected),
        "expires_at": (now + timedelta(minutes=COMPOSE_CART_TTL_MINUTES)).isoformat(),
    }
    session.add(
        AgentToolCall(
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            user_id=user.id,
            anonymous_user_id=anonymous_user_id,
            session_id=session_id,
            request_id=request_id,
            tool_name=COMPOSE_CART_TOOL,
            status="AWAITING_CONFIRMATION",
            confirmation_required=True,
            expires_at=now + timedelta(minutes=COMPOSE_CART_TTL_MINUTES),
            input_json={
                "categories": category_codes,
                "max_budget": max_budget,
                "skin_type": resolved_skin_type,
                "sensitivity": resolved_sensitivity,
            },
            output_json=payload,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()

    action = AgentUiAction(type="open_modal", target="agent_confirmation", payload=payload)
    items = [_to_response_item(item) for item in selected]
    validate_tool_ui_action(COMPOSE_CART_TOOL, action)
    validate_result_item_count(COMPOSE_CART_TOOL, len(items))
    return AgentChatResponse(
        conversation_id=conversation_id or f"conv_{secrets.token_urlsafe(12)}",
        message=(
            f"{resolved_skin_type}·민감도 {resolved_sensitivity} 기준으로 "
            f"{len(items)}개 상품을 {total:,}원에 구성했어요. 장바구니에 반영할까요?"
        ),
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=COMPOSE_CART_TOOL,
        ui_action=action,
        items=items,
    )


def confirm_composed_cart(
    session: Session,
    user: User,
    *,
    tool_call: AgentToolCall,
    action: str,
) -> AgentToolConfirmResponse:
    if tool_call.status == "EXECUTED":
        cart = get_cart_response(session, user, None)
        return _executed_response(tool_call.tool_call_id, cart, "이미 장바구니에 반영된 구성이에요.")
    if tool_call.status != "AWAITING_CONFIRMATION":
        raise ApiError(409, "AGENT_TOOL_CALL_NOT_CONFIRMABLE", "현재 상태에서는 이 요청을 확인할 수 없어요.")
    now = datetime.now(UTC)
    if tool_call.expires_at is not None and tool_call.expires_at.replace(tzinfo=UTC) <= now:
        tool_call.status = "EXPIRED"
        tool_call.updated_at = now
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="EXPIRED",
            message="장바구니 구성 확인 시간이 만료됐어요. 다시 요청해 주세요.",
            ui_action=AgentUiAction(),
        )
    if action == "reject":
        tool_call.status = "REJECTED"
        tool_call.updated_at = now
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="REJECTED",
            message="장바구니 구성을 반영하지 않았어요.",
            ui_action=AgentUiAction(),
        )
    if action != "confirm":
        raise ApiError(400, "AGENT_CONFIRM_ACTION_INVALID", "확인 응답을 처리할 수 없어요.")

    selections = (tool_call.output_json or {}).get("selections")
    if not isinstance(selections, list) or not selections:
        raise ApiError(400, "AGENT_CART_COMPOSITION_INVALID", "저장된 장바구니 구성 정보를 확인할 수 없어요.")
    for item in selections:
        if not isinstance(item, dict) or not isinstance(item.get("product_id"), str):
            raise ApiError(400, "AGENT_CART_COMPOSITION_INVALID", "저장된 장바구니 구성 정보를 확인할 수 없어요.")
        add_cart_item(
            session,
            user,
            None,
            product_code=item["product_id"],
            quantity=1,
            source="agent",
            recommendation_id=None,
            recommendation_rank=None,
        )
    cart = get_cart_response(session, user, None)
    tool_call.status = "EXECUTED"
    tool_call.confirmed_at = now
    tool_call.executed_at = now
    tool_call.updated_at = now
    session.flush()
    return _executed_response(tool_call.tool_call_id, cart, f"상품 {len(selections)}개를 장바구니에 반영했어요.")


def _load_candidates(
    session: Session,
    *,
    category_code: str,
    skin_type: str,
    sensitivity: str,
    avoid_ingredients: list[str],
    max_budget: int,
) -> list[dict]:
    lowest_prices = (
        select(
            ProductPrice.product_id.label("product_id"),
            func.min(ProductPrice.price).label("price"),
            func.min(ProductPrice.currency).label("currency"),
        )
        .group_by(ProductPrice.product_id)
        .subquery()
    )
    rows = session.execute(
        select(Product, Brand, ProductCategory, ProductSkinProfile, lowest_prices.c.price, lowest_prices.c.currency)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .join(Seller, Product.seller_id == Seller.id)
        .join(Inventory, Inventory.product_id == Product.id)
        .outerjoin(ProductSkinProfile, ProductSkinProfile.product_id == Product.id)
        .join(lowest_prices, lowest_prices.c.product_id == Product.id)
        .where(
            Product.is_active.is_(True),
            Product.is_recommendable.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.category_code == category_code,
            Seller.status == "ACTIVE",
            Inventory.sales_status == "ON_SALE",
            Inventory.stock_quantity - Inventory.reserved_quantity - Inventory.safety_stock > 0,
            lowest_prices.c.price <= max_budget,
        )
        .order_by(lowest_prices.c.price.asc(), Product.id.asc())
        .limit(80)
    ).all()
    blocked_ids = _blocked_product_ids(session, [int(row[0].id) for row in rows], avoid_ingredients)
    thumbnails = load_thumbnail_storage_keys(session, [int(row[0].id) for row in rows])
    candidates = []
    for product, brand, category, profile, price, currency in rows:
        if int(product.id) in blocked_ids:
            continue
        fit_score = _fit_score(profile, skin_type=skin_type, sensitivity=sensitivity)
        candidates.append({
            "product_id": product.product_code,
            "title": product.product_name,
            "brand": brand.name,
            "category_code": category.category_code,
            "category_name": CATEGORY_LABELS.get(category.category_code, category.name),
            "price": int(price),
            "currency": currency or "KRW",
            "fit_score": fit_score,
            "image_storage_key": thumbnails.get(int(product.id)),
        })
    return sorted(candidates, key=lambda item: (-item["fit_score"], item["price"], item["product_id"]))[:12]


def _blocked_product_ids(session: Session, product_ids: list[int], avoid_ingredients: list[str]) -> set[int]:
    if not product_ids or not avoid_ingredients:
        return set()
    normalized = [value.casefold().replace(" ", "") for value in avoid_ingredients]
    rows = session.execute(
        select(ProductIngredient.product_id, ProductIngredient.ingredient_name, Ingredient.name_ko)
        .join(Ingredient, ProductIngredient.ingredient_id == Ingredient.id)
        .where(ProductIngredient.product_id.in_(product_ids))
    ).all()
    return {
        int(product_id)
        for product_id, ingredient_name, canonical_name in rows
        if any(
            term in candidate.casefold().replace(" ", "")
            for candidate in (ingredient_name, canonical_name)
            if candidate
            for term in normalized
        )
    }


def _fit_score(profile: ProductSkinProfile | None, *, skin_type: str, sensitivity: str) -> float:
    if profile is None:
        return 0.0
    column = SKIN_FIT_COLUMNS.get(skin_type, "normal_fit")
    skin_score = float(getattr(profile, column))
    if sensitivity == "높음":
        return round((skin_score + float(profile.sensitive_fit)) / 2, 6)
    return round(skin_score, 6)


def _normalize_categories(categories: list[str]) -> list[str]:
    normalized = []
    for category in categories:
        code = CATEGORY_ALIASES.get(category.strip().casefold())
        if code and code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ApiError(400, "AGENT_CART_CATEGORIES_INVALID", "토너, 세럼, 크림 중 필요한 카테고리를 알려주세요.")
    return normalized


def _normalize_avoid_ingredients(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _to_response_item(item: dict) -> AgentResponseItem:
    return AgentResponseItem(
        item_type="product",
        id=item["product_id"],
        title=item["title"],
        subtitle=f"{item['brand']} · {item['category_name']}",
        image_storage_key=item["image_storage_key"],
        price=item["price"],
        currency=item["currency"],
        metadata={"category_code": item["category_code"], "fit_score": item["fit_score"]},
    )


def _executed_response(tool_call_id: str, cart, message: str) -> AgentToolConfirmResponse:
    action = AgentUiAction(type="show_cart", target="cart", payload=jsonable_encoder(cart))
    validate_tool_ui_action(COMPOSE_CART_TOOL, action)
    return AgentToolConfirmResponse(
        tool_call_id=tool_call_id,
        status="EXECUTED",
        message=message,
        ui_action=action,
    )
