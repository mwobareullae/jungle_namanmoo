from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.commerce import Order, Payment
from app.schemas.common import ApiError
from app.services.pending_payment_terminal_service import (
    PendingPaymentTerminationResult,
    PendingPaymentTerminationSpec,
    terminate_pending_payment,
)


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_EXPIRED = "EXPIRED"
PAYMENT_STATUS_READY = "READY"
PAYMENT_STATUS_EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ExpirePendingOrdersResult:
    expired_count: int
    order_codes: list[str]


def expire_pending_orders(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> ExpirePendingOrdersResult:
    started_at = current_time()
    try:
        normalized_now = _normalize_now(now)
        normalized_limit = _normalize_limit(limit)
        rows = session.execute(
            select(Order, Payment)
            .join(Payment, Payment.order_id == Order.id)
            .where(
                Order.status == ORDER_STATUS_PENDING_PAYMENT,
                Order.payment_expires_at.is_not(None),
                Order.payment_expires_at <= normalized_now,
                Payment.status == PAYMENT_STATUS_READY,
            )
            .order_by(Order.payment_expires_at.asc(), Order.id.asc())
            .limit(normalized_limit)
            .with_for_update(skip_locked=True)
        ).all()

        expired_codes: list[str] = []
        released_quantity_total = 0
        restored_quantity_total = 0
        restore_overflow_quantity_total = 0
        for order, payment in rows:
            termination = _expire_order(session, order, payment, normalized_now)
            released_quantity_total += termination.released_quantity_total
            restored_quantity_total += termination.restored_quantity_total
            restore_overflow_quantity_total += termination.restore_overflow_quantity_total
            expired_codes.append(order.order_code)

        session.flush()
        result = ExpirePendingOrdersResult(expired_count=len(expired_codes), order_codes=expired_codes)
        log_performance_event(
            "payment_expiry_sweep_completed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "limit": normalized_limit,
                "scanned_count": len(rows),
                "expired_count": result.expired_count,
                "released_quantity_total": released_quantity_total,
                "restored_quantity_total": restored_quantity_total,
                "restore_overflow_quantity_total": restore_overflow_quantity_total,
            },
        )
        return result
    except ApiError as exc:
        log_performance_event(
            "payment_expiry_sweep_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "limit": limit,
                "error_code": exc.code,
            },
        )
        raise


def _expire_order(
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
            order_status=ORDER_STATUS_EXPIRED,
            payment_status=PAYMENT_STATUS_EXPIRED,
            payment_timestamp_field="expired_at",
            order_timestamp_field="expired_at",
            event_type="ORDER_PAYMENT_EXPIRED",
            event_id=f"payment_expire:{order.order_code}:{payment.payment_code}",
            event_source="payment_expiry_sweep",
            event_reason="payment_expired",
            inventory_reason="payment expired reservation release",
        ),
        now=now,
    )


def _normalize_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        raise ApiError(400, "INVALID_LIMIT", "limit must be at least 1.")
    return min(limit, 500)
