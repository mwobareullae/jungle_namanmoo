from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentEvent
from app.schemas.common import ApiError
from app.schemas.payment import PaymentActionResponse


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_PAYMENT_FAILED = "PAYMENT_FAILED"
PAYMENT_STATUS_READY = "READY"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_STATUS_FAILED = "FAILED"


def confirm_mock_payment(
    session: Session,
    user: User,
    payment_code: str,
) -> PaymentActionResponse:
    payment, order = _load_user_payment(session, user.id, payment_code)
    if payment.status == PAYMENT_STATUS_APPROVED and order.status == ORDER_STATUS_PAID:
        return _to_response(order, payment)

    _require_status(
        order.status == ORDER_STATUS_PENDING_PAYMENT,
        "ORDER_NOT_PENDING_PAYMENT",
        "Order is not pending payment.",
    )
    _require_status(
        payment.status == PAYMENT_STATUS_READY,
        "PAYMENT_NOT_READY",
        "Payment is not ready.",
    )

    now = datetime.now(UTC)
    if order.payment_expires_at is not None and _as_utc(order.payment_expires_at) <= now:
        raise ApiError(409, "PAYMENT_EXPIRED", "Payment window has expired.")

    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    _confirm_reserved_inventory(session, order, order_items, inventories, now)

    old_payment_status = payment.status
    payment.status = PAYMENT_STATUS_APPROVED
    payment.approved_at = now
    payment.updated_at = now
    order.status = ORDER_STATUS_PAID
    order.paid_at = now
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        event_type="MOCK_PAYMENT_APPROVED",
        event_id=f"mock_confirm:{payment.payment_code}",
        status_before=old_payment_status,
        status_after=payment.status,
        payload={"source": "mock_confirm"},
        now=now,
    )
    session.flush()
    return _to_response(order, payment)


def fail_mock_payment(
    session: Session,
    user: User,
    payment_code: str,
) -> PaymentActionResponse:
    payment, order = _load_user_payment(session, user.id, payment_code)
    if payment.status == PAYMENT_STATUS_FAILED and order.status == ORDER_STATUS_PAYMENT_FAILED:
        return _to_response(order, payment)

    _require_status(
        order.status == ORDER_STATUS_PENDING_PAYMENT,
        "ORDER_NOT_PENDING_PAYMENT",
        "Order is not pending payment.",
    )
    _require_status(
        payment.status == PAYMENT_STATUS_READY,
        "PAYMENT_NOT_READY",
        "Payment is not ready.",
    )

    now = datetime.now(UTC)
    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    _release_reserved_inventory(session, order, order_items, inventories, now, "payment failed reservation release")

    old_payment_status = payment.status
    payment.status = PAYMENT_STATUS_FAILED
    payment.failed_at = now
    payment.updated_at = now
    order.status = ORDER_STATUS_PAYMENT_FAILED
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        event_type="MOCK_PAYMENT_FAILED",
        event_id=f"mock_fail:{payment.payment_code}",
        status_before=old_payment_status,
        status_after=payment.status,
        payload={"source": "mock_fail"},
        now=now,
    )
    session.flush()
    return _to_response(order, payment)


def _load_user_payment(session: Session, user_id: int, payment_code: str) -> tuple[Payment, Order]:
    normalized_code = payment_code.strip()
    if not normalized_code:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Payment was not found.")
    row = session.execute(
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(
            Payment.payment_code == normalized_code,
            Order.user_id == user_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Payment was not found.")
    return row


def _require_status(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ApiError(409, code, message)


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


def _confirm_reserved_inventory(
    session: Session,
    order: Order,
    order_items: list[OrderItem],
    inventories: dict[int, Inventory],
    now: datetime,
) -> None:
    for item in order_items:
        inventory = inventories[int(item.product_id)]
        _require_inventory_can_release(inventory, item.quantity)
        if inventory.stock_quantity < item.quantity:
            raise ApiError(409, "INVENTORY_STATE_INVALID", "Inventory stock is lower than order quantity.")
        inventory.stock_quantity -= item.quantity
        inventory.reserved_quantity -= item.quantity
        inventory.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=item.product_id,
                movement_type="SALE_CONFIRM",
                quantity_delta=-item.quantity,
                stock_after=inventory.stock_quantity,
                reason="payment approved stock deduction",
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )


def _release_reserved_inventory(
    session: Session,
    order: Order,
    order_items: list[OrderItem],
    inventories: dict[int, Inventory],
    now: datetime,
    reason: str,
) -> None:
    for item in order_items:
        inventory = inventories[int(item.product_id)]
        _require_inventory_can_release(inventory, item.quantity)
        inventory.reserved_quantity -= item.quantity
        inventory.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=item.product_id,
                movement_type="RELEASE_RESERVATION",
                quantity_delta=-item.quantity,
                stock_after=inventory.stock_quantity,
                reason=reason,
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )


def _require_inventory_can_release(inventory: Inventory, quantity: int) -> None:
    if inventory.reserved_quantity < quantity:
        raise ApiError(409, "INVENTORY_RESERVATION_INVALID", "Reserved inventory is lower than order quantity.")


def _record_payment_event(
    session: Session,
    *,
    payment: Payment,
    order: Order,
    event_type: str,
    event_id: str,
    status_before: str,
    status_after: str,
    payload: dict,
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
            raw_payload_json=payload,
            created_at=now,
        )
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_response(order: Order, payment: Payment) -> PaymentActionResponse:
    return PaymentActionResponse(
        order_code=order.order_code,
        payment_code=payment.payment_code,
        order_status=order.status,
        payment_status=payment.status,
        approved_at=payment.approved_at,
        failed_at=payment.failed_at,
    )
