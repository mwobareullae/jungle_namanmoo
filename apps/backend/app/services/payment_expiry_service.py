from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_error_event, log_performance_event
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
    failed_count: int = 0
    failed_order_codes: list[str] = field(default_factory=list)


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
        failed_codes: list[str] = []
        released_quantity_total = 0
        restored_quantity_total = 0
        restore_overflow_quantity_total = 0
        for order, payment in rows:
            order_code = order.order_code
            try:
                # 주문 하나를 savepoint 로 격리한다. 세션이 autoflush=False 라 with 블록을
                # 정상 종료할 때 커밋이 자동으로 flush 를 트리거하므로, 같은 유저의 다른 만료
                # 대상 주문이 이번에 만든/이동한 장바구니 상품을 바로 볼 수 있다(같은 상품을
                # 중복으로 활성 장바구니에 옮기려다 (cart_id, product_id) 유니크 제약을
                # 위반하는 문제를 방지). 이 주문 처리 중 예외(유니크 제약 위반 등)가 나면
                # 이 주문만 롤백되고 나머지 주문은 계속 처리된다.
                with session.begin_nested():
                    termination = _expire_order(session, order, payment, normalized_now)
            except Exception as exc:  # noqa: BLE001 - 배치의 나머지 주문을 계속 처리하기 위해 주문 단위로 실패를 격리한다.
                failed_codes.append(order_code)
                log_error_event(
                    "payment_expiry_order_failed",
                    started_at=started_at,
                    metadata={"order_code": order_code, "error_message": str(exc)[:500]},
                    exc=exc,
                )
                continue
            # with 블록이 예외 없이 끝나 이 주문의 savepoint 가 실제로 커밋된 뒤에만 집계한다.
            # 블록 안에서 집계하면, _expire_order 는 성공했지만 with 종료 시 flush 가 실패하는
            # 경우(예: 유니크 제약 위반) 실제로는 롤백된 주문의 수치까지 합산될 수 있다.
            released_quantity_total += termination.released_quantity_total
            restored_quantity_total += termination.restored_quantity_total
            restore_overflow_quantity_total += termination.restore_overflow_quantity_total
            expired_codes.append(order_code)
        result = ExpirePendingOrdersResult(
            expired_count=len(expired_codes),
            order_codes=expired_codes,
            failed_count=len(failed_codes),
            failed_order_codes=failed_codes,
        )
        log_performance_event(
            "payment_expiry_sweep_completed",
            duration_ms=elapsed_ms(started_at),
            metadata={
                "limit": normalized_limit,
                "scanned_count": len(rows),
                "expired_count": result.expired_count,
                "failed_count": result.failed_count,
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
