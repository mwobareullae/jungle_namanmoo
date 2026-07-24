"""관리자 취소 요청 목록·상세 조회 및 승인·거절 서비스 (P1-M1.5-B).

order_cancel_requests 는 고객이 결제완료 주문을 취소 신청할 때
order_cancel_service.cancel_order() 가 생성한다. 승인은
payment_cancel_service.cancel_paid_order() 를 재사용해 실제 취소를 처리하고,
거절은 Order 를 PAID 로 되돌려 배송·재신청이 가능한 상태로 복구한다.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest, OrderItem, Payment
from app.schemas.admin.order_cancel_request import (
    AdminOrderCancelRequestActionResponse,
    AdminOrderCancelRequestDetailResponse,
    AdminOrderCancelRequestItem,
    AdminOrderCancelRequestListResponse,
    AdminOrderCancelRequestPagination,
)
from app.schemas.common import ApiError
from app.services.payment_cancel_service import cancel_paid_order


CANCEL_REQUEST_STATUSES = {"REQUESTED", "APPROVED", "REJECTED"}
CANCEL_REQUEST_STATUS_REQUESTED = "REQUESTED"
CANCEL_REQUEST_STATUS_APPROVED = "APPROVED"
CANCEL_REQUEST_STATUS_REJECTED = "REJECTED"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_PAID = "PAID"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_STATUS_CANCELED = "CANCELED"
PAYMENT_PROVIDER_MOCK = "MOCK"
PAYMENT_PROVIDER_TOSS = "TOSS"
ADMIN_CANCEL_SUPPORTED_PROVIDERS = {PAYMENT_PROVIDER_MOCK, PAYMENT_PROVIDER_TOSS}

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def list_admin_cancel_requests(
    session: Session,
    *,
    status: str | None,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> AdminOrderCancelRequestListResponse:
    normalized_status = _normalize_status(status)
    normalized_page = page if page >= 1 else DEFAULT_PAGE
    normalized_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    conditions = []
    if normalized_status is not None:
        conditions.append(OrderCancelRequest.status == normalized_status)

    total_items = session.execute(
        select(func.count()).select_from(OrderCancelRequest).where(*conditions)
    ).scalar_one()
    total_pages = max((total_items + normalized_page_size - 1) // normalized_page_size, 1)

    rows = session.execute(
        select(OrderCancelRequest, Order, Payment)
        .join(Order, Order.id == OrderCancelRequest.order_id)
        .outerjoin(Payment, Payment.order_id == Order.id)
        .where(*conditions)
        .order_by(OrderCancelRequest.requested_at.desc(), OrderCancelRequest.id.desc())
        .limit(normalized_page_size)
        .offset((normalized_page - 1) * normalized_page_size)
    ).all()

    users_by_id = _load_users_by_id(session, [int(order.user_id) for _request, order, _payment in rows])
    items = [
        _to_list_item(request, order=order, payment=payment, user=users_by_id.get(int(order.user_id)))
        for request, order, payment in rows
    ]
    return AdminOrderCancelRequestListResponse(
        items=items,
        pagination=AdminOrderCancelRequestPagination(
            page=normalized_page,
            page_size=normalized_page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=normalized_page < total_pages,
            has_prev=normalized_page > 1,
        ),
    )


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
    """취소 요청 승인. 잠금 순서 Order→Payment→OrderCancelRequest(→Inventory, cancel_paid_order 내부).

    이미 APPROVED 인 요청은 Order/Payment 가 실제로 CANCELED 인지 직접 재검증하고 그대로 반환한다
    (cancel_paid_order() 를 다시 호출하지 않는다) — 그렇지 않으면 다른 경로로 어긋난 상태를
    "재실행"으로 조용히 복구해버릴 수 있어 정합성 오류를 숨기게 된다. 이미 REQUESTED 인데 Order/Payment
    가 사전조건과 안 맞으면(예: 다른 경로로 이미 CANCELED) 마찬가지로 409 로 거부한다.
    """
    order_id = _resolve_order_id(session, request_code)
    order = _load_order_for_update(session, order_id)
    payment = _load_payment_for_update(session, order.id)
    request = _load_cancel_request_for_update(session, request_code)

    if request.status == CANCEL_REQUEST_STATUS_REJECTED:
        raise ApiError(409, "CANCEL_REQUEST_ALREADY_REJECTED", "Cancel request was already rejected.")

    if request.status == CANCEL_REQUEST_STATUS_APPROVED:
        if order.status != ORDER_STATUS_CANCELED or payment is None or payment.status != PAYMENT_STATUS_CANCELED:
            raise ApiError(
                409,
                "ORDER_CANCEL_STATE_INCONSISTENT",
                "Cancel request is approved but order/payment state is inconsistent.",
            )
        return _to_action_response(request, order_status=order.status, order_code=order.order_code)

    if order.status != ORDER_STATUS_CANCEL_REQUESTED or payment is None or payment.status != PAYMENT_STATUS_APPROVED:
        raise ApiError(
            409,
            "ORDER_CANCEL_STATE_INCONSISTENT",
            "Order and payment are not in an approvable state.",
        )

    result = cancel_paid_order(
        session,
        order.order_code,
        simulate_toss_cancel=True,
    )

    now = datetime.now(UTC)
    request.status = CANCEL_REQUEST_STATUS_APPROVED
    request.processed_at = now
    request.updated_at = now
    session.flush()

    return _to_action_response(request, order_status=result.order_status, order_code=order.order_code)


def reject_admin_cancel_request(
    session: Session, request_code: str, *, rejection_reason: str
) -> AdminOrderCancelRequestActionResponse:
    """취소 요청 거절. 잠금 순서 Order→Payment→OrderCancelRequest. Order 를 PAID 로 복구한다."""
    normalized_reason = rejection_reason.strip()
    if not normalized_reason:
        raise ApiError(400, "REJECTION_REASON_REQUIRED", "Rejection reason is required.")

    order_id = _resolve_order_id(session, request_code)
    order = _load_order_for_update(session, order_id)
    payment = _load_payment_for_update(session, order.id)
    request = _load_cancel_request_for_update(session, request_code)

    if request.status == CANCEL_REQUEST_STATUS_APPROVED:
        raise ApiError(409, "CANCEL_REQUEST_ALREADY_APPROVED", "Cancel request was already approved.")

    if request.status == CANCEL_REQUEST_STATUS_REJECTED:
        if order.status != ORDER_STATUS_PAID or payment is None or payment.status != PAYMENT_STATUS_APPROVED:
            raise ApiError(
                409,
                "ORDER_CANCEL_STATE_INCONSISTENT",
                "Cancel request is rejected but order/payment state is inconsistent.",
            )
        return _to_action_response(request, order_status=order.status, order_code=order.order_code)

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


def _resolve_order_id(session: Session, request_code: str) -> int:
    normalized_code = request_code.strip()
    if not normalized_code:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    order_id = session.execute(
        select(OrderCancelRequest.order_id).where(OrderCancelRequest.request_code == normalized_code)
    ).scalar_one_or_none()
    if order_id is None:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    return order_id


def _load_cancel_request_for_update(session: Session, request_code: str) -> OrderCancelRequest:
    normalized_code = request_code.strip()
    request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.request_code == normalized_code).with_for_update()
    ).scalar_one_or_none()
    if request is None:
        raise ApiError(404, "CANCEL_REQUEST_NOT_FOUND", "Cancel request was not found.")
    return request


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
    if payment.provider not in ADMIN_CANCEL_SUPPORTED_PROVIDERS:
        return ["REJECT"]
    return ["APPROVE", "REJECT"]


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
