"""관리자 취소 요청 목록·상세 조회 및 승인·거절 서비스 (P1-M1.5-B).

order_cancel_requests 는 고객이 결제완료 주문을 취소 신청할 때
order_cancel_service.cancel_order() 가 생성한다. 승인은
payment_cancel_service.cancel_paid_order() 를 재사용해 실제 취소를 처리하고,
거절은 Order 를 PAID 로 되돌려 배송·재신청이 가능한 상태로 복구한다.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest, OrderItem, Payment
from app.schemas.admin.order_cancel_request import (
    AdminOrderCancelRequestActionResponse,
    AdminOrderCancelRequestDetailResponse,
    AdminOrderCancelRequestItem,
    AdminOrderCancelRequestListResponse,
)
from app.schemas.common import ApiError
from app.services.payment_cancel_service import cancel_paid_order


CANCEL_REQUEST_STATUSES = {"REQUESTED", "APPROVED", "REJECTED"}
CANCEL_REQUEST_STATUS_REQUESTED = "REQUESTED"
CANCEL_REQUEST_STATUS_APPROVED = "APPROVED"
CANCEL_REQUEST_STATUS_REJECTED = "REJECTED"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
ORDER_STATUS_PAID = "PAID"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_PROVIDER_MOCK = "MOCK"

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def list_admin_cancel_requests(
    session: Session,
    *,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> AdminOrderCancelRequestListResponse:
    normalized_status = _normalize_status(status)
    normalized_limit = _normalize_limit(limit)
    cursor_request = _load_cursor_request(session, cursor)

    conditions = []
    if normalized_status is not None:
        conditions.append(OrderCancelRequest.status == normalized_status)
    if cursor_request is not None:
        conditions.append(
            (OrderCancelRequest.requested_at < cursor_request.requested_at)
            | (
                (OrderCancelRequest.requested_at == cursor_request.requested_at)
                & (OrderCancelRequest.id < cursor_request.id)
            )
        )

    rows = session.execute(
        select(OrderCancelRequest, Order, Payment)
        .join(Order, Order.id == OrderCancelRequest.order_id)
        .outerjoin(Payment, Payment.order_id == Order.id)
        .where(*conditions)
        .order_by(OrderCancelRequest.requested_at.desc(), OrderCancelRequest.id.desc())
        .limit(normalized_limit + 1)
    ).all()
    visible_rows = list(rows[:normalized_limit])

    users_by_id = _load_users_by_id(session, [int(order.user_id) for _request, order, _payment in visible_rows])
    items = [
        _to_list_item(request, order=order, payment=payment, user=users_by_id.get(int(order.user_id)))
        for request, order, payment in visible_rows
    ]
    next_cursor = str(visible_rows[-1][0].id) if len(rows) > normalized_limit and visible_rows else None
    return AdminOrderCancelRequestListResponse(items=items, next_cursor=next_cursor)


def get_admin_cancel_request(session: Session, request_code: str) -> AdminOrderCancelRequestDetailResponse:
    request, order, payment = _load_request_row(session, request_code)
    user = _load_users_by_id(session, [int(order.user_id)]).get(int(order.user_id))
    order_items = _load_order_items(session, order.id)

    list_item = _to_list_item(request, order=order, payment=payment, user=user)
    return AdminOrderCancelRequestDetailResponse(
        **list_item.model_dump(),
        order_status=order.status,
        payment_status=payment.status if payment is not None else None,
        payment_provider=payment.provider if payment is not None else None,
        product_summary=_product_summary(order_items, order.item_count),
        total_amount=order.total_amount,
        currency=order.currency,
    )


def approve_admin_cancel_request(session: Session, request_code: str) -> AdminOrderCancelRequestActionResponse:
    """취소 요청 승인. Order→Payment→Inventory 잠금·실행은 cancel_paid_order() 에 위임한다.

    OrderCancelRequest 는 이 함수 안에서만 잠그므로(다른 코드 경로가 손대지 않음), Order/Payment/
    Inventory 보다 나중에 잠그더라도 교착 위험은 없다 — 잠금 대상 집합이 겹치는 다른 트랜잭션이 없기 때문.
    """
    request = _load_cancel_request_for_update(session, request_code)
    if request.status == CANCEL_REQUEST_STATUS_REJECTED:
        raise ApiError(409, "CANCEL_REQUEST_ALREADY_REJECTED", "Cancel request was already rejected.")

    order = _load_order_readonly(session, request.order_id)
    result = cancel_paid_order(session, order.order_code)

    now = datetime.now(UTC)
    if request.status != CANCEL_REQUEST_STATUS_APPROVED:
        request.status = CANCEL_REQUEST_STATUS_APPROVED
        request.processed_at = now
        request.updated_at = now
        session.flush()

    return _to_action_response(request, order_status=result.order_status, order_code=order.order_code)


def reject_admin_cancel_request(
    session: Session, request_code: str, *, rejection_reason: str
) -> AdminOrderCancelRequestActionResponse:
    """취소 요청 거절. Order 를 CANCEL_REQUESTED→PAID 로 되돌려 배송·재신청이 가능하게 한다."""
    normalized_reason = rejection_reason.strip()
    if not normalized_reason:
        raise ApiError(400, "REJECTION_REASON_REQUIRED", "Rejection reason is required.")

    request = _load_cancel_request_for_update(session, request_code)
    if request.status == CANCEL_REQUEST_STATUS_APPROVED:
        raise ApiError(409, "CANCEL_REQUEST_ALREADY_APPROVED", "Cancel request was already approved.")

    order = _load_order_for_update(session, request.order_id)

    if request.status == CANCEL_REQUEST_STATUS_REJECTED:
        if order.status != ORDER_STATUS_PAID:
            raise ApiError(409, "ORDER_CANCEL_STATE_INCONSISTENT", "Order is not in the expected rejected state.")
        return _to_action_response(request, order_status=order.status, order_code=order.order_code)

    payment = _load_payment_for_update(session, order.id)
    if order.status != ORDER_STATUS_CANCEL_REQUESTED or payment is None or payment.status != PAYMENT_STATUS_APPROVED:
        raise ApiError(
            409,
            "ORDER_CANCEL_STATE_INCONSISTENT",
            "Order and payment are not in a rejectable state.",
        )

    now = datetime.now(UTC)
    order.status = ORDER_STATUS_PAID
    order.updated_at = now
    request.status = CANCEL_REQUEST_STATUS_REJECTED
    request.decision_reason = normalized_reason
    request.processed_at = now
    request.updated_at = now
    session.flush()

    return _to_action_response(request, order_status=order.status, order_code=order.order_code)


def _load_cancel_request_for_update(session: Session, request_code: str) -> OrderCancelRequest:
    normalized_code = request_code.strip()
    if not normalized_code:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.request_code == normalized_code).with_for_update()
    ).scalar_one_or_none()
    if request is None:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    return request


def _load_order_readonly(session: Session, order_id: int) -> Order:
    order = session.execute(select(Order).where(Order.id == order_id)).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _load_order_for_update(session: Session, order_id: int) -> Order:
    order = session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _load_payment_for_update(session: Session, order_id: int) -> Payment | None:
    return session.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    ).scalar_one_or_none()


def _to_action_response(
    request: OrderCancelRequest, *, order_status: str, order_code: str
) -> AdminOrderCancelRequestActionResponse:
    return AdminOrderCancelRequestActionResponse(
        request_code=request.request_code,
        order_code=order_code,
        status=request.status,
        order_status=order_status,
        decision_reason=request.decision_reason,
        processed_at=request.processed_at,
        available_actions=[],
    )


def _normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().upper()
    if not normalized:
        return None
    if normalized not in CANCEL_REQUEST_STATUSES:
        raise ApiError(400, "INVALID_CANCEL_REQUEST_STATUS", "Invalid cancel request status.")
    return normalized


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        raise ApiError(400, "INVALID_LIMIT", "limit must be at least 1.")
    return min(limit, MAX_LIMIT)


def _load_cursor_request(session: Session, cursor: str | None) -> OrderCancelRequest | None:
    if cursor is None or not cursor.strip():
        return None
    try:
        cursor_id = int(cursor)
    except ValueError as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.") from exc
    if cursor_id <= 0:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == cursor_id)
    ).scalar_one_or_none()
    if request is None:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    return request


def _load_request_row(
    session: Session, request_code: str
) -> tuple[OrderCancelRequest, Order, Payment | None]:
    normalized_code = request_code.strip()
    if not normalized_code:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    row = session.execute(
        select(OrderCancelRequest, Order, Payment)
        .join(Order, Order.id == OrderCancelRequest.order_id)
        .outerjoin(Payment, Payment.order_id == Order.id)
        .where(OrderCancelRequest.request_code == normalized_code)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    return row


def _load_order_items(session: Session, order_id: int) -> list[OrderItem]:
    return list(
        session.execute(
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id.asc())
        ).scalars()
    )


def _load_users_by_id(session: Session, user_ids: list[int]) -> dict[int, User]:
    unique_ids = list({user_id for user_id in user_ids})
    if not unique_ids:
        return {}
    rows = session.execute(select(User).where(User.id.in_(unique_ids))).scalars()
    return {int(user.id): user for user in rows}


def _to_list_item(
    request: OrderCancelRequest,
    *,
    order: Order,
    payment: Payment | None,
    user: User | None,
) -> AdminOrderCancelRequestItem:
    return AdminOrderCancelRequestItem(
        request_code=request.request_code,
        order_code=order.order_code,
        customer_id=int(order.user_id),
        customer_display=_customer_display(order, user),
        status=request.status,
        reason_code=request.reason_code,
        reason_detail=request.reason_detail,
        decision_reason=request.decision_reason,
        requested_at=request.requested_at,
        processed_at=request.processed_at,
        available_actions=_compute_available_actions(request, order, payment),
    )


def _compute_available_actions(
    request: OrderCancelRequest, order: Order, payment: Payment | None
) -> list[str]:
    if request.status != "REQUESTED" or order.status != ORDER_STATUS_CANCEL_REQUESTED:
        return []
    if payment is None or payment.status != PAYMENT_STATUS_APPROVED:
        return []
    actions = []
    if payment.provider == PAYMENT_PROVIDER_MOCK:
        actions.append("APPROVE")
    actions.append("REJECT")
    return actions


def _customer_display(order: Order, user: User | None) -> str:
    if user is not None and user.display_name:
        return user.display_name
    return f"user_{int(order.user_id)}"


def _product_summary(items: list[OrderItem], item_count: int) -> str:
    if not items:
        return "주문 상품"
    first_name = items[0].product_name_snapshot
    if item_count <= 1:
        return first_name
    return f"{first_name} 외 {item_count - 1}개"
