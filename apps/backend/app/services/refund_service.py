from datetime import UTC, datetime
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.commerce import (
    Inventory,
    InventoryMovement,
    Order,
    OrderClaim,
    OrderClaimEvent,
    OrderClaimItem,
    OrderItem,
    Payment,
    PaymentEvent,
    PaymentRefund,
)
from app.schemas.common import ApiError


ORDER_ITEM_TERMINAL_STATUS_BY_CLAIM_TYPE = {
    "RETURN": "RETURNED",
    "REFUND": "REFUNDED",
    "EXCHANGE": "EXCHANGED",
}

PAYMENT_PROVIDER_MOCK = "MOCK"
PAYMENT_PROVIDER_TOSS = "TOSS"


def process_claim_refund(
    session: Session,
    claim_code: str,
    *,
    restock: bool,
    simulate_toss_refund: bool = False,
    now: datetime | None = None,
) -> PaymentRefund:
    """REFUND/RETURN 클레임을 완료 처리한다. 잠금 순서는 Order→Payment→Claim→Inventory —

    claim_code 로 order_id 만 잠금 없이 먼저 확인한 뒤 Order·Payment 를 잠그고, Claim 은
    그 다음에 잠근다(계약에 명시된 순서와 일치시켜 다른 경로와의 교착을 피한다).

    TOSS 결제는 기본적으로 외부 PG 환불 호출 없이는 처리하지 않는다. payment_cancel_service.
    cancel_paid_order() 의 simulate_toss_cancel 과 동일하게, simulate_toss_refund=True 를
    명시했을 때만 내부 상태(결제·재고·클레임)를 MOCK 과 같은 방식으로 정리하고, 외부 PG를
    호출하지 않았다는 PaymentEvent 를 남긴다.
    """
    processed_at = now or datetime.now(UTC)
    normalized_code = claim_code.strip()
    if not normalized_code:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    order_id = session.execute(
        select(OrderClaim.order_id).where(OrderClaim.claim_code == normalized_code)
    ).scalar_one_or_none()
    if order_id is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")

    # Order → Payment 순서를 코드로 보장하기 위해 하나의 join FOR UPDATE 로 묶지 않고
    # 별도 SELECT FOR UPDATE 로 나눈다 — join 한 쿼리는 실행 계획에 따라 실제 잠금 순서가
    # 달라질 수 있어 계약이 요구하는 순서를 보장하지 못한다.
    order = session.execute(select(Order).where(Order.id == order_id).with_for_update()).scalar_one()
    payment = session.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    ).scalar_one()
    claim = session.execute(
        select(OrderClaim).where(OrderClaim.claim_code == normalized_code).with_for_update()
    ).scalar_one()

    existing = session.execute(
        select(PaymentRefund).where(PaymentRefund.claim_id == claim.id).with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if claim.status != "IN_PROGRESS":
        raise ApiError(409, "CLAIM_NOT_IN_PROGRESS", "Claim must be in progress before refund processing.")
    if claim.claim_type == "EXCHANGE":
        raise ApiError(409, "EXCHANGE_REFUND_UNSUPPORTED", "Exchange claims do not use the refund flow.")
    if claim.claim_type != "RETURN" and restock:
        raise ApiError(400, "RESTOCK_NOT_APPLICABLE", "Restock only applies to RETURN claims.")

    is_toss_simulation = payment.provider == PAYMENT_PROVIDER_TOSS and simulate_toss_refund
    if payment.provider != PAYMENT_PROVIDER_MOCK and not is_toss_simulation:
        raise ApiError(409, "REFUND_PROVIDER_UNSUPPORTED", "This payment provider cannot use this refund flow.")
    if payment.status not in {"APPROVED", "PARTIALLY_REFUNDED"}:
        raise ApiError(409, "PAYMENT_NOT_REFUNDABLE", "Payment is not refundable in its current status.")
    amount = claim.refund_amount or 0
    if amount <= 0:
        raise ApiError(409, "INVALID_REFUND_AMOUNT", "Refund amount is invalid.")

    # 이미 REFUNDED 처리된 다른 클레임의 환불액까지 누적해서 한도를 넘지 않는지 확인한다.
    # 이번 건만 payment.amount 와 비교하면, 여러 클레임이 나눠 환불될 때 총액을 초과할 수 있다.
    already_refunded_total = session.execute(
        select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
            PaymentRefund.payment_id == payment.id,
            PaymentRefund.status == "REFUNDED",
        )
    ).scalar_one()
    cumulative_total = already_refunded_total + amount
    if cumulative_total > payment.amount:
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
        provider_refund_key=f"admin_refund:{claim.claim_code}",
        requested_at=processed_at,
        completed_at=processed_at,
        created_at=processed_at,
        updated_at=processed_at,
    )
    session.add(refund)
    status_before = payment.status
    payment.status = "REFUNDED" if cumulative_total == payment.amount else "PARTIALLY_REFUNDED"
    payment.updated_at = processed_at

    if is_toss_simulation:
        session.add(
            PaymentEvent(
                payment_id=payment.id,
                order_id=order.id,
                event_type="ADMIN_TOSS_REFUND_SIMULATED",
                event_id=f"admin-toss-refund:{claim.claim_code}",
                provider=payment.provider,
                provider_payment_key=payment.provider_payment_key,
                provider_order_id=payment.provider_order_id,
                amount=amount,
                currency=payment.currency,
                status_before=status_before,
                status_after=payment.status,
                raw_payload_json={
                    "mode": "INTERNAL_SIMULATION",
                    "external_provider_called": False,
                },
                created_at=processed_at,
            )
        )

    from_status = claim.status
    claim.status = "COMPLETED"
    claim.completed_at = processed_at
    claim.updated_at = processed_at
    session.add(
        OrderClaimEvent(
            claim_id=claim.id,
            from_status=from_status,
            to_status="COMPLETED",
            actor_type="ADMIN",
            actor_id=None,
            reason=None,
            created_at=processed_at,
        )
    )

    claim_items = session.execute(
        select(OrderClaimItem, OrderItem)
        .join(OrderItem, OrderItem.id == OrderClaimItem.order_item_id)
        .where(OrderClaimItem.claim_id == claim.id)
    ).all()
    inventories = _load_inventories(session, [item.product_id for _, item in claim_items]) if restock else {}
    for claim_item, order_item in claim_items:
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

    # OrderItem 상태 확정은 이 클레임이 COMPLETED 로 반영된 뒤(위 flush) 다른 완료된 클레임들과
    # 합산해서 판단해야 하므로 별도로 순회한다.
    for _claim_item, order_item in claim_items:
        recompute_order_item_status(session, order_item, processed_at)
    session.flush()
    return refund


def recompute_order_item_status(session: Session, order_item: OrderItem, now: datetime) -> None:
    """이 OrderItem 에 걸린 모든 COMPLETED 클레임의 청구 수량을 합산해 확정 상태를 다시 계산한다.

    합산 수량이 주문 수량과 같고 결과 유형(claim_type)이 전부 동일할 때만 RETURNED/REFUNDED/
    EXCHANGED 로 바꾼다. 아직 일부 수량만 완료됐거나 RETURN/REFUND/EXCHANGE 가 섞여 있으면
    DELIVERED 를 유지한다 — 부분·혼합 결과의 원장은 OrderClaimItem/OrderClaimEvent 로 조회한다.
    """
    rows = session.execute(
        select(OrderClaimItem.quantity, OrderClaim.claim_type)
        .join(OrderClaim, OrderClaim.id == OrderClaimItem.claim_id)
        .where(OrderClaimItem.order_item_id == order_item.id, OrderClaim.status == "COMPLETED")
    ).all()
    total_completed_quantity = sum(quantity for quantity, _claim_type in rows)
    distinct_claim_types = {claim_type for _quantity, claim_type in rows}
    if total_completed_quantity != order_item.quantity or len(distinct_claim_types) != 1:
        return
    (claim_type,) = distinct_claim_types
    order_item.status = ORDER_ITEM_TERMINAL_STATUS_BY_CLAIM_TYPE[claim_type]
    order_item.updated_at = now


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
