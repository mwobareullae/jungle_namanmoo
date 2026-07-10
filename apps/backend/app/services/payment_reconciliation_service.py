from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import Order, Payment, PaymentAttempt
from app.services.payment_service import (
    PAYMENT_PROVIDER_TOSS,
    PAYMENT_STATUS_APPROVED,
    PAYMENT_STATUS_CONFIRMING,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_UNKNOWN,
    _approve_payment,
)
from app.services.pending_payment_terminal_service import (
    PendingPaymentTerminationSpec,
    terminate_pending_payment,
)
from app.services.toss_payments_client import TossPaymentsClientError


class TossPaymentQueryClient(Protocol):
    def get_payment(self, *, payment_key: str) -> dict[str, Any]:
        pass


@dataclass(frozen=True)
class ReconcilePendingPaymentsResult:
    scanned_count: int
    approved_count: int
    failed_count: int
    unknown_count: int
    order_codes: list[str]


def reconcile_pending_payments(
    session: Session,
    *,
    toss_client: TossPaymentQueryClient,
    limit: int = 100,
) -> ReconcilePendingPaymentsResult:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    normalized_limit = min(limit, 500)
    rows = session.execute(
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(
            Payment.provider == PAYMENT_PROVIDER_TOSS,
            Payment.status.in_((PAYMENT_STATUS_CONFIRMING, PAYMENT_STATUS_UNKNOWN)),
            Payment.provider_payment_key.is_not(None),
        )
        .order_by(Payment.updated_at.asc(), Payment.id.asc())
        .limit(normalized_limit)
        .with_for_update(skip_locked=True)
    ).all()

    approved_count = 0
    failed_count = 0
    unknown_count = 0
    order_codes: list[str] = []
    for payment, order in rows:
        result = _reconcile_one(session, payment, order, toss_client)
        if result == PAYMENT_STATUS_APPROVED:
            approved_count += 1
            order_codes.append(order.order_code)
        elif result == PAYMENT_STATUS_FAILED:
            failed_count += 1
            order_codes.append(order.order_code)
        else:
            unknown_count += 1
        session.flush()

    return ReconcilePendingPaymentsResult(
        scanned_count=len(rows),
        approved_count=approved_count,
        failed_count=failed_count,
        unknown_count=unknown_count,
        order_codes=order_codes,
    )


def _reconcile_one(
    session: Session,
    payment: Payment,
    order: Order,
    toss_client: TossPaymentQueryClient,
) -> str:
    payment_key = payment.provider_payment_key
    if not payment_key:
        return PAYMENT_STATUS_UNKNOWN
    try:
        payload = toss_client.get_payment(payment_key=payment_key)
    except TossPaymentsClientError as exc:
        _record_attempt_result(
            session,
            payment,
            status=PAYMENT_STATUS_UNKNOWN,
            error_code=exc.code,
            error_message=exc.message,
        )
        return PAYMENT_STATUS_UNKNOWN

    provider_order_id = payload.get("orderId")
    provider_amount = payload.get("totalAmount")
    provider_status = payload.get("status")
    if provider_order_id != order.order_code or provider_amount != payment.amount:
        _record_attempt_result(
            session,
            payment,
            status=PAYMENT_STATUS_UNKNOWN,
            error_code="TOSS_PAYMENT_QUERY_MISMATCH",
            response_summary=_summary(payload),
        )
        return PAYMENT_STATUS_UNKNOWN

    if provider_status == "DONE":
        payment.provider_order_id = order.order_code
        _approve_payment(
            session,
            payment=payment,
            order=order,
            event_type="TOSS_PAYMENT_RECONCILED",
            event_id=f"toss_reconcile:{payment_key}",
            payload=_summary(payload),
            now=datetime.now(UTC),
            started_at=0,
        )
        _record_attempt_result(session, payment, status=PAYMENT_STATUS_APPROVED, response_summary=_summary(payload))
        return PAYMENT_STATUS_APPROVED

    if provider_status in {"ABORTED", "EXPIRED"}:
        now = datetime.now(UTC)
        terminate_pending_payment(
            session,
            payment=payment,
            order=order,
            spec=PendingPaymentTerminationSpec(
                order_status="PAYMENT_FAILED",
                payment_status=PAYMENT_STATUS_FAILED,
                payment_timestamp_field="failed_at",
                order_timestamp_field=None,
                event_type="TOSS_PAYMENT_TERMINAL",
                event_id=f"toss_terminal:{payment_key}:{provider_status}",
                event_source="payment_reconciliation",
                event_reason=provider_status.lower(),
                inventory_reason="Toss payment terminal state reservation release",
                allow_in_flight_payment=True,
            ),
            now=now,
        )
        _record_attempt_result(session, payment, status=PAYMENT_STATUS_FAILED, response_summary=_summary(payload))
        return PAYMENT_STATUS_FAILED

    _record_attempt_result(session, payment, status=PAYMENT_STATUS_UNKNOWN, response_summary=_summary(payload))
    return PAYMENT_STATUS_UNKNOWN


def _record_attempt_result(
    session: Session,
    payment: Payment,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    response_summary: dict[str, Any] | None = None,
) -> None:
    attempt = session.execute(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.payment_id == payment.id,
            PaymentAttempt.operation == "CONFIRM",
        )
        .order_by(PaymentAttempt.requested_at.desc(), PaymentAttempt.id.desc())
        .with_for_update()
    ).scalars().first()
    if attempt is not None:
        attempt.status = status
        attempt.provider_error_code = error_code
        attempt.provider_error_message = error_message
        attempt.response_summary_json = response_summary
        attempt.completed_at = datetime.now(UTC)
        attempt.updated_at = datetime.now(UTC)
    payment.status = status
    payment.updated_at = datetime.now(UTC)


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "payment_key": payload.get("paymentKey"),
        "order_id": payload.get("orderId"),
        "status": payload.get("status"),
        "total_amount": payload.get("totalAmount"),
        "method": payload.get("method"),
        "approved_at": payload.get("approvedAt"),
    }
