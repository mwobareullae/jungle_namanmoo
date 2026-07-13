from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentAttempt
from app.schemas.common import ApiError
from app.services.toss_payments_client import TossPaymentsClientError


ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
ORDER_STATUS_CANCELED = "CANCELED"
PAYMENT_PROVIDER_MOCK = "MOCK"
PAYMENT_PROVIDER_TOSS = "TOSS"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_STATUS_CANCELED = "CANCELED"
PAYMENT_STATUS_UNKNOWN = "UNKNOWN"
ORDER_ITEM_STATUS_ORDERED = "ORDERED"
ORDER_ITEM_STATUS_CANCELED = "CANCELED"


class TossPaymentCancelClient(Protocol):
    def cancel_payment(self, *, payment_key: str, cancel_reason: str) -> dict[str, Any]:
        pass


@dataclass(frozen=True)
class CancelRequestedOrdersResult:
    scanned_count: int
    canceled_count: int
    unknown_count: int
    skipped_count: int
    order_codes: list[str]


def cancel_requested_orders(
    session: Session,
    *,
    toss_client: TossPaymentCancelClient,
    limit: int = 100,
    cancel_reason: str = "customer requested cancellation",
) -> CancelRequestedOrdersResult:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    normalized_reason = cancel_reason.strip()
    if not normalized_reason:
        raise ValueError("cancel_reason must not be blank")
    rows = session.execute(
        select(Order, Payment)
        .join(Payment, Payment.order_id == Order.id)
        .where(Order.status == ORDER_STATUS_CANCEL_REQUESTED)
        .order_by(Order.updated_at.asc(), Order.id.asc())
        .limit(min(limit, 500))
        .with_for_update(skip_locked=True)
    ).all()

    canceled_count = 0
    unknown_count = 0
    skipped_count = 0
    order_codes: list[str] = []
    for order, payment in rows:
        outcome = _cancel_one(session, order, payment, toss_client, normalized_reason)
        if outcome == PAYMENT_STATUS_CANCELED:
            canceled_count += 1
            order_codes.append(order.order_code)
        elif outcome == PAYMENT_STATUS_UNKNOWN:
            unknown_count += 1
        else:
            skipped_count += 1
        session.flush()

    return CancelRequestedOrdersResult(
        scanned_count=len(rows),
        canceled_count=canceled_count,
        unknown_count=unknown_count,
        skipped_count=skipped_count,
        order_codes=order_codes,
    )


def _cancel_one(
    session: Session,
    order: Order,
    payment: Payment,
    toss_client: TossPaymentCancelClient,
    cancel_reason: str,
) -> str:
    if payment.status != PAYMENT_STATUS_APPROVED:
        return "SKIPPED"

    now = datetime.now(UTC)
    attempt_code = _attempt_code(payment, cancel_reason)
    existing = session.execute(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment.id,
            PaymentAttempt.attempt_code == attempt_code,
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == PAYMENT_STATUS_CANCELED:
        _apply_paid_cancel(session, order, payment, now)
        return PAYMENT_STATUS_CANCELED
    if existing is None:
        existing = PaymentAttempt(
            payment_id=payment.id,
            attempt_code=attempt_code,
            operation="CANCEL",
            provider=payment.provider,
            status="CONFIRMING",
            provider_payment_key=payment.provider_payment_key,
            provider_idempotency_key=attempt_code,
            request_summary_json={"cancel_reason": cancel_reason, "order_code": order.order_code},
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(existing)
        session.flush()

    if payment.provider == PAYMENT_PROVIDER_MOCK:
        existing.status = PAYMENT_STATUS_CANCELED
        existing.completed_at = now
        _apply_paid_cancel(session, order, payment, now)
        return PAYMENT_STATUS_CANCELED

    if payment.provider != PAYMENT_PROVIDER_TOSS or not payment.provider_payment_key:
        _finish_attempt(existing, PAYMENT_STATUS_UNKNOWN, now, error_code="PAYMENT_PROVIDER_KEY_MISSING")
        return PAYMENT_STATUS_UNKNOWN

    try:
        response = toss_client.cancel_payment(
            payment_key=payment.provider_payment_key,
            cancel_reason=cancel_reason,
        )
    except TossPaymentsClientError as exc:
        _finish_attempt(existing, PAYMENT_STATUS_UNKNOWN, now, error_code=exc.code, error_message=exc.message)
        return PAYMENT_STATUS_UNKNOWN

    if response.get("status") != "CANCELED" or response.get("paymentKey") not in {None, payment.provider_payment_key}:
        _finish_attempt(existing, PAYMENT_STATUS_UNKNOWN, now, error_code="TOSS_CANCEL_INVALID_RESPONSE", response=response)
        return PAYMENT_STATUS_UNKNOWN

    _finish_attempt(existing, PAYMENT_STATUS_CANCELED, now, response=response)
    _apply_paid_cancel(session, order, payment, now)
    return PAYMENT_STATUS_CANCELED


@dataclass(frozen=True)
class PaidOrderCancelResult:
    order_code: str
    order_status: str
    payment_status: str
    idempotent_replay: bool


def cancel_paid_order(
    session: Session,
    order_code: str,
    *,
    now: datetime | None = None,
) -> PaidOrderCancelResult:
    """Cancel a single CANCEL_REQUESTED + APPROVED order for admin approval reuse.

    Locks Order, then Payment, then Inventory (same order as the batch CLI path).
    Only flushes — the caller owns commit/rollback.
    """
    resolved_now = now or datetime.now(UTC)
    order = _load_order_for_cancel(session, order_code)
    payment = _load_payment_for_cancel(session, order.id)
    item_statuses = _load_order_item_statuses(session, order.id)

    if (
        order.status == ORDER_STATUS_CANCELED
        and payment.status == PAYMENT_STATUS_CANCELED
        and item_statuses
        and all(status == ORDER_ITEM_STATUS_CANCELED for status in item_statuses)
    ):
        return PaidOrderCancelResult(
            order_code=order.order_code,
            order_status=order.status,
            payment_status=payment.status,
            idempotent_replay=True,
        )

    if order.status != ORDER_STATUS_CANCEL_REQUESTED or payment.status != PAYMENT_STATUS_APPROVED:
        raise ApiError(
            409,
            "ORDER_CANCEL_STATE_INCONSISTENT",
            "Order and payment are not in a cancelable or consistently canceled state.",
        )

    if payment.provider != PAYMENT_PROVIDER_MOCK:
        raise ApiError(
            409,
            "MOCK_CANCEL_PROVIDER_MISMATCH",
            "Only MOCK payments can use the synchronous admin cancel flow.",
        )

    if len(item_statuses) != order.item_count or any(
        status != ORDER_ITEM_STATUS_ORDERED for status in item_statuses
    ):
        raise ApiError(
            409,
            "ORDER_CANCEL_STATE_INCONSISTENT",
            "Order items are not all in a cancelable state.",
        )

    _apply_paid_cancel(session, order, payment, resolved_now)
    session.flush()
    return PaidOrderCancelResult(
        order_code=order.order_code,
        order_status=order.status,
        payment_status=payment.status,
        idempotent_replay=False,
    )


def _load_order_for_cancel(session: Session, order_code: str) -> Order:
    normalized_code = order_code.strip()
    if not normalized_code:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    order = session.execute(
        select(Order).where(Order.order_code == normalized_code).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _load_payment_for_cancel(session: Session, order_id: int) -> Payment:
    payment = session.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise ApiError(409, "PAYMENT_NOT_FOUND", "Payment was not found.")
    return payment


def _load_order_item_statuses(session: Session, order_id: int) -> list[str]:
    return list(
        session.execute(
            select(OrderItem.status).where(OrderItem.order_id == order_id).with_for_update()
        ).scalars()
    )


def _apply_paid_cancel(session: Session, order: Order, payment: Payment, now: datetime) -> None:
    items = session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id.asc())
    ).scalars().all()
    inventories = {
        int(row.product_id): row
        for row in session.execute(
            select(Inventory).where(Inventory.product_id.in_([item.product_id for item in items])).with_for_update()
        ).scalars()
    }
    for item in items:
        inventory = inventories.get(int(item.product_id))
        if inventory is None:
            raise ApiError(409, "INVENTORY_NOT_FOUND", "Inventory is missing for paid order cancellation.")
        inventory.stock_quantity += item.quantity
        inventory.updated_at = now
        item.status = ORDER_ITEM_STATUS_CANCELED
        item.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=item.product_id,
                movement_type="SALE_CANCEL",
                quantity_delta=item.quantity,
                stock_after=inventory.stock_quantity,
                reason="paid order cancellation stock restore",
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )
    order.status = ORDER_STATUS_CANCELED
    order.canceled_at = now
    order.updated_at = now
    payment.status = PAYMENT_STATUS_CANCELED
    payment.canceled_at = now
    payment.updated_at = now


def _finish_attempt(
    attempt: PaymentAttempt,
    status: str,
    now: datetime,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    response: dict[str, Any] | None = None,
) -> None:
    attempt.status = status
    attempt.provider_error_code = error_code
    attempt.provider_error_message = error_message
    attempt.response_summary_json = _summary(response) if response is not None else None
    attempt.completed_at = now
    attempt.updated_at = now


def _attempt_code(payment: Payment, cancel_reason: str) -> str:
    raw = f"{payment.payment_code}:{payment.provider_payment_key}:{cancel_reason}"
    return f"toss_cancel:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "payment_key": payload.get("paymentKey"),
        "status": payload.get("status"),
        "order_id": payload.get("orderId"),
        "cancel_amount": payload.get("cancelAmount"),
        "balance_amount": payload.get("balanceAmount"),
    }
