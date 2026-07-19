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

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderFulfillmentEvent, OrderItem, Payment
from app.schemas.admin.order import (
    AdminOrderListItem,
    AdminOrderListResponse,
    AdminOrderShipmentActionResponse,
    AdminOrderSummary,
)
from app.schemas.common import ApiError


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_PREPARING_SHIPMENT = "PREPARING_SHIPMENT"
ORDER_STATUS_SHIPPED = "SHIPPED"
ORDER_STATUS_DELIVERED = "DELIVERED"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"

ORDER_ITEM_STATUS_ORDERED = "ORDERED"

PAYMENT_STATUS_APPROVED = "APPROVED"

ACTION_START_PREPARATION = "START_PREPARATION"
ACTION_START_SHIPMENT = "START_SHIPMENT"
ACTION_COMPLETE_DELIVERY = "COMPLETE_DELIVERY"

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
        summary=get_admin_order_summary(session),
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
        ordered_at=order.ordered_at,
        paid_at=order.paid_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        available_actions=_compute_available_actions(order, payment),
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


def _compute_available_actions(order: Order, payment: Payment | None) -> list[str]:
    payment_approved = payment is not None and payment.status == PAYMENT_STATUS_APPROVED
    if not payment_approved:
        return []
    if order.status == ORDER_STATUS_PAID:
        return [ACTION_START_PREPARATION]
    if order.status == ORDER_STATUS_PREPARING_SHIPMENT:
        return [ACTION_START_SHIPMENT]
    if order.status == ORDER_STATUS_SHIPPED:
        return [ACTION_COMPLETE_DELIVERY]
    return []


def _recommendation_ids(items: list[OrderItem]) -> list[str]:
    ids: list[str] = []
    for item in items:
        rid = item.recommendation_id
        if rid and rid not in ids:
            ids.append(rid)
    return ids


# ---------------------------------------------------------------------------
# 배송 상태 전이 (M1.5-A, 쓰기)
#
# 순서 고정: PAID → PREPARING_SHIPMENT → SHIPPED → DELIVERED. 건너뛰기·되돌리기 불가.
# 세 전이 모두 결제 승인(Payment.status == APPROVED)을 먼저 확인한다(2026-07-13 결정).
# Order 와 그 하위 OrderItem 을 같은 트랜잭션에서 함께 바꾸고, 서비스는 flush 까지만 한다
# (commit 과 성공/실패 성능 로그는 router 담당, apps/backend/app/api/routes/admin/orders.py).
# ---------------------------------------------------------------------------


@dataclass
class ShipmentTransitionResult:
    """서비스 반환값. response 는 API 응답 그대로, 나머지는 router 가 commit 이후
    성능 로그를 남길 때 쓰는 부가 정보.

    updated_item_count 는 이번 전이에서 **실제로 상태를 바꾼 OrderItem 행 수**다
    (order.item_count 저장값이 아니라 UPDATE rowcount). 멱등 재요청은 아무 행도 바꾸지
    않으므로 0 이다.
    """

    response: AdminOrderShipmentActionResponse
    previous_status: str
    updated_item_count: int
    idempotent_replay: bool
    action: str


def start_preparation(session: Session, *, order_code: str) -> ShipmentTransitionResult:
    """결제완료(PAID) → 배송준비중(PREPARING_SHIPMENT).

    이미 PREPARING_SHIPMENT 면 멱등 성공(updated_at 갱신 없음). PAID 가 아니면 409.
    결제 레코드가 없거나 승인(APPROVED)되지 않았으면 409.
    """
    return _transition_shipping_order(
        session,
        order_code=order_code,
        expected_status=ORDER_STATUS_PAID,
        expected_item_status=ORDER_ITEM_STATUS_ORDERED,
        target_status=ORDER_STATUS_PREPARING_SHIPMENT,
        action=ACTION_START_PREPARATION,
    )


def start_shipment(session: Session, *, order_code: str) -> ShipmentTransitionResult:
    """배송준비중(PREPARING_SHIPMENT) → 배송중(SHIPPED).

    이미 SHIPPED 면 멱등 성공(updated_at 갱신 없음). PREPARING_SHIPMENT 가 아니면 409.
    결제 레코드가 없거나 승인(APPROVED)되지 않았으면 409.
    """
    return _transition_shipping_order(
        session,
        order_code=order_code,
        expected_status=ORDER_STATUS_PREPARING_SHIPMENT,
        expected_item_status=ORDER_STATUS_PREPARING_SHIPMENT,
        target_status=ORDER_STATUS_SHIPPED,
        action=ACTION_START_SHIPMENT,
    )


def complete_delivery(session: Session, *, order_code: str) -> ShipmentTransitionResult:
    """배송중(SHIPPED) → 배송완료(DELIVERED, 최종 상태).

    이미 DELIVERED 면 멱등 성공(updated_at 갱신 없음). SHIPPED 가 아니면 409.
    결제 레코드가 없거나 승인(APPROVED)되지 않았으면 409. DELIVERED 는 최종 상태라
    응답의 available_actions 는 항상 빈 목록이다.
    """
    return _transition_shipping_order(
        session,
        order_code=order_code,
        expected_status=ORDER_STATUS_SHIPPED,
        expected_item_status=ORDER_STATUS_SHIPPED,
        target_status=ORDER_STATUS_DELIVERED,
        action=ACTION_COMPLETE_DELIVERY,
    )


def _transition_shipping_order(
    session: Session,
    *,
    order_code: str,
    expected_status: str,
    expected_item_status: str,
    target_status: str,
    action: str,
) -> ShipmentTransitionResult:
    order = _load_order_for_update(session, order_code)
    previous_status = order.status

    # 멱등: 이미 목표 상태면 갱신 없이 성공 반환(updated_at 유지, 바뀐 행 0). 쓰기가
    # 없는 순수 조회이므로 Payment 는 잠그지 않는다(응답의 available_actions 계산에만 씀).
    # item_count 정합성은 이 경로도 똑같이 확인한다 — 그래야 "같은 손상 데이터인데
    # 어느 상태에서 접근했느냐에 따라 통과 여부가 갈리는" 상황이 안 생긴다.
    if order.status == target_status:
        payment = _load_payment_for_order(session, int(order.id), lock=False)
        if _count_order_items(session, int(order.id)) != order.item_count:
            raise ApiError(409, "ORDER_ITEMS_INCONSISTENT", "Order items are inconsistent.")
        return ShipmentTransitionResult(
            response=_to_shipment_response(order, payment),
            previous_status=previous_status,
            updated_item_count=0,
            idempotent_replay=True,
            action=action,
        )

    # 순서 고정: 기대 상태가 아니면 건너뛰기·되돌리기·그 외 상태 모두 차단.
    # Payment 조회(+잠금)보다 먼저 검사한다 — 어차피 거부될 요청이 결제 행 잠금을
    # 불필요하게 붙잡지 않도록.
    _require_status(
        order.status == expected_status,
        "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED",
        f"Order status must be {expected_status} for this action.",
    )

    # 여기서부터 실제로 상태를 바꾸므로 Payment 도 잠근다(결제 승인 확인 + 쓰기 공통)
    payment = _load_payment_for_order(session, int(order.id), lock=True)
    if payment is None:
        raise ApiError(409, "ORDER_PAYMENT_NOT_FOUND", "Payment record not found for this order.")
    _require_status(
        payment.status == PAYMENT_STATUS_APPROVED,
        "ORDER_PAYMENT_NOT_APPROVED",
        "Payment is not approved.",
    )

    now = datetime.now(UTC)
    order.status = target_status
    order.updated_at = now
    result = session.execute(
        update(OrderItem)
        .where(
            OrderItem.order_id == order.id,
            OrderItem.status == expected_item_status,
        )
        .values(status=target_status, updated_at=now)
    )
    updated_count = result.rowcount
    # rowcount 는 PEP 249상 "확인 불가"일 때 -1일 수 있다 — `or 0`으로는 안 걸러진다
    # (-1은 참으로 평가됨). None/음수/item_count 불일치를 모두 같은 오류로 취급한다.
    # router 가 롤백하면 방금 바꾼 Order 상태도 함께 취소된다.
    if updated_count is None or updated_count < 0 or updated_count != order.item_count:
        raise ApiError(409, "ORDER_ITEMS_INCONSISTENT", "Order items are inconsistent.")

    # item_count 정합성 확인을 통과한 뒤에만 배송 시각·이력을 남긴다(실제 전이 1건당 1건).
    # 예상 상태가 아닌 아이템이 하나라도 있으면 rowcount 가 item_count 보다 작아져 위에서
    # 거부된다. updated_at·배송 시각·이력 created_at 모두 같은 now 를 쓰며, 실패하면 router 의
    # rollback 으로 Order·OrderItem·이 두 가지도 전부 함께 원복된다(같은 세션·트랜잭션).
    if target_status == ORDER_STATUS_SHIPPED:
        order.shipped_at = now
    elif target_status == ORDER_STATUS_DELIVERED:
        order.delivered_at = now
    session.add(
        OrderFulfillmentEvent(
            order_id=order.id,
            from_status=previous_status,
            to_status=target_status,
            source="ADMIN",
            reason=action,
            created_at=now,
        )
    )
    session.flush()

    return ShipmentTransitionResult(
        response=_to_shipment_response(order, payment),
        previous_status=previous_status,
        updated_item_count=updated_count,
        idempotent_replay=False,
        action=action,
    )


def _require_status(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ApiError(409, code, message)


def _load_order_for_update(session: Session, order_code: str) -> Order:
    normalized_code = order_code.strip()
    if not normalized_code:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order not found.")
    order = session.execute(
        select(Order).where(Order.order_code == normalized_code).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order not found.")
    return order


def _load_payment_for_order(session: Session, order_id: int, *, lock: bool) -> Payment | None:
    # 쓰기 경로(lock=True)는 Order 를 잠근 뒤 Payment 도 함께 잠근다(order_cancel_service
    # 와 동일 순서) — 배송 승인 검증과 commit 사이에 결제가 CANCELED/REFUNDED 로 바뀌는
    # 경쟁을 막는다. 멱등 재요청처럼 아무것도 안 바꾸는 순수 조회는 lock=False 로 호출해
    # 불필요한 행 잠금을 피한다.
    statement = select(Payment).where(Payment.order_id == order_id)
    if lock:
        statement = statement.with_for_update()
    return session.execute(statement).scalar_one_or_none()


def _count_order_items(session: Session, order_id: int) -> int:
    return session.execute(
        select(func.count()).select_from(OrderItem).where(OrderItem.order_id == order_id)
    ).scalar_one()


def _to_shipment_response(order: Order, payment: Payment | None) -> AdminOrderShipmentActionResponse:
    return AdminOrderShipmentActionResponse(
        order_code=order.order_code,
        order_status=order.status,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        available_actions=_compute_available_actions(order, payment),
        updated_at=order.updated_at,
    )


def get_admin_order_summary(session: Session) -> AdminOrderSummary:
    """관리자 주문 목록과 대시보드가 공유하는 전체 현재 상태 요약을 반환한다."""
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
