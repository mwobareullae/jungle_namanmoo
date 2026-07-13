from datetime import UTC, datetime
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest, Payment
from app.schemas.common import ApiError
from app.schemas.order import OrderCancelResponse
from app.services.pending_payment_terminal_service import (
    PendingPaymentTerminationResult,
    PendingPaymentTerminationSpec,
    terminate_pending_payment,
)


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_PAYMENT_FAILED = "PAYMENT_FAILED"
ORDER_STATUS_EXPIRED = "EXPIRED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
PAYMENT_STATUS_CANCELED = "CANCELED"
CANCEL_REQUEST_STATUS_REQUESTED = "REQUESTED"


def cancel_order(
    session: Session,
    user: User,
    order_code: str,
) -> OrderCancelResponse:
    started_at = current_time()
    try:
        order = _load_user_order_for_update(session, user.id, order_code)
        if order.status in {
            ORDER_STATUS_CANCELED,
            ORDER_STATUS_CANCEL_REQUESTED,
            ORDER_STATUS_PAYMENT_FAILED,
            ORDER_STATUS_EXPIRED,
        }:
            request_code = None
            if order.status == ORDER_STATUS_CANCEL_REQUESTED:
                request_code = _load_requested_cancel_request_code(session, order.id)
                if request_code is None:
                    raise ApiError(
                        409,
                        "ORDER_CANCEL_REQUEST_NOT_FOUND",
                        "Order is cancel-requested but has no matching cancel request record.",
                    )
            _log_order_cancel_completed(
                started_at,
                order=order,
                payment_status=None,
                released_quantity_total=0,
                restored_quantity_total=0,
                restore_overflow_quantity_total=0,
                idempotent_replay=True,
            )
            return _to_response(order, request_code=request_code)

        payment = _load_payment(session, order.id)
        now = datetime.now(UTC)
        if order.status == ORDER_STATUS_PENDING_PAYMENT:
            termination = _cancel_pending_payment_order(session, order, payment, now)
            session.flush()
            _log_order_cancel_completed(
                started_at,
                order=order,
                payment_status=payment.status,
                released_quantity_total=termination.released_quantity_total,
                restored_quantity_total=termination.restored_quantity_total,
                restore_overflow_quantity_total=termination.restore_overflow_quantity_total,
                idempotent_replay=False,
            )
            return _to_response(order)

        if order.status == ORDER_STATUS_PAID:
            order.status = ORDER_STATUS_CANCEL_REQUESTED
            order.updated_at = now
            cancel_request = OrderCancelRequest(
                request_code=_generate_cancel_request_code(now),
                order_id=order.id,
                user_id=user.id,
                status=CANCEL_REQUEST_STATUS_REQUESTED,
                requested_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(cancel_request)
            session.flush()
            _log_order_cancel_completed(
                started_at,
                order=order,
                payment_status=payment.status,
                released_quantity_total=0,
                restored_quantity_total=0,
                restore_overflow_quantity_total=0,
                idempotent_replay=False,
            )
            return _to_response(order, request_code=cancel_request.request_code)

        raise ApiError(409, "ORDER_NOT_CANCELABLE", "Order cannot be canceled in the current status.")
    except ApiError as exc:
        _log_order_cancel_failed(started_at, error_code=exc.code)
        raise


def _load_user_order_for_update(session: Session, user_id: int, order_code: str) -> Order:
    normalized_code = order_code.strip()
    if not normalized_code:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    order = session.execute(
        select(Order)
        .where(
            Order.order_code == normalized_code,
            Order.user_id == user_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _load_payment(session: Session, order_id: int) -> Payment:
    payment = session.execute(
        select(Payment)
        .where(Payment.order_id == order_id)
        .with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise ApiError(409, "PAYMENT_NOT_FOUND", "Payment was not found.")
    return payment


def _cancel_pending_payment_order(
    session: Session,
    order: Order,
    payment: Payment,
    now: datetime,
) -> PendingPaymentTerminationResult:
    return terminate_pending_payment(
        session,
        payment=payment,
        order=order,
        spec=PendingPaymentTerminationSpec(
            order_status=ORDER_STATUS_CANCELED,
            payment_status=PAYMENT_STATUS_CANCELED,
            payment_timestamp_field="canceled_at",
            order_timestamp_field="canceled_at",
            event_type="ORDER_PAYMENT_CANCELED",
            event_id=f"order_cancel:{order.order_code}:{payment.payment_code}",
            event_source="order_cancel",
            event_reason="pre_payment_cancel",
            inventory_reason="order canceled before payment reservation release",
        ),
        now=now,
    )


def _load_requested_cancel_request_code(session: Session, order_id: int) -> str | None:
    return session.execute(
        select(OrderCancelRequest.request_code).where(
            OrderCancelRequest.order_id == order_id,
            OrderCancelRequest.status == CANCEL_REQUEST_STATUS_REQUESTED,
        )
    ).scalar_one_or_none()


def _generate_cancel_request_code(now: datetime) -> str:
    return f"ocr_{now.strftime('%Y%m%d')}_{secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8]}"


def _to_response(order: Order, *, request_code: str | None = None) -> OrderCancelResponse:
    return OrderCancelResponse(order_code=order.order_code, status=order.status, request_code=request_code)


def _log_order_cancel_completed(
    started_at: float,
    *,
    order: Order,
    payment_status: str | None,
    released_quantity_total: int,
    restored_quantity_total: int,
    restore_overflow_quantity_total: int,
    idempotent_replay: bool,
) -> None:
    log_performance_event(
        "order_cancel_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "order_status": order.status,
            "payment_status": payment_status,
            "released_quantity_total": released_quantity_total,
            "restored_quantity_total": restored_quantity_total,
            "restore_overflow_quantity_total": restore_overflow_quantity_total,
            "idempotent_replay": idempotent_replay,
        },
    )


def _log_order_cancel_failed(started_at: float, *, error_code: str) -> None:
    log_performance_event(
        "order_cancel_failed",
        duration_ms=elapsed_ms(started_at),
        metadata={"error_code": error_code},
    )
