from datetime import UTC, datetime
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderClaim, OrderClaimItem, OrderItem, Payment, PaymentRefund
from app.schemas.common import ApiError


def process_mock_refund(
    session: Session,
    claim_code: str,
    *,
    restock: bool,
    now: datetime | None = None,
) -> PaymentRefund:
    processed_at = now or datetime.now(UTC)
    claim = session.execute(
        select(OrderClaim).where(OrderClaim.claim_code == claim_code.strip()).with_for_update()
    ).scalar_one_or_none()
    if claim is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    existing = session.execute(
        select(PaymentRefund).where(PaymentRefund.claim_id == claim.id).with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if claim.status not in {"APPROVED", "IN_PROGRESS"}:
        raise ApiError(409, "CLAIM_NOT_APPROVED", "Claim must be approved before refund processing.")
    if claim.claim_type == "EXCHANGE":
        raise ApiError(409, "EXCHANGE_REFUND_UNSUPPORTED", "Exchange claims do not use the refund flow.")

    payment, order = session.execute(
        select(Payment, Order)
        .join(Order, Order.id == Payment.order_id)
        .where(Order.id == claim.order_id)
        .with_for_update()
    ).one()
    if payment.provider != "MOCK":
        raise ApiError(409, "MOCK_REFUND_PROVIDER_MISMATCH", "Only MOCK payments can use this refund flow.")
    if payment.status not in {"APPROVED", "PARTIALLY_REFUNDED"}:
        raise ApiError(409, "PAYMENT_NOT_REFUNDABLE", "Payment is not refundable in its current status.")
    amount = claim.refund_amount or 0
    if amount <= 0 or amount > payment.amount:
        raise ApiError(409, "INVALID_REFUND_AMOUNT", "Refund amount is invalid.")

    refund = PaymentRefund(
        refund_code=_generate_refund_code(processed_at),
        claim_id=claim.id,
        payment_id=payment.id,
        order_id=order.id,
        provider=payment.provider,
        status="REFUNDED",
        amount=amount,
        currency=payment.currency,
        reason=claim.reason_code,
        restocked=restock,
        provider_refund_key=f"mock_refund:{claim.claim_code}",
        requested_at=processed_at,
        completed_at=processed_at,
        created_at=processed_at,
        updated_at=processed_at,
    )
    session.add(refund)
    payment.status = "REFUNDED" if amount == payment.amount else "PARTIALLY_REFUNDED"
    payment.updated_at = processed_at
    claim.status = "COMPLETED"
    claim.completed_at = processed_at
    claim.updated_at = processed_at

    claim_items = session.execute(
        select(OrderClaimItem, OrderItem)
        .join(OrderItem, OrderItem.id == OrderClaimItem.order_item_id)
        .where(OrderClaimItem.claim_id == claim.id)
    ).all()
    inventories = _load_inventories(session, [item.product_id for _, item in claim_items]) if restock else {}
    for claim_item, order_item in claim_items:
        order_item.status = "RETURNED" if claim.claim_type == "RETURN" else "REFUNDED"
        order_item.updated_at = processed_at
        if restock:
            inventory = inventories[int(order_item.product_id)]
            inventory.stock_quantity += claim_item.quantity
            inventory.updated_at = processed_at
            session.add(
                InventoryMovement(
                    inventory_id=inventory.id,
                    product_id=order_item.product_id,
                    movement_type="RETURN_RESTOCK",
                    quantity_delta=claim_item.quantity,
                    stock_after=inventory.stock_quantity,
                    reason="approved claim mock refund restock",
                    reference_type="claim",
                    reference_id=claim.claim_code,
                    created_at=processed_at,
                )
            )
    session.flush()
    return refund


def _load_inventories(session: Session, product_ids: list[int]) -> dict[int, Inventory]:
    rows = session.execute(
        select(Inventory).where(Inventory.product_id.in_(product_ids)).with_for_update()
    ).scalars().all()
    inventories = {int(row.product_id): row for row in rows}
    if len(inventories) != len(set(product_ids)):
        raise ApiError(409, "STOCK_UNKNOWN", "Product stock is unavailable.")
    return inventories


def _generate_refund_code(now: datetime) -> str:
    return f"rfd_{now.strftime('%Y%m%d')}_{secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8]}"
