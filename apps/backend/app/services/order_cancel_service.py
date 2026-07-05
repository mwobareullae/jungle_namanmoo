from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentEvent
from app.schemas.common import ApiError
from app.schemas.order import OrderCancelResponse


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_PAYMENT_FAILED = "PAYMENT_FAILED"
ORDER_STATUS_EXPIRED = "EXPIRED"
ORDER_STATUS_CANCELED = "CANCELED"
ORDER_STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"
PAYMENT_STATUS_READY = "READY"
PAYMENT_STATUS_CANCELED = "CANCELED"


def cancel_order(
    session: Session,
    user: User,
    order_code: str,
) -> OrderCancelResponse:
    order = _load_user_order_for_update(session, user.id, order_code)
    if order.status in {
        ORDER_STATUS_CANCELED,
        ORDER_STATUS_CANCEL_REQUESTED,
        ORDER_STATUS_PAYMENT_FAILED,
        ORDER_STATUS_EXPIRED,
    }:
        return _to_response(order)

    payment = _load_payment(session, order.id)
    now = datetime.now(UTC)
    if order.status == ORDER_STATUS_PENDING_PAYMENT:
        _cancel_pending_payment_order(session, order, payment, now)
        session.flush()
        return _to_response(order)

    if order.status == ORDER_STATUS_PAID:
        order.status = ORDER_STATUS_CANCEL_REQUESTED
        order.updated_at = now
        session.flush()
        return _to_response(order)

    raise ApiError(409, "ORDER_NOT_CANCELABLE", "Order cannot be canceled in the current status.")


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
) -> None:
    if payment.status != PAYMENT_STATUS_READY:
        raise ApiError(409, "PAYMENT_NOT_READY", "Payment is not ready.")

    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    _release_reserved_inventory(session, order, order_items, inventories, now)

    for item in order_items:
        item.status = ORDER_STATUS_CANCELED
        item.updated_at = now

    old_payment_status = payment.status
    payment.status = PAYMENT_STATUS_CANCELED
    payment.canceled_at = now
    payment.updated_at = now
    order.status = ORDER_STATUS_CANCELED
    order.canceled_at = now
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        event_type="ORDER_PAYMENT_CANCELED",
        event_id=f"order_cancel:{order.order_code}:{payment.payment_code}",
        status_before=old_payment_status,
        status_after=payment.status,
        now=now,
    )


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
                reason="order canceled before payment reservation release",
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
            raw_payload_json={"source": "order_cancel", "reason": "pre_payment_cancel"},
            created_at=now,
        )
    )


def _to_response(order: Order) -> OrderCancelResponse:
    return OrderCancelResponse(order_code=order.order_code, status=order.status)
