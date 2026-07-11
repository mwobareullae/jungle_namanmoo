"""관리자 주문·결제 조회 서비스 (P1-M1, 조회 전용).

기존 order_query_service 컨벤션을 따른다. 소비자 행동 EventLog 나 함수 단위
성능 로그는 남기지 않는다(요청 로그는 미들웨어가 자동 기록). 상태 변경 없음.

고객용 order_query_service.list_orders 와의 차이:
- user_id 필터 없음 → 전체 주문 조회(운영자 시야).
- order_status / payment_status 서버 필터(Payment outer join).
- 파생값: customer_display, product_summary, reserved_quantity, recommendation_ids.
- payment 레코드 누락 시 payment_status=None + payment_issue="PAYMENT_NOT_FOUND".
- 상단 요약 카드용 summary(전체 집계, 페이지·필터와 독립).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderItem, Payment
from app.schemas.admin.order import (
    AdminOrderListItem,
    AdminOrderListResponse,
    AdminOrderSummary,
)
from app.schemas.common import ApiError


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PREPARING_SHIPMENT = "PREPARING_SHIPMENT"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"

# db/models/commerce.py ORDER_STATUS_VALUES 와 정합
ORDER_STATUSES = {
    "PENDING_PAYMENT",
    "PAID",
    "PAYMENT_FAILED",
    "EXPIRED",
    "CANCELED",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
    "CANCEL_REQUESTED",
    "REFUND_REQUESTED",
    "REFUNDED",
    "RETURN_REQUESTED",
    "RETURNED",
    "EXCHANGE_REQUESTED",
    "EXCHANGED",
}

# db/models/commerce.py PAYMENT_STATUS_VALUES 와 정합
PAYMENT_STATUSES = {
    "READY",
    "CONFIRMING",
    "UNKNOWN",
    "APPROVED",
    "FAILED",
    "CANCELED",
    "EXPIRED",
    "REFUND_REQUESTED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
}

PAYMENT_ISSUE_NOT_FOUND = "PAYMENT_NOT_FOUND"

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def list_admin_orders(
    session: Session,
    *,
    order_status: str | None,
    payment_status: str | None,
    limit: int,
    cursor: str | None,
) -> AdminOrderListResponse:
    normalized_order_status = _normalize_order_status(order_status)
    normalized_payment_status = _normalize_payment_status(payment_status)
    normalized_limit = _normalize_limit(limit)
    cursor_order = _load_cursor_order(session, cursor)

    conditions = []
    if normalized_order_status is not None:
        conditions.append(Order.status == normalized_order_status)
    if normalized_payment_status is not None:
        # outer join + 이 조건 → 결제 레코드 없는 주문(NULL)은 자연히 제외됨
        conditions.append(Payment.status == normalized_payment_status)
    if cursor_order is not None:
        conditions.append(
            (Order.ordered_at < cursor_order.ordered_at)
            | ((Order.ordered_at == cursor_order.ordered_at) & (Order.id < cursor_order.id))
        )

    rows = session.execute(
        select(Order, Payment)
        .outerjoin(Payment, Payment.order_id == Order.id)
        .where(*conditions)
        .order_by(Order.ordered_at.desc(), Order.id.desc())
        .limit(normalized_limit + 1)
    ).all()
    visible_rows = list(rows[:normalized_limit])

    order_ids = [int(order.id) for order, _payment in visible_rows]
    items_by_order = _load_items_by_order(session, order_ids)
    users_by_id = _load_users_by_id(session, [int(order.user_id) for order, _payment in visible_rows])

    items = [
        _to_list_item(
            order,
            payment=payment,
            items=items_by_order.get(int(order.id), []),
            user=users_by_id.get(int(order.user_id)),
        )
        for order, payment in visible_rows
    ]
    next_cursor = (
        str(visible_rows[-1][0].id)
        if len(rows) > normalized_limit and visible_rows
        else None
    )
    return AdminOrderListResponse(
        items=items,
        summary=_compute_summary(session),
        next_cursor=next_cursor,
    )


def _normalize_order_status(order_status: str | None) -> str | None:
    if order_status is None:
        return None
    normalized = order_status.strip().upper()
    if not normalized:
        return None
    if normalized not in ORDER_STATUSES:
        raise ApiError(400, "INVALID_ORDER_STATUS", "Invalid order status.")
    return normalized


def _normalize_payment_status(payment_status: str | None) -> str | None:
    if payment_status is None:
        return None
    normalized = payment_status.strip().upper()
    if not normalized:
        return None
    if normalized not in PAYMENT_STATUSES:
        raise ApiError(400, "INVALID_PAYMENT_STATUS", "Invalid payment status.")
    return normalized


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        raise ApiError(400, "INVALID_LIMIT", "limit must be at least 1.")
    return min(limit, MAX_LIMIT)


def _load_cursor_order(session: Session, cursor: str | None) -> Order | None:
    if cursor is None or not cursor.strip():
        return None
    try:
        cursor_id = int(cursor)
    except ValueError as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.") from exc
    if cursor_id <= 0:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    order = session.execute(
        select(Order).where(Order.id == cursor_id)
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    return order


def _load_items_by_order(session: Session, order_ids: list[int]) -> dict[int, list[OrderItem]]:
    if not order_ids:
        return {}
    rows = session.execute(
        select(OrderItem)
        .where(OrderItem.order_id.in_(order_ids))
        .order_by(OrderItem.order_id.asc(), OrderItem.id.asc())
    ).scalars()
    grouped: dict[int, list[OrderItem]] = {}
    for row in rows:
        grouped.setdefault(int(row.order_id), []).append(row)
    return grouped


def _load_users_by_id(session: Session, user_ids: list[int]) -> dict[int, User]:
    unique_ids = list({user_id for user_id in user_ids})
    if not unique_ids:
        return {}
    rows = session.execute(select(User).where(User.id.in_(unique_ids))).scalars()
    return {int(user.id): user for user in rows}


def _to_list_item(
    order: Order,
    *,
    payment: Payment | None,
    items: list[OrderItem],
    user: User | None,
) -> AdminOrderListItem:
    if payment is not None:
        payment_status: str | None = payment.status
        payment_issue: str | None = None
    else:
        payment_status = None
        payment_issue = PAYMENT_ISSUE_NOT_FOUND

    return AdminOrderListItem(
        id=int(order.id),
        order_code=order.order_code,
        customer_id=int(order.user_id),
        customer_display=_customer_display(order, user),
        product_summary=_product_summary(items, order.item_count),
        item_count=order.item_count,
        total_quantity=order.total_quantity,
        total_amount=order.total_amount,
        currency=order.currency,
        order_status=order.status,
        payment_status=payment_status,
        payment_issue=payment_issue,
        reserved_quantity=_reserved_quantity(order),
        recommendation_ids=_recommendation_ids(items),
        updated_at=order.updated_at,
    )


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


def _reserved_quantity(order: Order) -> int:
    return order.total_quantity if order.status == ORDER_STATUS_PENDING_PAYMENT else 0


def _recommendation_ids(items: list[OrderItem]) -> list[str]:
    ids: list[str] = []
    for item in items:
        rid = item.recommendation_id
        if rid and rid not in ids:
            ids.append(rid)
    return ids


def _compute_summary(session: Session) -> AdminOrderSummary:
    status_counts = dict(
        session.execute(
            select(Order.status, func.count()).group_by(Order.status)
        ).all()
    )
    reserved_total = session.execute(
        select(func.coalesce(func.sum(Order.total_quantity), 0)).where(
            Order.status == ORDER_STATUS_PENDING_PAYMENT
        )
    ).scalar_one()
    return AdminOrderSummary(
        pending_payment_count=int(status_counts.get(ORDER_STATUS_PENDING_PAYMENT, 0)),
        preparing_shipment_count=int(status_counts.get(ORDER_STATUS_PREPARING_SHIPMENT, 0)),
        cancel_requested_count=int(status_counts.get(ORDER_STATUS_CANCEL_REQUESTED, 0)),
        reserved_quantity_total=int(reserved_total),
    )
