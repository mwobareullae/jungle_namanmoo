from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
import unicodedata

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductCategoryAlias, ProductIngredient, ProductSkinProfile
from app.db.models.commerce import Inventory, Wishlist
from app.db.models.taxonomy import Ingredient, IngredientAlias
from app.schemas.agent import AgentChatResponse, AgentError, AgentResponseItem, AgentToolConfirmResponse, AgentUiAction
from app.schemas.common import ApiError
from app.schemas.event import EventLogCreateRequest
from app.services.agent_policy import validate_result_item_count, validate_tool_ui_action
from app.services.event_service import create_event_logs
from app.services.popular_products_service import get_popular_product_items
from app.services.skin_profile_service import load_skin_profile_for_user


BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL = "bulk_wishlist_by_popular_ingredient"
BULK_WISHLIST_CONFIRMATION_TTL_MINUTES = 10
MAX_BULK_WISHLIST_RANK = 50
_CATEGORY_QUERY_ALIASES = {
    "세럼": "serum",
    "토너": "toner",
    "크림": "cream",
    "로션": "lotion",
}
_KOREAN_INGREDIENT_PARTICLE_SUFFIXES = ("은", "는", "이", "가", "을", "를", "와", "과")


def _prepare_legacy_bulk_wishlist_by_popular_ingredient(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    ingredient_name: str | None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    rank_limit: int,
    window_days: int,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    if ingredient_name and (skin_type or sensitivity):
        raise ApiError(400, "AGENT_WISHLIST_CRITERIA_INVALID", "성분 조건과 피부 조건은 한 번에 하나만 선택할 수 있어요.")
    if not ingredient_name and not skin_type and not sensitivity:
        profile = load_skin_profile_for_user(session, user.id)
        if profile is None:
            raise ApiError(400, "AGENT_SKIN_PROFILE_REQUIRED", "피부 타입이나 민감도 조건을 알려주세요.")
        skin_type = profile.explicit_skin_type or profile.skin_type
        sensitivity = profile.explicit_sensitivity or profile.sensitivity
    criterion_name = ingredient_name or _skin_criterion_name(skin_type, sensitivity)
    ingredient = _resolve_canonical_ingredient(session, ingredient_name) if ingredient_name else None
    popular_items = get_popular_product_items(
        session,
        window_days=window_days,
        limit=rank_limit,
        recommendable_only=False,
    )[:rank_limit]
    if not popular_items:
        raise ApiError(404, "AGENT_POPULAR_PRODUCTS_NOT_FOUND", "확인할 수 있는 인기 상품이 없어요.")

    product_codes = [item.product_id for item in popular_items]
    product_rows = session.execute(
        select(Product.id, Product.product_code).where(Product.product_code.in_(product_codes))
    ).all()
    db_id_by_code = {str(code): int(db_id) for db_id, code in product_rows}
    if ingredient is not None:
        matching_db_ids = set(
            session.execute(
                select(ProductIngredient.product_id).where(
                    ProductIngredient.product_id.in_(list(db_id_by_code.values())),
                    ProductIngredient.ingredient_id == ingredient.id,
                )
            ).scalars()
        )
    else:
        profiles = session.execute(
            select(ProductSkinProfile).where(
                ProductSkinProfile.product_id.in_(list(db_id_by_code.values()))
            )
        ).scalars()
        matching_db_ids = {
            int(profile.product_id)
            for profile in profiles
            if _matches_skin_profile(profile, skin_type=skin_type, sensitivity=sensitivity)
        }
    wished_db_ids = set(
        session.execute(
            select(Wishlist.product_id).where(
                Wishlist.user_id == user.id,
                Wishlist.product_id.in_(list(db_id_by_code.values())),
            )
        ).scalars()
    )

    matched = []
    for rank, item in enumerate(popular_items, start=1):
        db_product_id = db_id_by_code.get(item.product_id)
        if db_product_id is None or db_product_id not in matching_db_ids:
            continue
        matched.append(
            {
                "product_id": item.product_id,
                "db_product_id": db_product_id,
                "rank": rank,
                "brand": item.brand,
                "name": item.name,
                "image_storage_key": item.thumbnail_url,
                "already_wished": db_product_id in wished_db_ids,
                "popularity_score": item.popularity_score,
                "score_version": item.score_version,
                "computed_at": item.computed_at.isoformat(),
            }
        )

    if not matched:
        return _no_change_response(
            conversation_id,
            ingredient_name=criterion_name,
            message=f"인기 상품 {rank_limit}위 안에서 {criterion_name} 기준 상품을 찾지 못했어요.",
            inspected_count=len(popular_items),
            matched=[],
            rank_limit=rank_limit,
            window_days=window_days,
        )

    new_items = [item for item in matched if not item["already_wished"]]
    if not new_items:
        return _no_change_response(
            conversation_id,
            ingredient_name=criterion_name,
            message=f"조건에 맞는 {criterion_name} 상품 {len(matched)}개를 이미 모두 찜했어요.",
            inspected_count=len(popular_items),
            matched=matched,
            rank_limit=rank_limit,
            window_days=window_days,
        )

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=BULK_WISHLIST_CONFIRMATION_TTL_MINUTES)
    tool_call_id = f"tool_{secrets.token_urlsafe(18)}"
    payload = _result_payload(
        ingredient_name=criterion_name,
        inspected_count=len(popular_items),
        matched=matched,
        added_product_ids=[],
        window_days=window_days,
        rank_limit=rank_limit,
    )
    payload.update({"tool_call_id": tool_call_id, "confirmation_expires_at": expires_at.isoformat()})
    session.add(
        AgentToolCall(
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            user_id=user.id,
            anonymous_user_id=anonymous_user_id,
            session_id=session_id,
            request_id=request_id,
            tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
            status="AWAITING_CONFIRMATION",
            confirmation_required=True,
            expires_at=expires_at,
            input_json={
                "ingredient_name": ingredient.name_ko if ingredient is not None else None,
                "ingredient_id": int(ingredient.id) if ingredient is not None else None,
                "skin_type": skin_type,
                "sensitivity": sensitivity,
                "rank_limit": rank_limit,
                "window_days": window_days,
            },
            output_json=payload,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()

    action = AgentUiAction(type="open_modal", target="agent_confirmation", payload=jsonable_encoder(payload))
    items = [_to_response_item(item) for item in matched]
    validate_tool_ui_action(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, action)
    validate_result_item_count(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, len(items))
    already_count = len(matched) - len(new_items)
    return AgentChatResponse(
        conversation_id=conversation_id or f"conv_{secrets.token_urlsafe(12)}",
        message=(
            f"인기 상품 {rank_limit}위 안에서 {criterion_name} 기준 상품은 {len(matched)}개예요. "
            f"이미 찜한 {already_count}개를 제외하고 {len(new_items)}개를 새로 찜할까요?"
        ),
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        ui_action=action,
        items=items,
    )


def prepare_bulk_wishlist_by_popular_ingredient(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    ingredient_name: str | None,
    ingredient_names: list[str] | None = None,
    ingredient_match_mode: str = "all",
    category: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    rank_limit: int,
    window_days: int,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    """Preview a confirmation-gated wishlist write against stable popularity ranks.

    The legacy single-ingredient/profile path remains intact. Compound criteria use
    a separate path so the global popularity window is fixed before filters apply.
    """
    if not 1 <= rank_limit <= MAX_BULK_WISHLIST_RANK:
        raise ApiError(
            400,
            "AGENT_BULK_WISHLIST_RANK_LIMIT",
            "인기 상품은 상위 1위부터 50위 안에서만 선택할 수 있어요.",
        )
    raw_ingredient_names = _collect_ingredient_names(ingredient_name, ingredient_names)
    uses_only_legacy_criteria = (
        not ingredient_names
        and category is None
        and price_min is None
        and price_max is None
        and not (ingredient_name and (skin_type or sensitivity))
    )
    if uses_only_legacy_criteria:
        return _prepare_legacy_bulk_wishlist_by_popular_ingredient(
            session,
            user,
            conversation_id=conversation_id,
            ingredient_name=ingredient_name,
            skin_type=skin_type,
            sensitivity=sensitivity,
            rank_limit=rank_limit,
            window_days=window_days,
            request_id=request_id,
            session_id=session_id,
            anonymous_user_id=anonymous_user_id,
        )

    if price_min is not None and price_max is not None and price_min > price_max:
        raise ApiError(400, "AGENT_WISHLIST_PRICE_RANGE_INVALID", "최소 가격은 최대 가격보다 클 수 없어요.")
    if ingredient_match_mode not in {"all", "any"}:
        raise ApiError(400, "AGENT_WISHLIST_INGREDIENT_MATCH_INVALID", "성분 조건 방식이 올바르지 않아요.")

    if not raw_ingredient_names and category is None and price_min is None and price_max is None and not skin_type and not sensitivity:
        profile = load_skin_profile_for_user(session, user.id)
        if profile is None:
            raise ApiError(400, "AGENT_SKIN_PROFILE_REQUIRED", "피부 타입이나 민감도 조건을 알려주세요.")
        skin_type = profile.explicit_skin_type or profile.skin_type
        sensitivity = profile.explicit_sensitivity or profile.sensitivity

    ingredients_by_id: dict[int, Ingredient] = {}
    for raw_name in raw_ingredient_names:
        ingredient = _resolve_canonical_ingredient(session, raw_name)
        ingredients_by_id.setdefault(int(ingredient.id), ingredient)
    ingredients = list(ingredients_by_id.values())
    # Once aliases have been resolved and duplicates removed, all/any have the
    # same meaning for one ingredient. Persist one canonical shape so previews,
    # confirmations, and downstream evaluation do not depend on model wording.
    if len(ingredients) <= 1:
        ingredient_match_mode = "all"
    resolved_category = _resolve_canonical_category(session, category) if category else None
    criteria = _build_compound_criteria(
        ingredients=ingredients,
        ingredient_match_mode=ingredient_match_mode,
        category=resolved_category,
        price_min=price_min,
        price_max=price_max,
        skin_type=skin_type,
        sensitivity=sensitivity,
    )
    criterion_name = _criteria_label(criteria)

    # Rank first, then filter. A category/price condition must never redefine
    # what the user meant by "top 50".
    popular_items = get_popular_product_items(
        session,
        window_days=window_days,
        limit=rank_limit,
        recommendable_only=False,
    )[:rank_limit]
    if not popular_items:
        raise ApiError(404, "AGENT_POPULAR_PRODUCTS_NOT_FOUND", "확인할 수 있는 인기 상품이 없어요.")

    product_codes = [item.product_id for item in popular_items]
    product_rows = session.execute(
        select(Product.id, Product.product_code).where(Product.product_code.in_(product_codes))
    ).all()
    db_id_by_code = {str(code): int(db_id) for db_id, code in product_rows}
    candidate_db_ids = list(db_id_by_code.values())

    ingredient_ids_by_product: dict[int, set[int]] = {product_id: set() for product_id in candidate_db_ids}
    if ingredients and candidate_db_ids:
        for product_id, resolved_ingredient_id in session.execute(
            select(ProductIngredient.product_id, ProductIngredient.ingredient_id).where(
                ProductIngredient.product_id.in_(candidate_db_ids),
                ProductIngredient.ingredient_id.in_([ingredient.id for ingredient in ingredients]),
            )
        ):
            ingredient_ids_by_product.setdefault(int(product_id), set()).add(int(resolved_ingredient_id))

    profiles_by_product: dict[int, ProductSkinProfile] = {}
    if (skin_type or sensitivity) and candidate_db_ids:
        profiles_by_product = {
            int(profile.product_id): profile
            for profile in session.execute(
                select(ProductSkinProfile).where(ProductSkinProfile.product_id.in_(candidate_db_ids))
            ).scalars()
        }

    wished_db_ids = set(
        session.execute(
            select(Wishlist.product_id).where(
                Wishlist.user_id == user.id,
                Wishlist.product_id.in_(candidate_db_ids),
            )
        ).scalars()
    )
    required_ingredient_ids = {int(ingredient.id) for ingredient in ingredients}
    matched: list[dict] = []
    for rank, item in enumerate(popular_items, start=1):
        db_product_id = db_id_by_code.get(item.product_id)
        if db_product_id is None:
            continue
        product_ingredient_ids = ingredient_ids_by_product.get(db_product_id, set())
        if required_ingredient_ids:
            has_ingredient_match = (
                required_ingredient_ids.issubset(product_ingredient_ids)
                if ingredient_match_mode == "all"
                else bool(required_ingredient_ids.intersection(product_ingredient_ids))
            )
            if not has_ingredient_match:
                continue
        if (skin_type or sensitivity) and not _matches_skin_profile(
            profiles_by_product.get(db_product_id),
            skin_type=skin_type,
            sensitivity=sensitivity,
        ):
            continue
        if resolved_category is not None and item.category_code != resolved_category.category_code:
            continue
        if price_min is not None and int(item.lowest_price) < price_min:
            continue
        if price_max is not None and (not item.lowest_price or int(item.lowest_price) > price_max):
            continue
        matched.append(
            {
                "product_id": item.product_id,
                "db_product_id": db_product_id,
                "rank": rank,
                "brand": item.brand,
                "name": item.name,
                "category_code": item.category_code,
                "category_name": item.category_name,
                "lowest_price": int(item.lowest_price or 0),
                "image_storage_key": item.thumbnail_url,
                "already_wished": db_product_id in wished_db_ids,
                "popularity_score": item.popularity_score,
                "score_version": item.score_version,
                "computed_at": item.computed_at.isoformat(),
            }
        )

    if not matched:
        return _no_change_response(
            conversation_id,
            ingredient_name=criterion_name,
            message=f"인기 상품 상위 {rank_limit}위 안에서 {criterion_name} 조건에 맞는 상품을 찾지 못했어요.",
            inspected_count=len(popular_items),
            matched=[],
            rank_limit=rank_limit,
            window_days=window_days,
            criteria=criteria,
        )

    new_items = [item for item in matched if not item["already_wished"]]
    if not new_items:
        return _no_change_response(
            conversation_id,
            ingredient_name=criterion_name,
            message=f"{criterion_name} 조건에 맞는 상품 {len(matched)}개를 이미 모두 찜했어요.",
            inspected_count=len(popular_items),
            matched=matched,
            rank_limit=rank_limit,
            window_days=window_days,
            criteria=criteria,
        )

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=BULK_WISHLIST_CONFIRMATION_TTL_MINUTES)
    tool_call_id = f"tool_{secrets.token_urlsafe(18)}"
    payload = _result_payload(
        ingredient_name=criterion_name,
        inspected_count=len(popular_items),
        matched=matched,
        added_product_ids=[],
        window_days=window_days,
        rank_limit=rank_limit,
        criteria=criteria,
    )
    payload.update({"tool_call_id": tool_call_id, "confirmation_expires_at": expires_at.isoformat()})
    session.add(
        AgentToolCall(
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            user_id=user.id,
            anonymous_user_id=anonymous_user_id,
            session_id=session_id,
            request_id=request_id,
            tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
            status="AWAITING_CONFIRMATION",
            confirmation_required=True,
            expires_at=expires_at,
            input_json={
                "ingredient_name": ingredients[0].name_ko if len(ingredients) == 1 else None,
                "ingredient_names": [ingredient.name_ko for ingredient in ingredients],
                "ingredient_ids": [int(ingredient.id) for ingredient in ingredients],
                "ingredient_match_mode": ingredient_match_mode,
                "category": category,
                "category_code": resolved_category.category_code if resolved_category is not None else None,
                "price_min": price_min,
                "price_max": price_max,
                "skin_type": skin_type,
                "sensitivity": sensitivity,
                "rank_limit": rank_limit,
                "window_days": window_days,
            },
            output_json=payload,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()

    action = AgentUiAction(type="open_modal", target="agent_confirmation", payload=jsonable_encoder(payload))
    items = [_to_response_item(item) for item in matched]
    validate_tool_ui_action(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, action)
    validate_result_item_count(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, len(items))
    already_count = len(matched) - len(new_items)
    return AgentChatResponse(
        conversation_id=conversation_id or f"conv_{secrets.token_urlsafe(12)}",
        message=(
            f"인기 상품 상위 {rank_limit}위 안에서 {criterion_name} 조건에 맞는 상품은 {len(matched)}개예요. "
            f"이미 찜한 {already_count}개를 제외하고 {len(new_items)}개를 새로 찜할까요?"
        ),
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        ui_action=action,
        items=items,
    )


def _collect_ingredient_names(ingredient_name: str | None, ingredient_names: list[str] | None) -> list[str]:
    names = [name for name in [ingredient_name, *(ingredient_names or [])] if isinstance(name, str) and name.strip()]
    seen: set[str] = set()
    unique_names: list[str] = []
    for name in names:
        normalized = _normalize_ingredient_name(name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_names.append(name.strip())
    return unique_names


def _resolve_canonical_category(session: Session, raw_category: str) -> ProductCategory:
    normalized = _normalize_ingredient_name(raw_category)
    if not normalized:
        raise ApiError(400, "AGENT_CATEGORY_REQUIRED", "카테고리 조건을 알려주세요.")
    normalized = _CATEGORY_QUERY_ALIASES.get(normalized, normalized)
    categories = session.execute(select(ProductCategory).where(ProductCategory.is_active.is_(True))).scalars().all()
    direct_matches = [
        category
        for category in categories
        if normalized in {
            _normalize_ingredient_name(category.category_code),
            _normalize_ingredient_name(category.name),
        }
    ]
    aliases = session.execute(select(ProductCategoryAlias)).scalars().all()
    alias_category_ids = {
        int(alias.category_id)
        for alias in aliases
        if _normalize_ingredient_name(alias.normalized_alias or alias.alias) == normalized
    }
    matches = {int(category.id): category for category in [*direct_matches, *[item for item in categories if int(item.id) in alias_category_ids]]}
    if len(matches) == 1:
        return next(iter(matches.values()))
    if not matches:
        raise ApiError(404, "AGENT_CATEGORY_NOT_FOUND", "조건에 맞는 카테고리를 찾지 못했어요.")
    raise ApiError(400, "AGENT_CATEGORY_AMBIGUOUS", "카테고리 조건을 조금 더 구체적으로 알려주세요.")


def _build_compound_criteria(
    *,
    ingredients: list[Ingredient],
    ingredient_match_mode: str,
    category: ProductCategory | None,
    price_min: int | None,
    price_max: int | None,
    skin_type: str | None,
    sensitivity: str | None,
) -> dict:
    return {
        "ingredient_names": [ingredient.name_ko for ingredient in ingredients],
        "ingredient_match_mode": ingredient_match_mode if ingredients else None,
        "category": (
            {"category_code": category.category_code, "name": category.name}
            if category is not None
            else None
        ),
        "price_min": price_min,
        "price_max": price_max,
        "skin_type": skin_type,
        "sensitivity": sensitivity,
    }


def _criteria_label(criteria: dict) -> str:
    labels: list[str] = []
    ingredient_names = criteria.get("ingredient_names") or []
    if ingredient_names:
        joiner = "와 " if criteria.get("ingredient_match_mode") == "all" and len(ingredient_names) > 1 else ", "
        labels.append(f"{joiner.join(ingredient_names)} 성분")
    category = criteria.get("category")
    if isinstance(category, dict) and category.get("name"):
        labels.append(str(category["name"]))
    price_min = criteria.get("price_min")
    price_max = criteria.get("price_max")
    if price_min is not None or price_max is not None:
        if price_min is not None and price_max is not None:
            labels.append(f"{price_min:,}원~{price_max:,}원")
        elif price_min is not None:
            labels.append(f"{price_min:,}원 이상")
        else:
            labels.append(f"{price_max:,}원 이하")
    skin_type = criteria.get("skin_type")
    sensitivity = criteria.get("sensitivity")
    if skin_type or sensitivity:
        labels.append(_skin_criterion_name(skin_type, sensitivity))
    return " · ".join(labels) or "선택한"


def confirm_bulk_wishlist_by_popular_ingredient(
    session: Session,
    user: User,
    *,
    tool_call: AgentToolCall,
    action: str,
) -> AgentToolConfirmResponse:
    if tool_call.status == "EXECUTED":
        return _confirmed_response(tool_call, "이미 찜 목록에 반영된 요청이에요.")
    if tool_call.status != "AWAITING_CONFIRMATION":
        raise ApiError(409, "AGENT_TOOL_CALL_NOT_CONFIRMABLE", "현재 상태에서는 이 요청을 확인할 수 없어요.")

    now = datetime.now(UTC)
    if tool_call.expires_at is not None and _as_utc(tool_call.expires_at) <= now:
        tool_call.status = "EXPIRED"
        tool_call.updated_at = now
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="EXPIRED",
            message="찜 목록 반영 확인 시간이 만료됐어요. 다시 요청해 주세요.",
            ui_action=AgentUiAction(),
            error=AgentError(code="AGENT_TOOL_CALL_EXPIRED", message="확인 시간이 만료됐어요.", retryable=True),
        )
    if action == "reject":
        tool_call.status = "REJECTED"
        tool_call.updated_at = now
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="REJECTED",
            message="찜 목록에 반영하지 않았어요.",
            ui_action=AgentUiAction(),
        )
    if action != "confirm":
        raise ApiError(400, "AGENT_CONFIRM_ACTION_INVALID", "확인 응답을 처리할 수 없어요.")

    stored = dict(tool_call.output_json or {})
    products = stored.get("products")
    if not isinstance(products, list):
        raise ApiError(400, "AGENT_BULK_WISHLIST_INVALID", "저장된 찜 상품 정보를 확인할 수 없어요.")
    candidate_codes = [
        item.get("product_id")
        for item in products
        if isinstance(item, dict) and isinstance(item.get("product_id"), str) and not item.get("already_wished")
    ]
    active_rows = session.execute(
        select(Product.id, Product.product_code)
        .join(Brand, Product.brand_id == Brand.id)
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(
            Product.product_code.in_(candidate_codes),
            Product.is_active.is_(True),
            Brand.is_active.is_(True),
            ProductCategory.is_active.is_(True),
            or_(Inventory.id.is_(None), Inventory.sales_status != "HIDDEN"),
        )
    ).all()
    db_id_by_code = {str(code): int(db_id) for db_id, code in active_rows}
    existing_ids = set(
        session.execute(
            select(Wishlist.product_id).where(
                Wishlist.user_id == user.id,
                Wishlist.product_id.in_(list(db_id_by_code.values())),
            )
        ).scalars()
    )
    preview_already_codes = [
        str(item.get("product_id"))
        for item in products
        if isinstance(item, dict) and item.get("already_wished") and isinstance(item.get("product_id"), str)
    ]
    existing_codes = list(dict.fromkeys([
        *preview_already_codes,
        *[code for code in candidate_codes if db_id_by_code.get(code) in existing_ids],
    ]))
    added_codes = [code for code in candidate_codes if db_id_by_code.get(code) not in existing_ids and code in db_id_by_code]

    tool_call.status = "CONFIRMED"
    tool_call.confirmed_at = now
    tool_call.updated_at = now
    session.flush()
    try:
        with session.begin_nested():
            for code in added_codes:
                session.add(Wishlist(user_id=user.id, product_id=db_id_by_code[code], added_at=now, created_at=now))
            create_event_logs(
                session,
                [
                    EventLogCreateRequest(
                        event_id=f"agent_bulk_wishlist:{tool_call.tool_call_id}:{code}",
                        event_name="wishlist_added",
                        occurred_at=now,
                        product_id=code,
                        rank=_rank_for_product(products, code),
                        source="agent_bulk_wishlist",
                        page="products_popular",
                        metadata_json={"tool_call_id": tool_call.tool_call_id},
                    )
                    for code in added_codes
                ],
                current_user=user,
                fallback_request_id=tool_call.request_id,
                fallback_session_id=tool_call.session_id,
                fallback_anonymous_user_id=tool_call.anonymous_user_id,
            )
            session.flush()
    except SQLAlchemyError:
        failed_at = datetime.now(UTC)
        tool_call.status = "FAILED"
        tool_call.error_code = "AGENT_BULK_WISHLIST_SAVE_FAILED"
        tool_call.error_message = "찜 목록을 저장하지 못했어요."
        tool_call.updated_at = failed_at
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="FAILED",
            message="찜 목록을 저장하지 못했어요.",
            ui_action=AgentUiAction(),
            error=AgentError(code=tool_call.error_code, message=tool_call.error_message, retryable=True),
        )

    completed_at = datetime.now(UTC)
    output = _result_payload(
        ingredient_name=str(stored.get("ingredient_name") or "성분"),
        inspected_count=int(stored.get("inspected_count") or 0),
        matched=[item for item in products if isinstance(item, dict)],
        added_product_ids=added_codes,
        already_wished_product_ids=existing_codes,
        window_days=int(stored.get("window_days") or 7),
        rank_limit=int(stored.get("rank_limit") or MAX_BULK_WISHLIST_RANK),
        criteria=stored.get("criteria") if isinstance(stored.get("criteria"), dict) else None,
    )
    tool_call.status = "EXECUTED"
    tool_call.executed_at = completed_at
    tool_call.output_json = output
    tool_call.updated_at = completed_at
    session.flush()
    already_count = int(output["already_wished_count"])
    return _confirmed_response(
        tool_call,
        f"조건에 맞는 상품 {len(added_codes)}개를 찜 목록에 반영했어요. 이미 찜한 상품 {already_count}개는 그대로 유지했어요.",
    )


def _resolve_canonical_ingredient(session: Session, raw_name: str) -> Ingredient:
    normalized_variants = _normalized_ingredient_variants(raw_name)
    if not normalized_variants:
        raise ApiError(400, "AGENT_INGREDIENT_REQUIRED", "확인할 성분명을 알려주세요.")
    ingredients = session.execute(select(Ingredient).where(Ingredient.is_active.is_(True))).scalars().all()
    by_code = [
        item
        for item in ingredients
        if _normalize_ingredient_name(item.ingredient_code) in normalized_variants
    ]
    if by_code:
        return by_code[0]
    alias_rows = session.execute(select(IngredientAlias)).scalars().all()
    alias_ids = {
        int(alias.ingredient_id)
        for alias in alias_rows
        if _normalize_ingredient_name(alias.normalized_alias or alias.alias) in normalized_variants
    }
    by_alias = [item for item in ingredients if int(item.id) in alias_ids]
    if len(by_alias) == 1:
        return by_alias[0]
    by_name = [
        item
        for item in ingredients
        if normalized_variants.intersection(
            {
                _normalize_ingredient_name(item.name_ko),
                _normalize_ingredient_name(item.name_en or ""),
                _normalize_ingredient_name(item.normalized_name or ""),
            }
        )
    ]
    if len(by_name) == 1:
        return by_name[0]
    raise ApiError(404, "AGENT_INGREDIENT_NOT_FOUND", "등록된 성분명에서 정확히 일치하는 성분을 찾지 못했어요.")


def _normalize_ingredient_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return "".join(character for character in normalized if character.isalnum())


def _normalized_ingredient_variants(value: str) -> set[str]:
    normalized = _normalize_ingredient_name(value)
    if not normalized:
        return set()

    variants = {normalized}
    source = unicodedata.normalize("NFKC", value).casefold().strip(" \t\n\r,，.。!?！？·ㆍ-")
    for suffix in _KOREAN_INGREDIENT_PARTICLE_SUFFIXES:
        if source.endswith(suffix) and len(source) > len(suffix) + 1:
            stripped = _normalize_ingredient_name(source[: -len(suffix)])
            if stripped:
                variants.add(stripped)
            break
    return variants


def _skin_criterion_name(skin_type: str | None, sensitivity: str | None) -> str:
    if skin_type and sensitivity:
        return f"{skin_type}·민감도 {sensitivity}"
    if skin_type:
        return f"{skin_type} 피부"
    return f"민감도 {sensitivity}"


def _matches_skin_profile(
    profile: ProductSkinProfile | None,
    *,
    skin_type: str | None,
    sensitivity: str | None,
) -> bool:
    if profile is None:
        return False
    fit_by_type = {
        "건성": profile.dry_fit,
        "지성": profile.oily_fit,
        "복합성": profile.combination_fit,
        "중성": profile.normal_fit,
        "수부지": profile.dehydrated_oily_fit,
    }
    if skin_type and float(fit_by_type.get(skin_type, 0)) < 0.7:
        return False
    if sensitivity in {"높음", "민감", "민감성"} and float(profile.sensitive_fit) < 0.7:
        return False
    return True


def _result_payload(
    *,
    ingredient_name: str,
    inspected_count: int,
    matched: list[dict],
    added_product_ids: list[str],
    window_days: int,
    rank_limit: int,
    already_wished_product_ids: list[str] | None = None,
    criteria: dict | None = None,
) -> dict:
    matched_ids = [str(item["product_id"]) for item in matched]
    already_ids = already_wished_product_ids or [str(item["product_id"]) for item in matched if item.get("already_wished")]
    return {
        "ingredient_name": ingredient_name,
        "window_days": window_days,
        "rank_limit": rank_limit,
        "inspected_count": inspected_count,
        "matched_count": len(matched),
        "added_count": len(added_product_ids),
        "already_wished_count": len(already_ids),
        "matched_product_ids": matched_ids,
        "added_product_ids": added_product_ids,
        "already_wished_product_ids": list(dict.fromkeys(already_ids)),
        "criteria": criteria,
        "products": matched,
        "result_url": "/products/popular",
    }


def _to_response_item(item: dict) -> AgentResponseItem:
    wished_label = "이미 찜한 상품" if item["already_wished"] else "새로 찜할 상품"
    return AgentResponseItem(
        item_type="product",
        id=str(item["product_id"]),
        title=str(item["name"]),
        subtitle=f"{item['rank']}위 · {item['brand']} · {wished_label}",
        image_storage_key=str(item.get("image_storage_key") or "") or None,
        metadata={"rank": item["rank"], "brand": item["brand"], "already_wished": item["already_wished"]},
    )


def _no_change_response(
    conversation_id: str | None,
    *,
    ingredient_name: str,
    message: str,
    inspected_count: int,
    matched: list[dict],
    rank_limit: int,
    window_days: int,
    criteria: dict | None = None,
) -> AgentChatResponse:
    payload = _result_payload(
        ingredient_name=ingredient_name,
        inspected_count=inspected_count,
        matched=matched,
        added_product_ids=[],
        window_days=window_days,
        rank_limit=rank_limit,
        criteria=criteria,
    )
    action = AgentUiAction(type="show_products", target="popular_wishlist", payload=jsonable_encoder(payload))
    validate_tool_ui_action(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, action)
    return AgentChatResponse(
        conversation_id=conversation_id or f"conv_{secrets.token_urlsafe(12)}",
        message=message,
        tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        ui_action=action,
        items=[_to_response_item(item) for item in matched],
    )


def _confirmed_response(tool_call: AgentToolCall, message: str) -> AgentToolConfirmResponse:
    action = AgentUiAction(type="show_products", target="popular_wishlist", payload=jsonable_encoder(tool_call.output_json or {}))
    validate_tool_ui_action(BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL, action)
    return AgentToolConfirmResponse(tool_call_id=tool_call.tool_call_id, status="EXECUTED", message=message, ui_action=action)


def _rank_for_product(products: list, product_code: str) -> int | None:
    for item in products:
        if isinstance(item, dict) and item.get("product_id") == product_code and isinstance(item.get("rank"), int):
            return item["rank"]
    return None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
