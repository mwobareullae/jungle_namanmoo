from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import Order, OrderFulfillmentEvent, OrderItem
from app.schemas.common import ApiError


FULFILLMENT_STATUSES = {
    "PAID",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
}

FULFILLMENT_TRANSITIONS = {
    "PAID": "PREPARING_SHIPMENT",
    "PREPARING_SHIPMENT": "SHIPPED",
    "SHIPPED": "DELIVERED",
}


def transition_fulfillment_status(
    session: Session,
    order_code: str,
    to_status: str,
    *,
    source: str = "ADMIN",
    reason: str | None = None,
    now: datetime | None = None,
) -> Order:
    normalized_order_code = order_code.strip()
    normalized_to_status = to_status.strip().upper()
    if not normalized_order_code:
        raise ApiError(400, "ORDER_CODE_REQUIRED", "order_code is required.")
    if normalized_to_status not in FULFILLMENT_STATUSES:
        raise ApiError(400, "INVALID_FULFILLMENT_STATUS", "Invalid fulfillment status.")

    order = session.execute(
        select(Order)
        .where(Order.order_code == normalized_order_code)
        .with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    if order.status == normalized_to_status:
        return order
    if FULFILLMENT_TRANSITIONS.get(order.status) != normalized_to_status:
        raise ApiError(
            409,
            "INVALID_FULFILLMENT_TRANSITION",
            f"Cannot change fulfillment status from {order.status} to {normalized_to_status}.",
        )

    transition_time = now or datetime.now(UTC)
    previous_status = order.status
    order.status = normalized_to_status
    order.updated_at = transition_time
    if normalized_to_status == "SHIPPED":
        order.shipped_at = transition_time
    elif normalized_to_status == "DELIVERED":
        order.delivered_at = transition_time

    session.execute(
        OrderItem.__table__.update()
        .where(OrderItem.order_id == order.id)
        .values(status=normalized_to_status, updated_at=transition_time)
    )
    session.add(
        OrderFulfillmentEvent(
            order_id=order.id,
            from_status=previous_status,
            to_status=normalized_to_status,
            source=source.strip() or "ADMIN",
            reason=reason.strip() if reason and reason.strip() else None,
            created_at=transition_time,
        )
    )
    session.flush()
    return order
