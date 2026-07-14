from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import (
    Inventory,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
)
from app.schemas.common import ApiError


ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
ORDER_STATUS_CANCELED = "CANCELED"
PAYMENT_PROVIDER_MOCK = "MOCK"
PAYMENT_PROVIDER_TOSS = "TOSS"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_STATUS_CANCELED = "CANCELED"
ORDER_ITEM_STATUS_ORDERED = "ORDERED"
ORDER_ITEM_STATUS_CANCELED = "CANCELED"


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
    simulate_toss_cancel: bool = False,
) -> PaidOrderCancelResult:
    """Cancel a single CANCEL_REQUESTED + APPROVED order for admin approval reuse.

    Locks Order, then Payment, then Inventory. Only flushes — the caller owns commit/rollback.

    TOSS 결제는 기본적으로 외부 PG 취소 없이는 처리하지 않는다. 관리자 시뮬레이션
    범위에서만 ``simulate_toss_cancel=True``를 명시해 내부 주문·결제·재고 상태를
    취소하고, 외부 PG를 호출하지 않았다는 PaymentEvent를 남긴다.
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

    is_toss_simulation = payment.provider == PAYMENT_PROVIDER_TOSS and simulate_toss_cancel
    if payment.provider != PAYMENT_PROVIDER_MOCK and not is_toss_simulation:
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
    if is_toss_simulation:
        _record_toss_simulated_cancel_event(session, order, payment, resolved_now)
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


def _record_toss_simulated_cancel_event(
    session: Session,
    order: Order,
    payment: Payment,
    now: datetime,
) -> None:
    session.add(
        PaymentEvent(
            payment_id=payment.id,
            order_id=order.id,
            event_type="ADMIN_TOSS_CANCEL_SIMULATED",
            event_id=f"admin-toss-cancel:{order.order_code}",
            provider=payment.provider,
            provider_payment_key=payment.provider_payment_key,
            provider_order_id=payment.provider_order_id,
            amount=payment.amount,
            currency=payment.currency,
            status_before=PAYMENT_STATUS_APPROVED,
            status_after=PAYMENT_STATUS_CANCELED,
            raw_payload_json={
                "mode": "INTERNAL_SIMULATION",
                "external_provider_called": False,
            },
            created_at=now,
        )
    )
