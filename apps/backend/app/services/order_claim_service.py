from collections import defaultdict
from datetime import UTC, datetime, timedelta
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderClaim, OrderClaimEvent, OrderClaimItem, OrderItem
from app.schemas.claim import OrderClaimCreateRequest, OrderClaimItemRequest
from app.schemas.common import ApiError


CLAIM_WINDOW_DAYS = 7
ACTIVE_CLAIM_STATUSES = {"REQUESTED", "APPROVED", "IN_PROGRESS"}
CLAIMABLE_ORDER_STATUS = "DELIVERED"


def create_claim(
    session: Session,
    user: User,
    request: OrderClaimCreateRequest,
    *,
    now: datetime | None = None,
) -> OrderClaim:
    requested_at = now or datetime.now(UTC)
    order = _load_user_order(session, user.id, request.order_code, for_update=True)
    _validate_claim_window(order, requested_at)
    requested_items = _normalize_items(request.items)
    order_items = _load_order_items(session, order.id, requested_items)
    _validate_quantities(session, order.id, requested_items, order_items)

    claim = OrderClaim(
        claim_code=_generate_claim_code(requested_at),
        order_id=order.id,
        user_id=user.id,
        claim_type=request.claim_type,
        status="REQUESTED",
        reason_code=request.reason_code.strip(),
        reason_detail=request.reason_detail.strip() if request.reason_detail and request.reason_detail.strip() else None,
        refund_amount=(
            sum(order_items[item_id].unit_price * quantity for item_id, quantity in requested_items.items())
            if request.claim_type in {"RETURN", "REFUND"}
            else None
        ),
        requested_at=requested_at,
        created_at=requested_at,
        updated_at=requested_at,
    )
    session.add(claim)
    session.flush()

    resolution = "EXCHANGE" if request.claim_type == "EXCHANGE" else "REFUND"
    for item_id, quantity in requested_items.items():
        session.add(
            OrderClaimItem(
                claim_id=claim.id,
                order_item_id=item_id,
                quantity=quantity,
                resolution=resolution,
                created_at=requested_at,
            )
        )
    session.add(
        OrderClaimEvent(
            claim_id=claim.id,
            from_status=None,
            to_status="REQUESTED",
            actor_type="USER",
            actor_id=user.id,
            reason=claim.reason_code,
            created_at=requested_at,
        )
    )
    session.flush()
    return claim


def list_claims(session: Session, user: User) -> list[OrderClaim]:
    return session.execute(
        select(OrderClaim)
        .where(OrderClaim.user_id == user.id)
        .order_by(OrderClaim.created_at.desc(), OrderClaim.id.desc())
    ).scalars().all()


def get_claim(session: Session, user: User, claim_code: str) -> OrderClaim:
    claim = session.execute(
        select(OrderClaim).where(
            OrderClaim.claim_code == claim_code.strip(),
            OrderClaim.user_id == user.id,
        )
    ).scalar_one_or_none()
    if claim is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    return claim


def withdraw_claim(
    session: Session,
    user: User,
    claim_code: str,
    *,
    now: datetime | None = None,
) -> OrderClaim:
    withdrawn_at = now or datetime.now(UTC)
    claim = session.execute(
        select(OrderClaim)
        .where(OrderClaim.claim_code == claim_code.strip(), OrderClaim.user_id == user.id)
        .with_for_update()
    ).scalar_one_or_none()
    if claim is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    if claim.status != "REQUESTED":
        raise ApiError(409, "CLAIM_NOT_WITHDRAWABLE", "Only requested claims can be withdrawn.")

    claim.status = "WITHDRAWN"
    claim.updated_at = withdrawn_at
    session.add(
        OrderClaimEvent(
            claim_id=claim.id,
            from_status="REQUESTED",
            to_status="WITHDRAWN",
            actor_type="USER",
            actor_id=user.id,
            reason="USER_WITHDRAWAL",
            created_at=withdrawn_at,
        )
    )
    session.flush()
    return claim


def _load_user_order(session: Session, user_id: int, order_code: str, *, for_update: bool) -> Order:
    statement = select(Order).where(Order.user_id == user_id, Order.order_code == order_code.strip())
    if for_update:
        statement = statement.with_for_update()
    order = session.execute(statement).scalar_one_or_none()
    if order is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return order


def _validate_claim_window(order: Order, now: datetime) -> None:
    if order.status != CLAIMABLE_ORDER_STATUS or order.delivered_at is None:
        raise ApiError(409, "CLAIM_NOT_ELIGIBLE", "Only delivered orders can be claimed.")
    delivered_at = order.delivered_at
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=UTC)
    if now > delivered_at + timedelta(days=CLAIM_WINDOW_DAYS):
        raise ApiError(409, "CLAIM_WINDOW_EXPIRED", "The claim window has expired.")


def _normalize_items(items: list[OrderClaimItemRequest]) -> dict[int, int]:
    normalized: dict[int, int] = {}
    for item in items:
        if item.order_item_id in normalized:
            raise ApiError(400, "DUPLICATE_CLAIM_ITEM", "Each order item can appear only once.")
        normalized[item.order_item_id] = item.quantity
    return normalized


def _load_order_items(session: Session, order_id: int, requested_items: dict[int, int]) -> dict[int, OrderItem]:
    rows = session.execute(
        select(OrderItem).where(OrderItem.order_id == order_id, OrderItem.id.in_(requested_items))
    ).scalars().all()
    result = {int(row.id): row for row in rows}
    if len(result) != len(requested_items):
        raise ApiError(404, "ORDER_ITEM_NOT_FOUND", "An order item was not found.")
    return result


def _validate_quantities(
    session: Session,
    order_id: int,
    requested_items: dict[int, int],
    order_items: dict[int, OrderItem],
) -> None:
    active_claim_rows = session.execute(
        select(OrderClaimItem.order_item_id, func.sum(OrderClaimItem.quantity))
        .join(OrderClaim, OrderClaim.id == OrderClaimItem.claim_id)
        .where(
            OrderClaim.order_id == order_id,
            OrderClaim.status.in_(ACTIVE_CLAIM_STATUSES),
            OrderClaimItem.order_item_id.in_(requested_items),
        )
        .group_by(OrderClaimItem.order_item_id)
    ).all()
    claimed_quantities = {int(item_id): int(quantity or 0) for item_id, quantity in active_claim_rows}
    for item_id, quantity in requested_items.items():
        available = order_items[item_id].quantity - claimed_quantities.get(item_id, 0)
        if quantity > available:
            raise ApiError(409, "CLAIM_QUANTITY_EXCEEDED", "Claim quantity exceeds the remaining quantity.")


def _generate_claim_code(now: datetime) -> str:
    return f"clm_{now.strftime('%Y%m%d')}_{secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8]}"
