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
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient
from app.db.models.commerce import Inventory, Wishlist
from app.db.models.taxonomy import Ingredient, IngredientAlias
from app.schemas.agent import AgentChatResponse, AgentError, AgentResponseItem, AgentToolConfirmResponse, AgentUiAction
from app.schemas.common import ApiError
from app.schemas.event import EventLogCreateRequest
from app.services.agent_policy import validate_result_item_count, validate_tool_ui_action
from app.services.event_service import create_event_logs
from app.services.popular_products_service import get_popular_product_items


BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL = "bulk_wishlist_by_popular_ingredient"
BULK_WISHLIST_CONFIRMATION_TTL_MINUTES = 10
MAX_BULK_WISHLIST_RANK = 20


def prepare_bulk_wishlist_by_popular_ingredient(
    session: Session,
    user: User,
    *,
    conversation_id: str | None,
    ingredient_name: str,
    rank_limit: int,
    window_days: int,
    request_id: str | None,
    session_id: str | None,
    anonymous_user_id: str | None,
) -> AgentChatResponse:
    ingredient = _resolve_canonical_ingredient(session, ingredient_name)
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
    matching_db_ids = set(
        session.execute(
            select(ProductIngredient.product_id).where(
                ProductIngredient.product_id.in_(list(db_id_by_code.values())),
                ProductIngredient.ingredient_id == ingredient.id,
            )
        ).scalars()
    )
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
            ingredient_name=ingredient.name_ko,
            message=f"인기 상품 {rank_limit}위 안에서 {ingredient.name_ko}가 확인된 상품을 찾지 못했어요.",
            inspected_count=len(popular_items),
            matched=[],
            rank_limit=rank_limit,
            window_days=window_days,
        )

    new_items = [item for item in matched if not item["already_wished"]]
    if not new_items:
        return _no_change_response(
            conversation_id,
            ingredient_name=ingredient.name_ko,
            message=f"조건에 맞는 상품 {len(matched)}개를 이미 모두 찜했어요.",
            inspected_count=len(popular_items),
            matched=matched,
            rank_limit=rank_limit,
            window_days=window_days,
        )

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=BULK_WISHLIST_CONFIRMATION_TTL_MINUTES)
    tool_call_id = f"tool_{secrets.token_urlsafe(18)}"
    payload = _result_payload(
        ingredient_name=ingredient.name_ko,
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
                "ingredient_name": ingredient.name_ko,
                "ingredient_id": int(ingredient.id),
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
            f"인기 상품 {rank_limit}위 안에서 {ingredient.name_ko}가 확인된 상품은 {len(matched)}개예요. "
            f"이미 찜한 {already_count}개를 제외하고 {len(new_items)}개를 새로 찜할까요?"
        ),
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        ui_action=action,
        items=items,
    )


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
    normalized = _normalize_ingredient_name(raw_name)
    if not normalized:
        raise ApiError(400, "AGENT_INGREDIENT_REQUIRED", "확인할 성분명을 알려주세요.")
    ingredients = session.execute(select(Ingredient).where(Ingredient.is_active.is_(True))).scalars().all()
    by_code = [item for item in ingredients if _normalize_ingredient_name(item.ingredient_code) == normalized]
    if by_code:
        return by_code[0]
    alias_rows = session.execute(select(IngredientAlias)).scalars().all()
    alias_ids = {
        int(alias.ingredient_id)
        for alias in alias_rows
        if _normalize_ingredient_name(alias.normalized_alias or alias.alias) == normalized
    }
    by_alias = [item for item in ingredients if int(item.id) in alias_ids]
    if len(by_alias) == 1:
        return by_alias[0]
    by_name = [
        item
        for item in ingredients
        if normalized in {_normalize_ingredient_name(item.name_ko), _normalize_ingredient_name(item.name_en or ""), _normalize_ingredient_name(item.normalized_name or "")}
    ]
    if len(by_name) == 1:
        return by_name[0]
    raise ApiError(404, "AGENT_INGREDIENT_NOT_FOUND", "등록된 성분명에서 정확히 일치하는 성분을 찾지 못했어요.")


def _normalize_ingredient_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return "".join(character for character in normalized if character.isalnum())


def _result_payload(
    *,
    ingredient_name: str,
    inspected_count: int,
    matched: list[dict],
    added_product_ids: list[str],
    window_days: int,
    rank_limit: int,
    already_wished_product_ids: list[str] | None = None,
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
) -> AgentChatResponse:
    payload = _result_payload(
        ingredient_name=ingredient_name,
        inspected_count=inspected_count,
        matched=matched,
        added_product_ids=[],
        window_days=window_days,
        rank_limit=rank_limit,
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
