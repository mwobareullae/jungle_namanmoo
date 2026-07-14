"""관리자 클레임(반품·교환·환불) 조회·승인·거절 서비스 (P1-M1.5-B).

order_claims 는 배송완료 주문에 대해 고객이 order_claim_service.create_claim() 으로
생성한다. 처리시작·완료 액션은 이후 청크에서 추가한다(환불·재고·교환 정합성 보완 포함).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.auth import User
from app.db.models.commerce import Order, OrderClaim, OrderClaimEvent, OrderClaimItem, OrderItem
from app.schemas.admin.order_claim import (
    AdminOrderClaimActionResponse,
    AdminOrderClaimDetailResponse,
    AdminOrderClaimEventDetail,
    AdminOrderClaimItemDetail,
    AdminOrderClaimListItem,
    AdminOrderClaimListResponse,
)
from app.schemas.common import ApiError
from app.services.refund_service import process_mock_refund, recompute_order_item_status


CLAIM_STATUS_REQUESTED = "REQUESTED"
CLAIM_STATUS_APPROVED = "APPROVED"
CLAIM_STATUS_REJECTED = "REJECTED"
CLAIM_STATUS_IN_PROGRESS = "IN_PROGRESS"
CLAIM_STATUS_COMPLETED = "COMPLETED"


CLAIM_STATUSES = {"REQUESTED", "APPROVED", "REJECTED", "IN_PROGRESS", "COMPLETED", "WITHDRAWN"}
CLAIM_TYPES = {"RETURN", "EXCHANGE", "REFUND"}

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def list_admin_claims(
    session: Session,
    *,
    status: str | None,
    claim_type: str | None,
    page: int,
    page_size: int,
) -> AdminOrderClaimListResponse:
    normalized_status = _normalize_status(status)
    normalized_claim_type = _normalize_claim_type(claim_type)
    normalized_page = _normalize_page(page)
    normalized_page_size = _normalize_page_size(page_size)

    conditions = []
    if normalized_status is not None:
        conditions.append(OrderClaim.status == normalized_status)
    if normalized_claim_type is not None:
        conditions.append(OrderClaim.claim_type == normalized_claim_type)

    total_count = session.execute(
        select(func.count())
        .select_from(OrderClaim)
        .join(Order, Order.id == OrderClaim.order_id)
        .where(*conditions)
    ).scalar_one()

    rows = session.execute(
        select(OrderClaim, Order)
        .join(Order, Order.id == OrderClaim.order_id)
        .where(*conditions)
        .order_by(OrderClaim.requested_at.desc(), OrderClaim.id.desc())
        .offset((normalized_page - 1) * normalized_page_size)
        .limit(normalized_page_size)
    ).all()

    claim_ids = [int(claim.id) for claim, _order in rows]
    items_by_claim = _load_claim_items_by_claim(session, claim_ids)
    users_by_id = _load_users_by_id(session, [int(order.user_id) for _claim, order in rows])

    items = [
        _to_list_item(
            claim,
            order=order,
            claim_items=items_by_claim.get(int(claim.id), []),
            user=users_by_id.get(int(order.user_id)),
        )
        for claim, order in rows
    ]
    return AdminOrderClaimListResponse(
        items=items,
        page=normalized_page,
        page_size=normalized_page_size,
        total_count=int(total_count),
    )


def get_admin_claim(session: Session, claim_code: str) -> AdminOrderClaimDetailResponse:
    claim, order = _load_claim_row(session, claim_code)
    user = _load_users_by_id(session, [int(order.user_id)]).get(int(order.user_id))
    claim_items = _load_claim_items(session, claim.id)
    events = _load_claim_events(session, claim.id)

    list_item = _to_list_item(claim, order=order, claim_items=claim_items, user=user)
    return AdminOrderClaimDetailResponse(
        **list_item.model_dump(),
        order_status=order.status,
        items=[
            AdminOrderClaimItemDetail(
                order_item_id=claim_item.order_item_id,
                product_name_snapshot=order_item.product_name_snapshot,
                quantity=claim_item.quantity,
                resolution=claim_item.resolution,
            )
            for claim_item, order_item in claim_items
        ],
        events=[
            AdminOrderClaimEventDetail(
                from_status=event.from_status,
                to_status=event.to_status,
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                reason=event.reason,
                created_at=event.created_at,
            )
            for event in events
        ],
    )


def approve_admin_claim(session: Session, claim_code: str) -> AdminOrderClaimActionResponse:
    """클레임 승인. REQUESTED→APPROVED. 비금전 액션이라 Claim 행만 잠근다(Order/Payment/Inventory 불필요)."""
    claim, order_code = _load_claim_for_update(session, claim_code)

    if claim.status == CLAIM_STATUS_APPROVED:
        return _to_action_response(claim, order_code=order_code)
    if claim.status == CLAIM_STATUS_REJECTED:
        raise ApiError(409, "CLAIM_ALREADY_REJECTED", "Claim was already rejected.")
    if claim.status != CLAIM_STATUS_REQUESTED:
        raise ApiError(409, "CLAIM_NOT_REQUESTED", "Claim is not in a requested state.")

    now = datetime.now(UTC)
    _transition_claim(session, claim, to_status=CLAIM_STATUS_APPROVED, reason=None, now=now)
    return _to_action_response(claim, order_code=order_code)


def reject_admin_claim(
    session: Session, claim_code: str, *, rejection_reason: str
) -> AdminOrderClaimActionResponse:
    """클레임 거절. REQUESTED→REJECTED. 사유는 필수이며 OrderClaimEvent.reason 에 기록한다."""
    normalized_reason = rejection_reason.strip()
    if not normalized_reason:
        raise ApiError(400, "REJECTION_REASON_REQUIRED", "Rejection reason is required.")

    claim, order_code = _load_claim_for_update(session, claim_code)

    if claim.status == CLAIM_STATUS_REJECTED:
        return _to_action_response(claim, order_code=order_code)
    if claim.status == CLAIM_STATUS_APPROVED:
        raise ApiError(409, "CLAIM_ALREADY_APPROVED", "Claim was already approved.")
    if claim.status != CLAIM_STATUS_REQUESTED:
        raise ApiError(409, "CLAIM_NOT_REQUESTED", "Claim is not in a requested state.")

    now = datetime.now(UTC)
    _transition_claim(session, claim, to_status=CLAIM_STATUS_REJECTED, reason=normalized_reason, now=now)
    return _to_action_response(claim, order_code=order_code)


def start_admin_claim(session: Session, claim_code: str) -> AdminOrderClaimActionResponse:
    """클레임 처리 시작. APPROVED→IN_PROGRESS. 비금전 액션이라 Claim 행만 잠근다."""
    claim, order_code = _load_claim_for_update(session, claim_code)

    if claim.status == CLAIM_STATUS_IN_PROGRESS:
        return _to_action_response(claim, order_code=order_code)
    if claim.status != CLAIM_STATUS_APPROVED:
        raise ApiError(409, "CLAIM_NOT_APPROVED", "Claim is not in an approved state.")

    now = datetime.now(UTC)
    _transition_claim(session, claim, to_status=CLAIM_STATUS_IN_PROGRESS, reason=None, now=now)
    return _to_action_response(claim, order_code=order_code)


def complete_admin_claim(
    session: Session, claim_code: str, *, restock: bool
) -> AdminOrderClaimActionResponse:
    """클레임 완료. IN_PROGRESS→COMPLETED.

    REFUND/RETURN 은 refund_service.process_mock_refund() 를 재사용해 누적 환불 한도·재고
    복구·OrderItem 상태 확정까지 처리한다(그 함수 내부가 Order→Payment→Claim→Inventory 순서로
    잠근다 — 여기서 Claim 을 먼저 잠그면 순서가 뒤집히므로 claim_type 만 잠금 없이 미리 확인한다).
    EXCHANGE 는 결제·재고 변화 없이 Claim 만 잠그고 상태만 완료 처리한다.
    """
    claim_type = _peek_claim_type(session, claim_code)

    if claim_type == "EXCHANGE":
        claim, order_code = _load_claim_for_update(session, claim_code)
        if claim.status == CLAIM_STATUS_COMPLETED:
            return _to_action_response(claim, order_code=order_code)
        if claim.status != CLAIM_STATUS_IN_PROGRESS:
            raise ApiError(409, "CLAIM_NOT_IN_PROGRESS", "Claim is not in progress.")
        _complete_exchange_claim(session, claim, now=datetime.now(UTC))
        return _to_action_response(claim, order_code=order_code)

    process_mock_refund(session, claim_code, restock=restock)
    claim, order_code = _load_claim_for_update(session, claim_code)
    return _to_action_response(claim, order_code=order_code)


def _peek_claim_type(session: Session, claim_code: str) -> str:
    normalized_code = claim_code.strip()
    if not normalized_code:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    claim_type = session.execute(
        select(OrderClaim.claim_type).where(OrderClaim.claim_code == normalized_code)
    ).scalar_one_or_none()
    if claim_type is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    return claim_type


def _complete_exchange_claim(session: Session, claim: OrderClaim, *, now: datetime) -> None:
    claim_items = _load_claim_items(session, claim.id)
    _transition_claim(session, claim, to_status=CLAIM_STATUS_COMPLETED, reason=None, now=now)
    for _claim_item, order_item in claim_items:
        recompute_order_item_status(session, order_item, now)
    session.flush()


def _transition_claim(session: Session, claim: OrderClaim, *, to_status: str, reason: str | None, now: datetime) -> None:
    from_status = claim.status
    claim.status = to_status
    if to_status == CLAIM_STATUS_COMPLETED:
        claim.completed_at = now
    elif to_status in {CLAIM_STATUS_APPROVED, CLAIM_STATUS_REJECTED}:
        claim.processed_at = now
    # IN_PROGRESS(처리 시작)는 processed_at 을 건드리지 않는다 — 승인/거절 시각을 그대로 보존한다.
    claim.updated_at = now
    session.add(
        OrderClaimEvent(
            claim_id=claim.id,
            from_status=from_status,
            to_status=to_status,
            actor_type="ADMIN",
            actor_id=None,
            reason=reason,
            created_at=now,
        )
    )
    session.flush()


def _load_claim_for_update(session: Session, claim_code: str) -> tuple[OrderClaim, str]:
    normalized_code = claim_code.strip()
    if not normalized_code:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    claim = session.execute(
        select(OrderClaim).where(OrderClaim.claim_code == normalized_code).with_for_update()
    ).scalar_one_or_none()
    if claim is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    order_code = session.execute(select(Order.order_code).where(Order.id == claim.order_id)).scalar_one()
    return claim, order_code


def _to_action_response(claim: OrderClaim, *, order_code: str) -> AdminOrderClaimActionResponse:
    return AdminOrderClaimActionResponse(
        claim_code=claim.claim_code,
        order_code=order_code,
        status=claim.status,
        processed_at=claim.processed_at,
        completed_at=claim.completed_at,
        available_actions=_compute_available_actions(claim.status),
    )


def _normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().upper()
    if not normalized:
        return None
    if normalized not in CLAIM_STATUSES:
        raise ApiError(400, "INVALID_CLAIM_STATUS", "Invalid claim status.")
    return normalized


def _normalize_claim_type(claim_type: str | None) -> str | None:
    if claim_type is None:
        return None
    normalized = claim_type.strip().upper()
    if not normalized:
        return None
    if normalized not in CLAIM_TYPES:
        raise ApiError(400, "INVALID_CLAIM_TYPE", "Invalid claim type.")
    return normalized


def _normalize_page(page: int) -> int:
    if page < 1:
        raise ApiError(400, "INVALID_PAGE", "page must be at least 1.")
    return page


def _normalize_page_size(page_size: int) -> int:
    if page_size < 1:
        raise ApiError(400, "INVALID_PAGE_SIZE", "page_size must be at least 1.")
    return min(page_size, MAX_PAGE_SIZE)


def _load_claim_row(session: Session, claim_code: str) -> tuple[OrderClaim, Order]:
    normalized_code = claim_code.strip()
    if not normalized_code:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    row = session.execute(
        select(OrderClaim, Order)
        .join(Order, Order.id == OrderClaim.order_id)
        .where(OrderClaim.claim_code == normalized_code)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "CLAIM_NOT_FOUND", "Claim was not found.")
    return row


def _load_claim_items_by_claim(
    session: Session, claim_ids: list[int]
) -> dict[int, list[tuple[OrderClaimItem, OrderItem]]]:
    if not claim_ids:
        return {}
    rows = session.execute(
        select(OrderClaimItem, OrderItem)
        .join(OrderItem, OrderItem.id == OrderClaimItem.order_item_id)
        .where(OrderClaimItem.claim_id.in_(claim_ids))
        .order_by(OrderClaimItem.id.asc())
    ).all()
    grouped: dict[int, list[tuple[OrderClaimItem, OrderItem]]] = {}
    for claim_item, order_item in rows:
        grouped.setdefault(int(claim_item.claim_id), []).append((claim_item, order_item))
    return grouped


def _load_claim_items(session: Session, claim_id: int) -> list[tuple[OrderClaimItem, OrderItem]]:
    return _load_claim_items_by_claim(session, [claim_id]).get(claim_id, [])


def _load_claim_events(session: Session, claim_id: int) -> list[OrderClaimEvent]:
    return list(
        session.execute(
            select(OrderClaimEvent).where(OrderClaimEvent.claim_id == claim_id).order_by(OrderClaimEvent.id.asc())
        ).scalars()
    )


def _load_users_by_id(session: Session, user_ids: list[int]) -> dict[int, User]:
    unique_ids = list({user_id for user_id in user_ids})
    if not unique_ids:
        return {}
    rows = session.execute(select(User).where(User.id.in_(unique_ids))).scalars()
    return {int(user.id): user for user in rows}


def _to_list_item(
    claim: OrderClaim,
    *,
    order: Order,
    claim_items: list[tuple[OrderClaimItem, OrderItem]],
    user: User | None,
) -> AdminOrderClaimListItem:
    return AdminOrderClaimListItem(
        claim_code=claim.claim_code,
        order_code=order.order_code,
        customer_id=int(order.user_id),
        customer_display=_customer_display(order, user),
        product_summary=_product_summary(claim_items),
        claim_type=claim.claim_type,
        status=claim.status,
        reason_code=claim.reason_code,
        reason_detail=claim.reason_detail,
        refund_amount=claim.refund_amount,
        requested_at=claim.requested_at,
        processed_at=claim.processed_at,
        completed_at=claim.completed_at,
        available_actions=_compute_available_actions(claim.status),
    )


def _compute_available_actions(status: str) -> list[str]:
    if status == "REQUESTED":
        return ["APPROVE", "REJECT"]
    if status == "APPROVED":
        return ["START"]
    if status == "IN_PROGRESS":
        return ["COMPLETE"]
    return []


def _customer_display(order: Order, user: User | None) -> str:
    if user is not None and user.display_name:
        return user.display_name
    return f"user_{int(order.user_id)}"


def _product_summary(claim_items: list[tuple[OrderClaimItem, OrderItem]]) -> str:
    if not claim_items:
        return "청구 상품"
    first_name = claim_items[0][1].product_name_snapshot
    if len(claim_items) <= 1:
        return first_name
    return f"{first_name} 외 {len(claim_items) - 1}개"
