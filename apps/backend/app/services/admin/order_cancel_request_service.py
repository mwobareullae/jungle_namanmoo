"""관리자 취소 요청 목록·상세 조회 서비스 (P1-M1.5-B, 조회 전용).

order_cancel_requests 는 고객이 결제완료 주문을 취소 신청할 때
order_cancel_service.cancel_order() 가 생성한다. 이 서비스는 조회만 담당하며,
승인·거절 실행은 payment_cancel_service.cancel_paid_order() 를 재사용하는
별도 서비스에서 처리한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest, OrderItem, Payment
from app.schemas.admin.order_cancel_request import (
    AdminOrderCancelRequestDetailResponse,
    AdminOrderCancelRequestItem,
    AdminOrderCancelRequestListResponse,
)
from app.schemas.common import ApiError


CANCEL_REQUEST_STATUSES = {"REQUESTED", "APPROVED", "REJECTED"}
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
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
