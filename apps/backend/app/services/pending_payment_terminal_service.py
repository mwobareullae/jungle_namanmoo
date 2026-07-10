from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import (
    Cart,
    CartItem,
    Inventory,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
)
from app.schemas.common import ApiError


CART_STATUS_ACTIVE = "ACTIVE"
MAX_CART_ITEM_QUANTITY = 99
ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_ITEM_STATUS_CANCELED = "CANCELED"
PAYMENT_STATUS_READY = "READY"

PaymentTerminalTimestampField = Literal["failed_at", "canceled_at", "expired_at"]
OrderTerminalTimestampField = Literal["canceled_at", "expired_at"]


@dataclass(frozen=True)
class PendingPaymentTerminationSpec:
    order_status: str
    payment_status: str
    payment_timestamp_field: PaymentTerminalTimestampField
    order_timestamp_field: OrderTerminalTimestampField | None
    event_type: str
    event_id: str
    event_source: str
    event_reason: str
    inventory_reason: str


@dataclass(frozen=True)
class PendingPaymentTerminationResult:
    released_quantity_total: int
    restored_item_count: int
    restored_quantity_total: int
    restore_overflow_quantity_total: int


def terminate_pending_payment(
    session: Session,
    *,
    order: Order,
    payment: Payment,
    spec: PendingPaymentTerminationSpec,
    now: datetime,
) -> PendingPaymentTerminationResult:
    if order.status != ORDER_STATUS_PENDING_PAYMENT:
        raise ApiError(409, "ORDER_NOT_PENDING_PAYMENT", "Order is not pending payment.")
    if payment.status != PAYMENT_STATUS_READY:
        raise ApiError(409, "PAYMENT_NOT_READY", "Payment is not ready.")

    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    _release_reserved_inventory(
        session,
        order=order,
        order_items=order_items,
        inventories=inventories,
        reason=spec.inventory_reason,
        now=now,
    )
    restored_item_count, restored_quantity_total, overflow_quantity_total = _restore_order_items_to_active_cart(
        session,
        order=order,
        order_items=order_items,
        now=now,
    )

    for item in order_items:
        item.status = ORDER_ITEM_STATUS_CANCELED
        item.updated_at = now

    old_payment_status = payment.status
    payment.status = spec.payment_status
    setattr(payment, spec.payment_timestamp_field, now)
    payment.updated_at = now
    order.status = spec.order_status
    if spec.order_timestamp_field is not None:
        setattr(order, spec.order_timestamp_field, now)
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        spec=spec,
        status_before=old_payment_status,
        restored_item_count=restored_item_count,
        restored_quantity_total=restored_quantity_total,
        overflow_quantity_total=overflow_quantity_total,
        now=now,
    )
    return PendingPaymentTerminationResult(
        released_quantity_total=sum(item.quantity for item in order_items),
        restored_item_count=restored_item_count,
        restored_quantity_total=restored_quantity_total,
        restore_overflow_quantity_total=overflow_quantity_total,
    )


def _load_order_items(session: Session, order_id: int) -> list[OrderItem]:
    items = session.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.id.asc())
        .with_for_update()
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
    *,
    order: Order,
    order_items: list[OrderItem],
    inventories: dict[int, Inventory],
    reason: str,
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
                reason=reason,
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )


def _restore_order_items_to_active_cart(
    session: Session,
    *,
    order: Order,
    order_items: list[OrderItem],
    now: datetime,
) -> tuple[int, int, int]:
    active_cart = _load_or_create_active_cart(session, order.user_id, now)
    product_ids = [int(item.product_id) for item in order_items]
    source_item_ids = [int(item.cart_item_id) for item in order_items if item.cart_item_id is not None]
    source_items = _load_cart_items_for_update(session, source_item_ids)
    active_items = {
        int(item.product_id): item
        for item in session.execute(
            select(CartItem)
            .where(
                CartItem.cart_id == active_cart.id,
                CartItem.product_id.in_(product_ids),
            )
            .with_for_update()
        ).scalars()
    }

    restored_item_count = 0
    restored_quantity_total = 0
    overflow_quantity_total = 0
    for order_item in order_items:
        product_id = int(order_item.product_id)
        source_item = source_items.get(int(order_item.cart_item_id)) if order_item.cart_item_id is not None else None
        active_item = active_items.get(product_id)
        if active_item is not None:
            if source_item is not None and active_item.id == source_item.id:
                continue
            previous_quantity = active_item.quantity
            active_item.quantity = min(MAX_CART_ITEM_QUANTITY, active_item.quantity + order_item.quantity)
            active_item.updated_at = now
            restored_quantity = active_item.quantity - previous_quantity
            restored_item_count += 1
            restored_quantity_total += restored_quantity
            overflow_quantity_total += order_item.quantity - restored_quantity
            continue

        if source_item is not None:
            source_item.cart_id = active_cart.id
            source_item.quantity = order_item.quantity
            source_item.updated_at = now
            active_item = source_item
        else:
            active_item = CartItem(
                cart_id=active_cart.id,
                product_id=order_item.product_id,
                seller_id=order_item.seller_id,
                quantity=order_item.quantity,
                unit_price_snapshot=order_item.unit_price,
                currency=order_item.currency,
                source=order_item.source,
                recommendation_id=order_item.recommendation_id,
                recommendation_rank=order_item.recommendation_rank,
                created_at=now,
                updated_at=now,
            )
            session.add(active_item)
        active_items[product_id] = active_item
        restored_item_count += 1
        restored_quantity_total += order_item.quantity

    active_cart.updated_at = now
    return restored_item_count, restored_quantity_total, overflow_quantity_total


def _load_or_create_active_cart(session: Session, user_id: int, now: datetime) -> Cart:
    cart = session.execute(
        select(Cart)
        .where(
            Cart.user_id == user_id,
            Cart.status == CART_STATUS_ACTIVE,
        )
        .order_by(Cart.updated_at.desc(), Cart.id.desc())
        .with_for_update()
    ).scalars().first()
    if cart is not None:
        return cart
    cart = Cart(
        user_id=user_id,
        status=CART_STATUS_ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(cart)
    session.flush()
    return cart


def _load_cart_items_for_update(session: Session, cart_item_ids: list[int]) -> dict[int, CartItem]:
    if not cart_item_ids:
        return {}
    return {
        int(item.id): item
        for item in session.execute(
            select(CartItem)
            .where(CartItem.id.in_(cart_item_ids))
            .with_for_update()
        ).scalars()
    }


def _record_payment_event(
    session: Session,
    *,
    payment: Payment,
    order: Order,
    spec: PendingPaymentTerminationSpec,
    status_before: str,
    restored_item_count: int,
    restored_quantity_total: int,
    overflow_quantity_total: int,
    now: datetime,
) -> None:
    session.add(
        PaymentEvent(
            payment_id=payment.id,
            order_id=order.id,
            event_type=spec.event_type,
            event_id=spec.event_id,
            provider=payment.provider,
            provider_payment_key=payment.provider_payment_key,
            provider_order_id=payment.provider_order_id,
            amount=payment.amount,
            currency=payment.currency,
            status_before=status_before,
            status_after=payment.status,
            raw_payload_json={
                "source": spec.event_source,
                "reason": spec.event_reason,
                "cart_restore": {
                    "restored_item_count": restored_item_count,
                    "restored_quantity_total": restored_quantity_total,
                    "overflow_quantity_total": overflow_quantity_total,
                },
            },
            created_at=now,
        )
    )
