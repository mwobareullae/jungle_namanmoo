from datetime import UTC, datetime, timedelta
import secrets
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.commerce import Order
from app.schemas.agent import (
    AgentChatResponse,
    AgentError,
    AgentResponseItem,
    AgentToolConfirmResponse,
    AgentUiAction,
)
from app.schemas.common import ApiError
from app.schemas.order import OrderDetailResponse
from app.services.agent_policy import (
    validate_result_item_count,
    validate_tool_access,
    validate_tool_ui_action,
)
from app.services.order_cancel_service import cancel_order
from app.services.order_query_service import get_order_detail, list_orders


CANCEL_RECENT_ORDER_TOOL = "cancel_recent_order"
FILTER_ORDER_HISTORY_TOOL = "filter_order_history"
ORDER_STATUS_LOOKUP_TOOL = "order_status_lookup"
CANCEL_CONFIRMATION_TTL_MINUTES = 10
CANCELABLE_ORDER_STATUSES = {"PENDING_PAYMENT", "PAID"}
ORDER_STATUS_LABELS = {
    "PENDING_PAYMENT": "결제 대기",
    "PAID": "결제 완료",
    "PREPARING_SHIPMENT": "배송 준비 중",
    "SHIPPED": "배송 중",
    "DELIVERED": "배송 완료",
    "CANCEL_REQUESTED": "취소 요청",
    "CANCELED": "취소 완료",
}
PAYMENT_STATUS_LABELS = {
    "PENDING": "결제 대기",
    "PAID": "결제 완료",
    "CANCELED": "결제 취소",
    "FAILED": "결제 실패",
}


def filter_order_history(
    user: User,
    *,
    conversation_id: str | None = None,
    period_months: int | None = None,
    status: str | None = None,
) -> AgentChatResponse:
    validate_tool_access(FILTER_ORDER_HISTORY_TOOL, user_id=user.id)
    payload: dict[str, Any] = {}
    if period_months is not None:
        payload["period_months"] = period_months
    if status is not None:
        payload["status"] = status

    action = AgentUiAction(type="navigate", target="order_history", payload=payload)
    validate_result_item_count(FILTER_ORDER_HISTORY_TOOL, 0)
    validate_tool_ui_action(FILTER_ORDER_HISTORY_TOOL, action)

    period_copy = f"최근 {period_months}개월" if period_months and period_months < 12 else "최근 1년"
    status_labels = {
        "ALL": "전체 상태",
        "PENDING_PAYMENT": "주문접수",
        "PAID": "결제완료",
        "PREPARING_SHIPMENT": "배송준비중",
        "SHIPPED": "배송중",
        "DELIVERED": "배송완료",
    }
    status_copy = f", {status_labels[status]}만" if status else ""
    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message=f"{period_copy} 주문 내역{status_copy} 보이도록 화면에 반영했어요.",
        tool_name=FILTER_ORDER_HISTORY_TOOL,
        ui_action=action,
        items=[],
    )


def lookup_order_status(
    session: Session,
    user: User,
    *,
    conversation_id: str | None = None,
    order_code: str | None = None,
) -> AgentChatResponse:
    validate_tool_access(ORDER_STATUS_LOOKUP_TOOL, user_id=user.id)

    detail = _load_order_detail_for_tool(session, user, order_code)
    item = _to_order_response_item(detail)
    validate_result_item_count(ORDER_STATUS_LOOKUP_TOOL, 1)
    action = AgentUiAction(
        type="show_order_status",
        target="order_status",
        payload=_to_order_status_payload(detail),
    )
    validate_tool_ui_action(ORDER_STATUS_LOOKUP_TOOL, action)

    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message=_build_order_status_message(detail),
        tool_name=ORDER_STATUS_LOOKUP_TOOL,
        ui_action=action,
        items=[item],
    )


def prepare_recent_order_cancel(
    session: Session,
    user: User,
    *,
    conversation_id: str | None = None,
    order_code: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    anonymous_user_id: str | None = None,
) -> AgentChatResponse:
    started_at = time.perf_counter()
    validate_tool_access(CANCEL_RECENT_ORDER_TOOL, user_id=user.id)

    order = _load_cancelable_order(session, user.id, order_code)
    detail = get_order_detail(session, user, order.order_code)
    validate_result_item_count(CANCEL_RECENT_ORDER_TOOL, 1)
    now = datetime.now(UTC)
    tool_call_id = _generate_tool_call_id()
    expires_at = now + timedelta(minutes=CANCEL_CONFIRMATION_TTL_MINUTES)
    output_payload = _to_cancel_confirmation_payload(detail, tool_call_id, expires_at)

    tool_call = AgentToolCall(
        tool_call_id=tool_call_id,
        conversation_id=conversation_id,
        user_id=user.id,
        anonymous_user_id=anonymous_user_id,
        session_id=session_id,
        request_id=request_id,
        tool_name=CANCEL_RECENT_ORDER_TOOL,
        status="AWAITING_CONFIRMATION",
        confirmation_required=True,
        expires_at=expires_at,
        input_json={
            "order_code": detail.order_code,
            "requested_action": "cancel_order",
        },
        output_json=output_payload,
        latency_ms=_elapsed_ms(started_at),
        created_at=now,
        updated_at=now,
    )
    session.add(tool_call)
    session.flush()

    action = AgentUiAction(
        type="open_modal",
        target="order_cancel_confirm",
        payload=output_payload,
    )
    validate_tool_ui_action(CANCEL_RECENT_ORDER_TOOL, action)
    return AgentChatResponse(
        conversation_id=_resolve_conversation_id(conversation_id),
        message=_build_cancel_confirmation_message(detail),
        requires_confirmation=True,
        tool_call_id=tool_call_id,
        tool_name=CANCEL_RECENT_ORDER_TOOL,
        ui_action=action,
        items=[_to_order_response_item(detail)],
    )


def confirm_agent_tool_call(
    session: Session,
    user: User,
    *,
    tool_call_id: str,
    action: str,
) -> AgentToolConfirmResponse:
    started_at = time.perf_counter()
    tool_call = _load_user_tool_call_for_update(session, user.id, tool_call_id)
    validate_tool_access(tool_call.tool_name, user_id=user.id)

    from app.services.agent_commerce_tools import PREPARE_ORDER_TOOL
    from app.services.agent_cart_composer import COMPOSE_CART_TOOL, confirm_composed_cart
    from app.services.agent_bulk_wishlist import (
        BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL,
        confirm_bulk_wishlist_by_popular_ingredient,
    )

    if tool_call.tool_name == BULK_WISHLIST_BY_POPULAR_INGREDIENT_TOOL:
        return confirm_bulk_wishlist_by_popular_ingredient(session, user, tool_call=tool_call, action=action)

    if tool_call.tool_name == COMPOSE_CART_TOOL:
        return confirm_composed_cart(session, user, tool_call=tool_call, action=action)

    if tool_call.tool_name == PREPARE_ORDER_TOOL:
        return _confirm_prepared_order_tool_call(
            session,
            user,
            tool_call=tool_call,
            action=action,
            started_at=started_at,
        )

    if tool_call.tool_name != CANCEL_RECENT_ORDER_TOOL:
        raise ApiError(400, "AGENT_TOOL_CONFIRM_UNSUPPORTED", "확인할 수 없는 요청이에요.")
    if tool_call.status == "EXECUTED":
        return _already_executed_response(tool_call)
    if tool_call.status not in {"AWAITING_CONFIRMATION", "CONFIRMED"}:
        raise ApiError(409, "AGENT_TOOL_CALL_NOT_CONFIRMABLE", "현재 상태에서는 이 요청을 확인할 수 없어요.")

    now = datetime.now(UTC)
    if tool_call.expires_at is not None and _as_utc(tool_call.expires_at) <= now:
        tool_call.status = "EXPIRED"
        tool_call.error_code = "AGENT_TOOL_CALL_EXPIRED"
        tool_call.error_message = "확인 시간이 만료됐어요."
        tool_call.updated_at = now
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="EXPIRED",
            message="주문 취소 확인 시간이 만료됐어요. 다시 요청해 주세요.",
            ui_action=AgentUiAction(),
            error=AgentError(
                code="AGENT_TOOL_CALL_EXPIRED",
                message="확인 시간이 만료됐어요.",
                retryable=True,
            ),
        )

    if action == "reject":
        tool_call.status = "REJECTED"
        tool_call.updated_at = now
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="REJECTED",
            message="주문 취소를 진행하지 않았어요.",
            ui_action=AgentUiAction(),
        )
    if action != "confirm":
        raise ApiError(400, "AGENT_CONFIRM_ACTION_INVALID", "확인 응답을 처리할 수 없어요.")

    order_code = _get_tool_call_order_code(tool_call)
    tool_call.status = "CONFIRMED"
    tool_call.confirmed_at = now
    tool_call.updated_at = now
    session.flush()

    try:
        cancel_response = cancel_order(session, user, order_code)
    except ApiError as exc:
        tool_call.status = "FAILED"
        tool_call.error_code = exc.code
        tool_call.error_message = exc.message
        tool_call.updated_at = datetime.now(UTC)
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="FAILED",
            message="주문 취소를 완료하지 못했어요.",
            ui_action=AgentUiAction(),
            error=AgentError(code=exc.code, message=exc.message, retryable=False),
        )

    completed_at = datetime.now(UTC)
    output_json = dict(tool_call.output_json or {})
    output_json["final_order_status"] = cancel_response.status
    output_json["executed_at"] = _isoformat_utc(completed_at)
    tool_call.status = "EXECUTED"
    tool_call.executed_at = completed_at
    tool_call.output_json = output_json
    tool_call.updated_at = completed_at
    tool_call.latency_ms = _elapsed_ms(started_at)
    session.flush()

    ui_action = AgentUiAction(
        type="show_order_status",
        target="order_status",
        payload={
            "order_code": cancel_response.order_code,
            "status": cancel_response.status,
        },
    )
    validate_tool_ui_action(CANCEL_RECENT_ORDER_TOOL, ui_action)
    return AgentToolConfirmResponse(
        tool_call_id=tool_call.tool_call_id,
        status="EXECUTED",
        message=_build_cancel_executed_message(cancel_response.status),
        ui_action=ui_action,
    )


def _confirm_prepared_order_tool_call(
    session: Session,
    user: User,
    *,
    tool_call: AgentToolCall,
    action: str,
    started_at: float,
) -> AgentToolConfirmResponse:
    from app.services.agent_commerce_tools import execute_confirmed_agent_order

    if tool_call.status == "EXECUTED":
        output = dict(tool_call.output_json or {})
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="EXECUTED",
            message="이미 생성된 주문이에요. Toss 결제를 진행해 주세요.",
            ui_action=AgentUiAction(type="open_payment", target="toss_payment", payload=output),
        )
    if tool_call.status not in {"AWAITING_CONFIRMATION", "CONFIRMED"}:
        raise ApiError(409, "AGENT_TOOL_CALL_NOT_CONFIRMABLE", "현재 상태에서는 이 요청을 확인할 수 없어요.")

    now = datetime.now(UTC)
    if tool_call.expires_at is not None and _as_utc(tool_call.expires_at) <= now:
        tool_call.status = "EXPIRED"
        tool_call.error_code = "AGENT_TOOL_CALL_EXPIRED"
        tool_call.error_message = "확인 시간이 만료됐어요."
        tool_call.updated_at = now
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="EXPIRED",
            message="주문 확인 시간이 만료됐어요. 다시 요청해 주세요.",
            ui_action=AgentUiAction(),
            error=AgentError(code="AGENT_TOOL_CALL_EXPIRED", message="확인 시간이 만료됐어요.", retryable=True),
        )
    if action == "reject":
        tool_call.status = "REJECTED"
        tool_call.updated_at = now
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="REJECTED",
            message="주문을 생성하지 않았어요.",
            ui_action=AgentUiAction(),
        )
    if action != "confirm":
        raise ApiError(400, "AGENT_CONFIRM_ACTION_INVALID", "확인 응답을 처리할 수 없어요.")

    tool_call.status = "CONFIRMED"
    tool_call.confirmed_at = now
    tool_call.updated_at = now
    session.flush()
    try:
        response = execute_confirmed_agent_order(session, user, tool_call)
    except ApiError as exc:
        tool_call.status = "FAILED"
        tool_call.error_code = exc.code
        tool_call.error_message = exc.message
        tool_call.updated_at = datetime.now(UTC)
        tool_call.latency_ms = _elapsed_ms(started_at)
        session.flush()
        return AgentToolConfirmResponse(
            tool_call_id=tool_call.tool_call_id,
            status="FAILED",
            message="주문을 생성하지 못했어요.",
            ui_action=AgentUiAction(),
            error=AgentError(code=exc.code, message=exc.message, retryable=False),
        )

    completed_at = datetime.now(UTC)
    tool_call.status = "EXECUTED"
    tool_call.executed_at = completed_at
    tool_call.output_json = dict(response.ui_action.payload)
    tool_call.updated_at = completed_at
    tool_call.latency_ms = _elapsed_ms(started_at)
    session.flush()
    return response


def _load_order_detail_for_tool(
    session: Session,
    user: User,
    order_code: str | None,
) -> OrderDetailResponse:
    normalized_code = _normalize_optional_text(order_code)
    if normalized_code is not None:
        return get_order_detail(session, user, normalized_code)

    orders = list_orders(session, user, status=None, limit=1, cursor=None)
    if not orders.items:
        raise ApiError(404, "AGENT_ORDER_NOT_FOUND", "주문 내역을 찾지 못했어요.")
    return get_order_detail(session, user, orders.items[0].order_code)


def _load_cancelable_order(
    session: Session,
    user_id: int,
    order_code: str | None,
) -> Order:
    normalized_code = _normalize_optional_text(order_code)
    if normalized_code is not None:
        order = session.execute(
            select(Order).where(
                Order.order_code == normalized_code,
                Order.user_id == user_id,
            )
        ).scalar_one_or_none()
        if order is None:
            raise ApiError(404, "ORDER_NOT_FOUND", "주문을 찾지 못했어요.")
        if order.status not in CANCELABLE_ORDER_STATUSES:
            raise ApiError(409, "ORDER_NOT_CANCELABLE", "현재 상태에서는 주문을 취소할 수 없어요.")
        return order

    conditions = [
        Order.user_id == user_id,
        Order.status.in_(CANCELABLE_ORDER_STATUSES),
    ]
    statement = (
        select(Order)
        .where(*conditions)
        .order_by(Order.ordered_at.desc(), Order.id.desc())
        .limit(1)
    )
    order = session.execute(statement).scalars().first()
    if order is None:
        raise ApiError(404, "AGENT_CANCELABLE_ORDER_NOT_FOUND", "취소할 수 있는 최근 주문을 찾지 못했어요.")
    return order


def _load_user_tool_call_for_update(
    session: Session,
    user_id: int,
    tool_call_id: str,
) -> AgentToolCall:
    normalized_id = tool_call_id.strip()
    if not normalized_id:
        raise ApiError(404, "AGENT_TOOL_CALL_NOT_FOUND", "실행 요청을 찾지 못했어요.")
    tool_call = session.execute(
        select(AgentToolCall)
        .where(
            AgentToolCall.tool_call_id == normalized_id,
            AgentToolCall.user_id == user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if tool_call is None:
        raise ApiError(404, "AGENT_TOOL_CALL_NOT_FOUND", "실행 요청을 찾지 못했어요.")
    return tool_call


def _to_order_response_item(detail: OrderDetailResponse) -> AgentResponseItem:
    first_item = detail.items[0] if detail.items else None
    return AgentResponseItem(
        item_type="order",
        id=detail.order_code,
        title=_build_order_title(detail),
        subtitle=(
            f"{_order_status_label(detail.status)} / "
            f"{_payment_status_label(detail.payment.status)}"
        ),
        image_storage_key=first_item.thumbnail_storage_key if first_item else None,
        price=detail.total,
        currency=detail.currency,
        metadata={
            "order_status": detail.status,
            "payment_status": detail.payment.status,
            "item_count": len(detail.items),
        },
    )


def _to_order_status_payload(detail: OrderDetailResponse) -> dict[str, Any]:
    return {
        "order_code": detail.order_code,
        "order_status": detail.status,
        "payment_status": detail.payment.status,
        "payment_code": detail.payment.payment_code,
        "total": detail.total,
        "currency": detail.currency,
        "ordered_at": _isoformat_utc(detail.ordered_at),
        "paid_at": _isoformat_utc(detail.paid_at),
        "payment_expires_at": _isoformat_utc(detail.payment_expires_at),
        "item_count": len(detail.items),
        "title": _build_order_title(detail),
        "can_cancel": detail.status in CANCELABLE_ORDER_STATUSES,
    }


def _to_cancel_confirmation_payload(
    detail: OrderDetailResponse,
    tool_call_id: str,
    expires_at: datetime,
) -> dict[str, Any]:
    payload = _to_order_status_payload(detail)
    payload.update(
        {
            "tool_call_id": tool_call_id,
            "confirmation_expires_at": _isoformat_utc(expires_at),
            "message": _build_cancel_confirmation_message(detail),
        }
    )
    return payload


def _get_tool_call_order_code(tool_call: AgentToolCall) -> str:
    for payload in (tool_call.output_json, tool_call.input_json):
        value = (payload or {}).get("order_code")
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ApiError(409, "AGENT_TOOL_CALL_INVALID", "주문번호가 없어 요청을 이어갈 수 없어요.")


def _already_executed_response(tool_call: AgentToolCall) -> AgentToolConfirmResponse:
    payload = tool_call.output_json or {}
    order_code = payload.get("order_code")
    status = payload.get("final_order_status") or payload.get("order_status")
    action = AgentUiAction(
        type="show_order_status",
        target="order_status",
        payload={
            "order_code": order_code,
            "status": status,
        },
    )
    validate_tool_ui_action(CANCEL_RECENT_ORDER_TOOL, action)
    return AgentToolConfirmResponse(
        tool_call_id=tool_call.tool_call_id,
        status="EXECUTED",
        message="이미 처리된 요청이에요.",
        ui_action=action,
    )


def _build_order_title(detail: OrderDetailResponse) -> str:
    if not detail.items:
        return "주문"
    first_item_name = detail.items[0].product_name
    if len(detail.items) == 1:
        return first_item_name
    return f"{first_item_name} 외 {len(detail.items) - 1}개"


def _order_status_label(status: str) -> str:
    return ORDER_STATUS_LABELS.get(status, status)


def _payment_status_label(status: str) -> str:
    return PAYMENT_STATUS_LABELS.get(status, status)


def _build_order_status_message(detail: OrderDetailResponse) -> str:
    return f"주문 {detail.order_code}의 현재 상태는 {_order_status_label(detail.status)}예요."


def _build_cancel_confirmation_message(detail: OrderDetailResponse) -> str:
    if detail.status == "PENDING_PAYMENT":
        return "결제 전 주문이라 즉시 취소돼요. 주문 취소를 진행할까요?"
    if detail.status == "PAID":
        return "결제 완료 주문의 취소를 요청할까요?"
    return "주문 취소를 진행할까요?"


def _build_cancel_executed_message(status: str) -> str:
    if status == "CANCELED":
        return "주문 취소가 완료됐어요."
    if status == "CANCEL_REQUESTED":
        return "주문 취소를 요청했어요. 처리 결과를 확인하고 있어요."
    return f"주문 취소 처리 상태는 {status}예요."


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_conversation_id(conversation_id: str | None) -> str:
    normalized = _normalize_optional_text(conversation_id)
    if normalized is not None:
        return normalized
    return f"conv_{secrets.token_urlsafe(12).replace('-', '').replace('_', '')[:16]}"


def _generate_tool_call_id() -> str:
    return f"tool_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def _elapsed_ms(started_at: float) -> int:
    return max(int((time.perf_counter() - started_at) * 1000), 0)


def _isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
