from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentEvent
from app.schemas.common import ApiError


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_EXPIRED = "EXPIRED"
ORDER_ITEM_STATUS_CANCELED = "CANCELED"
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
        for order, payment in rows:
            released_quantity_total += _expire_order(session, order, payment, normalized_now)
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
) -> int:
    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    released_quantity_total = _quantity_total(order_items)
    _release_reserved_inventory(session, order, order_items, inventories, now)

    for item in order_items:
        item.status = ORDER_ITEM_STATUS_CANCELED
        item.updated_at = now

    old_payment_status = payment.status
    payment.status = PAYMENT_STATUS_EXPIRED
    payment.expired_at = now
    payment.updated_at = now
    order.status = ORDER_STATUS_EXPIRED
    order.expired_at = now
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        event_type="ORDER_PAYMENT_EXPIRED",
        event_id=f"payment_expire:{order.order_code}:{payment.payment_code}",
        status_before=old_payment_status,
        status_after=payment.status,
        now=now,
    )
    return released_quantity_total


def _load_order_items(session: Session, order_id: int) -> list[OrderItem]:
    items = session.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.id.asc())
    ).scalars().all()
    if not items:
        raise ApiError(409, "ORDER_ITEMS_NOT_FOUND", "Order items were not found.")
    return list(items)


def _load_inventories_for_update(session: Session, product_ids: list[int]) -> dict[int, Inventory]:
    rows = session.execute(
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .with_for_update()
    ).scalars()
    inventories = {int(row.product_id): row for row in rows}
    if len(inventories) != len(set(product_ids)):
        raise ApiError(409, "STOCK_UNKNOWN", "Product stock is unavailable.")
    return inventories


def _release_reserved_inventory(
    session: Session,
    order: Order,
    order_items: list[OrderItem],
    inventories: dict[int, Inventory],
    now: datetime,
) -> None:
    for item in order_items:
        inventory = inventories[int(item.product_id)]
        if inventory.reserved_quantity < item.quantity:
            raise ApiError(409, "INVENTORY_RESERVATION_INVALID", "Reserved inventory is lower than order quantity.")
        inventory.reserved_quantity -= item.quantity
        inventory.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=item.product_id,
                movement_type="RELEASE_RESERVATION",
                quantity_delta=-item.quantity,
                stock_after=inventory.stock_quantity,
                reason="payment expired reservation release",
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )


def _record_payment_event(
    session: Session,
    *,
    payment: Payment,
    order: Order,
    event_type: str,
    event_id: str,
    status_before: str,
    status_after: str,
    now: datetime,
) -> None:
    session.add(
        PaymentEvent(
            payment_id=payment.id,
            order_id=order.id,
            event_type=event_type,
            event_id=event_id,
            provider=payment.provider,
            provider_payment_key=payment.provider_payment_key,
            provider_order_id=payment.provider_order_id,
            amount=payment.amount,
            currency=payment.currency,
            status_before=status_before,
            status_after=status_after,
            raw_payload_json={"source": "payment_expiry_sweep"},
            created_at=now,
        )
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


def _quantity_total(order_items: list[OrderItem]) -> int:
    return sum(item.quantity for item in order_items)
