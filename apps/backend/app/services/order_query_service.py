from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import (
    Order,
    OrderItem,
    OrderShippingAddress,
    OrderShippingGroup,
    Payment,
)
from app.schemas.common import ApiError
from app.schemas.order import (
    OrderDetailItem,
    OrderDetailPayment,
    OrderDetailResponse,
    OrderDetailShippingAddress,
    OrderDetailShippingGroup,
    OrderListItem,
    OrderListResponse,
)


ORDER_STATUSES = {
    "PENDING_PAYMENT",
    "PAID",
    "PAYMENT_FAILED",
    "EXPIRED",
    "CANCELED",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
    "CANCEL_REQUESTED",
    "REFUND_REQUESTED",
    "REFUNDED",
    "RETURN_REQUESTED",
    "RETURNED",
    "EXCHANGE_REQUESTED",
    "EXCHANGED",
}


def list_orders(
    session: Session,
    user: User,
    *,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> OrderListResponse:
    normalized_status = _normalize_status(status)
    normalized_limit = _normalize_limit(limit)
    cursor_order = _load_cursor_order(session, user.id, cursor)

    conditions = [Order.user_id == user.id]
    if normalized_status is not None:
        conditions.append(Order.status == normalized_status)
    if cursor_order is not None:
        conditions.append(
            or_(
                Order.ordered_at < cursor_order.ordered_at,
                and_(Order.ordered_at == cursor_order.ordered_at, Order.id < cursor_order.id),
            )
        )

    rows = session.execute(
        select(Order)
        .where(*conditions)
        .order_by(Order.ordered_at.desc(), Order.id.desc())
        .limit(normalized_limit + 1)
    ).scalars().all()
    visible_orders = list(rows[:normalized_limit])
    first_items = _load_first_items_by_order_id(session, [order.id for order in visible_orders])
    return OrderListResponse(
        items=[
            _to_list_item(order, first_items.get(int(order.id)))
            for order in visible_orders
        ],
        next_cursor=str(visible_orders[-1].id) if len(rows) > normalized_limit and visible_orders else None,
    )


def get_order_detail(
    session: Session,
    user: User,
    order_code: str,
) -> OrderDetailResponse:
    order = _load_user_order(session, user.id, order_code)
    payment = _load_payment(session, order.id)
    item_rows = session.execute(
        select(OrderItem, Product.product_code)
        .join(Product, OrderItem.product_id == Product.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id.asc())
    ).all()
    shipping_address = session.execute(
        select(OrderShippingAddress).where(OrderShippingAddress.order_id == order.id)
    ).scalar_one_or_none()
    shipping_groups = session.execute(
        select(OrderShippingGroup)
        .where(OrderShippingGroup.order_id == order.id)
        .order_by(OrderShippingGroup.id.asc())
    ).scalars().all()

    return OrderDetailResponse(
        order_code=order.order_code,
        status=order.status,
        subtotal=order.subtotal_amount,
        shipping_fee=order.shipping_fee,
        discount_total=order.discount_amount,
        total=order.total_amount,
        currency=order.currency,
        ordered_at=order.ordered_at,
        paid_at=order.paid_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        payment_expires_at=order.payment_expires_at,
        payment=OrderDetailPayment(
            payment_code=payment.payment_code,
            provider=payment.provider,
            status=payment.status,
            approved_at=payment.approved_at,
        ),
        items=[
            _to_detail_item(item, product_code)
            for item, product_code in item_rows
        ],
        shipping_address=_to_shipping_address(shipping_address),
        shipping_groups=[
            OrderDetailShippingGroup(
                seller_name=group.seller_name_snapshot,
                item_subtotal=group.item_subtotal,
                shipping_fee=group.shipping_fee,
                free_shipping_threshold=group.free_shipping_threshold_snapshot,
            )
            for group in shipping_groups
        ],
    )


def _normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().upper()
    if not normalized:
        return None
    if normalized not in ORDER_STATUSES:
        raise ApiError(400, "INVALID_ORDER_STATUS", "Invalid order status.")
    return normalized


def _normalize_limit(limit: int) -> int:
    if limit < 1:
        raise ApiError(400, "INVALID_LIMIT", "limit must be at least 1.")
    return min(limit, 50)


def _load_cursor_order(session: Session, user_id: int, cursor: str | None) -> Order | None:
    if cursor is None or not cursor.strip():
        return None
    try:
        cursor_id = int(cursor)
    except ValueError as exc:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.") from exc
    if cursor_id <= 0:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    order = session.execute(
        select(Order).where(
            Order.id == cursor_id,
            Order.user_id == user_id,
        )
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(400, "INVALID_CURSOR", "Invalid cursor.")
    return order


def _load_user_order(session: Session, user_id: int, order_code: str) -> Order:
    normalized_code = order_code.strip()
    if not normalized_code:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    order = session.execute(
        select(Order).where(
            Order.order_code == normalized_code,
            Order.user_id == user_id,
        )
    ).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _load_payment(session: Session, order_id: int) -> Payment:
    payment = session.execute(select(Payment).where(Payment.order_id == order_id)).scalar_one_or_none()
    if payment is None:
        raise ApiError(409, "PAYMENT_NOT_FOUND", "Payment was not found.")
    return payment


def _load_first_items_by_order_id(
    session: Session,
    order_ids: list[int],
) -> dict[int, OrderItem]:
    if not order_ids:
        return {}
    rows = session.execute(
        select(OrderItem)
        .where(OrderItem.order_id.in_(order_ids))
        .order_by(OrderItem.order_id.asc(), OrderItem.id.asc())
    ).scalars()
    first_items: dict[int, OrderItem] = {}
    for row in rows:
        first_items.setdefault(int(row.order_id), row)
    return first_items


def _to_list_item(order: Order, first_item: OrderItem | None) -> OrderListItem:
    return OrderListItem(
        order_code=order.order_code,
        status=order.status,
        total=order.total_amount,
        currency=order.currency,
        item_count=order.item_count,
        ordered_at=order.ordered_at,
        paid_at=order.paid_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        thumbnail_storage_key=first_item.thumbnail_storage_key_snapshot if first_item else None,
        title=_build_order_title(first_item, order.item_count),
    )


def _build_order_title(first_item: OrderItem | None, item_count: int) -> str:
    if first_item is None:
        return "주문 상품"
    if item_count <= 1:
        return first_item.product_name_snapshot
    return f"{first_item.product_name_snapshot} and {item_count - 1} more"


def _to_detail_item(item: OrderItem, product_code: str) -> OrderDetailItem:
    return OrderDetailItem(
        id=item.id,
        product_id=product_code,
        product_name=item.product_name_snapshot,
        brand_name=item.brand_name_snapshot,
        seller_name=item.seller_name_snapshot,
        thumbnail_storage_key=item.thumbnail_storage_key_snapshot,
        unit_price=item.unit_price,
        quantity=item.quantity,
        line_subtotal=item.line_subtotal,
        line_discount_amount=item.line_discount_amount,
        line_total=item.line_total,
        currency=item.currency,
        status=item.status,
        source=item.source,
        recommendation_id=item.recommendation_id,
        recommendation_rank=item.recommendation_rank,
    )


def _to_shipping_address(address: OrderShippingAddress | None) -> OrderDetailShippingAddress | None:
    if address is None:
        return None
    return OrderDetailShippingAddress(
        recipient_name=address.recipient_name,
        phone=address.phone,
        postal_code=address.postal_code,
        address1=address.address1,
        address2=address.address2,
        delivery_memo=address.delivery_memo,
    )
