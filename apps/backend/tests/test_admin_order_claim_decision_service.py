"""관리자 클레임 승인·거절·처리시작 서비스 테스트 (M1.5-B).

REQUESTED→APPROVED / REQUESTED→REJECTED / APPROVED→IN_PROGRESS 전이와
멱등·상태 불일치·이벤트 기록을 검증한다. 완료(COMPLETE)는 이후 청크에서 다룬다.
"""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import (
    Inventory,
    InventoryMovement,
    Order,
    OrderClaim,
    OrderClaimEvent,
    OrderClaimItem,
    OrderItem,
    Payment,
    PaymentRefund,
)
from app.schemas.common import ApiError
from app.services.admin.order_claim_service import (
    approve_admin_claim,
    complete_admin_claim,
    reject_admin_claim,
    start_admin_claim,
)


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


_seq = 0


def _make_claim(
    session: Session,
    *,
    status: str = "REQUESTED",
    claim_type: str = "REFUND",
    with_inventory: bool = True,
    provider: str = "MOCK",
) -> OrderClaim:
    global _seq
    _seq += 1
    now = datetime.now(UTC)
    user = User(email=f"claimdecision{_seq}@example.com", display_name=None, status="ACTIVE", role="USER")
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_claimdecision_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_claimdecision_{_seq}",
        status="DELIVERED",
        subtotal_amount=10000,
        total_amount=10000,
        currency="KRW",
        item_count=1,
        total_quantity=1,
        ordered_at=now,
        delivered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    order_item = OrderItem(
        order_id=order.id,
        product_id=_seq,
        seller_id=1,
        product_name_snapshot="상품A",
        brand_name_snapshot="브랜드",
        seller_name_snapshot="자사",
        unit_price=10000,
        quantity=1,
        line_subtotal=10000,
        line_discount_amount=0,
        line_total=10000,
        currency="KRW",
        status="DELIVERED",
        created_at=now,
        updated_at=now,
    )
    session.add(order_item)
    if with_inventory:
        session.add(
            Inventory(
                product_id=_seq,
                stock_quantity=10,
                reserved_quantity=0,
                safety_stock=0,
                sales_status="ON_SALE",
                inventory_source="TEST",
                updated_at=now,
            )
        )
    session.add(
        Payment(
            payment_code=f"pay_claimdecision_{_seq}",
            order_id=order.id,
            provider=provider,
            status="APPROVED",
            amount=10000,
            currency="KRW",
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    resolution = "EXCHANGE" if claim_type == "EXCHANGE" else "REFUND"
    claim = OrderClaim(
        claim_code=f"clm_decision_{_seq}",
        order_id=order.id,
        user_id=user.id,
        claim_type=claim_type,
        status=status,
        reason_code="DAMAGED",
        refund_amount=10000 if claim_type != "EXCHANGE" else None,
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(claim)
    session.flush()
    session.add(
        OrderClaimItem(claim_id=claim.id, order_item_id=order_item.id, quantity=1, resolution=resolution, created_at=now)
    )
    session.add(
        OrderClaimEvent(
            claim_id=claim.id,
            from_status=None,
            to_status="REQUESTED",
            actor_type="USER",
            actor_id=user.id,
            reason="DAMAGED",
            created_at=now,
        )
    )
    session.flush()
    return claim


def _events(session: Session, claim_id: int) -> list[OrderClaimEvent]:
    return list(
        session.execute(
            select(OrderClaimEvent).where(OrderClaimEvent.claim_id == claim_id).order_by(OrderClaimEvent.id.asc())
        ).scalars()
    )


def _naive(value: datetime) -> datetime:
    # SQLite 는 DateTime(timezone=True) 값도 조회 시 tzinfo 를 잃는다(Postgres 는 안 그럼) —
    # 같은 시각인지 비교할 때는 tzinfo 를 벗겨서 값 자체만 비교한다.
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def test_approve_transitions_requested_to_approved_and_logs_event(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    response = approve_admin_claim(session, claim.claim_code)
    session.commit()

    assert response.status == "APPROVED"
    assert response.available_actions == ["START"]
    reloaded = session.execute(select(OrderClaim).where(OrderClaim.id == claim.id)).scalar_one()
    assert reloaded.status == "APPROVED"
    assert reloaded.processed_at is not None
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].from_status == "REQUESTED"
    assert events[1].to_status == "APPROVED"
    assert events[1].actor_type == "ADMIN"
    assert events[1].actor_id is None


def test_approve_is_idempotent_and_does_not_duplicate_event(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    first = approve_admin_claim(session, claim.claim_code)
    session.commit()
    second = approve_admin_claim(session, claim.claim_code)
    session.commit()

    assert first.status == "APPROVED"
    assert second.status == "APPROVED"
    assert len(_events(session, claim.id)) == 2


def test_approve_rejects_already_rejected_claim(session: Session) -> None:
    claim = _make_claim(session, status="REJECTED")
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_claim(session, claim.claim_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_ALREADY_REJECTED"


@pytest.mark.parametrize("status", ["IN_PROGRESS", "COMPLETED", "WITHDRAWN"])
def test_approve_rejects_non_requested_claim(session: Session, status: str) -> None:
    claim = _make_claim(session, status=status)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_claim(session, claim.claim_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_NOT_REQUESTED"


def test_approve_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        approve_admin_claim(session, "clm_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_reject_transitions_requested_to_rejected_and_logs_reason(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    response = reject_admin_claim(session, claim.claim_code, rejection_reason="사진상 파손 확인 안 됨")
    session.commit()

    assert response.status == "REJECTED"
    assert response.available_actions == []
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].to_status == "REJECTED"
    assert events[1].reason == "사진상 파손 확인 안 됨"
    assert events[1].actor_type == "ADMIN"
    assert events[1].actor_id is None


def test_reject_is_idempotent_and_does_not_duplicate_event(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    first = reject_admin_claim(session, claim.claim_code, rejection_reason="사유1")
    session.commit()
    second = reject_admin_claim(session, claim.claim_code, rejection_reason="사유2")
    session.commit()

    assert first.status == "REJECTED"
    assert second.status == "REJECTED"
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].reason == "사유1"  # 재호출은 새 사유로 덮어쓰지 않는다


def test_reject_requires_non_blank_reason(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_claim(session, claim.claim_code, rejection_reason="   ")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REJECTION_REASON_REQUIRED"


def test_reject_rejects_already_approved_claim(session: Session) -> None:
    claim = _make_claim(session, status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_claim(session, claim.claim_code, rejection_reason="사유")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_ALREADY_APPROVED"


def test_reject_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        reject_admin_claim(session, "clm_does_not_exist", rejection_reason="사유")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_reject_rolls_back_when_session_is_rolled_back(session: Session) -> None:
    claim = _make_claim(session)
    session.commit()

    reject_admin_claim(session, claim.claim_code, rejection_reason="사유")
    session.rollback()

    reloaded = session.execute(select(OrderClaim).where(OrderClaim.id == claim.id)).scalar_one()
    assert reloaded.status == "REQUESTED"
    assert len(_events(session, claim.id)) == 1


# ---- 처리 시작 ----


def test_start_transitions_approved_to_in_progress_and_logs_event(session: Session) -> None:
    claim = _make_claim(session, status="APPROVED")
    session.commit()

    response = start_admin_claim(session, claim.claim_code)
    session.commit()

    assert response.status == "IN_PROGRESS"
    assert response.available_actions == ["COMPLETE"]
    reloaded = session.execute(select(OrderClaim).where(OrderClaim.id == claim.id)).scalar_one()
    assert reloaded.status == "IN_PROGRESS"
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].from_status == "APPROVED"
    assert events[1].to_status == "IN_PROGRESS"
    assert events[1].actor_type == "ADMIN"
    assert events[1].actor_id is None


def test_start_does_not_overwrite_processed_at_from_approval(session: Session) -> None:
    claim = _make_claim(session, status="REQUESTED")
    session.commit()

    approved = approve_admin_claim(session, claim.claim_code)
    session.commit()
    approval_processed_at = approved.processed_at
    assert approval_processed_at is not None

    started = start_admin_claim(session, claim.claim_code)
    session.commit()

    assert _naive(started.processed_at) == _naive(approval_processed_at)  # 처리 시작이 승인 시각을 덮어쓰면 안 된다
    reloaded = session.execute(select(OrderClaim).where(OrderClaim.id == claim.id)).scalar_one()
    assert _naive(reloaded.processed_at) == _naive(approval_processed_at)


def test_start_is_idempotent_and_does_not_duplicate_event(session: Session) -> None:
    claim = _make_claim(session, status="APPROVED")
    session.commit()

    first = start_admin_claim(session, claim.claim_code)
    session.commit()
    second = start_admin_claim(session, claim.claim_code)
    session.commit()

    assert first.status == "IN_PROGRESS"
    assert second.status == "IN_PROGRESS"
    assert len(_events(session, claim.id)) == 2


@pytest.mark.parametrize("status", ["REQUESTED", "REJECTED", "COMPLETED", "WITHDRAWN"])
def test_start_rejects_non_approved_claim(session: Session, status: str) -> None:
    claim = _make_claim(session, status=status)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        start_admin_claim(session, claim.claim_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_NOT_APPROVED"


def test_start_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        start_admin_claim(session, "clm_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


# ---- 완료 ----


def test_complete_refund_claim_creates_refund_and_logs_event(session: Session) -> None:
    claim = _make_claim(session, status="IN_PROGRESS", claim_type="REFUND")
    session.commit()

    response = complete_admin_claim(session, claim.claim_code, restock=False)
    session.commit()

    assert response.status == "COMPLETED"
    assert response.available_actions == []
    assert response.completed_at is not None
    reloaded = session.execute(select(OrderClaim).where(OrderClaim.id == claim.id)).scalar_one()
    assert reloaded.status == "COMPLETED"
    payment = session.execute(select(Payment).where(Payment.order_id == claim.order_id)).scalar_one()
    assert payment.status == "REFUNDED"
    refund = session.execute(select(PaymentRefund).where(PaymentRefund.claim_id == claim.id)).scalar_one()
    assert refund.amount == 10000
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].to_status == "COMPLETED"
    assert events[1].actor_type == "ADMIN"


def test_complete_refund_claim_with_toss_payment_succeeds(session: Session) -> None:
    # TOSS 로 결제된 배송완료 주문도 관리자가 환불/반품 완료 처리를 할 수 있어야 한다 —
    # 이전에는 MOCK 결제만 허용해 TOSS 주문은 완료 처리 자체가 불가능했다.
    claim = _make_claim(session, status="IN_PROGRESS", claim_type="REFUND", provider="TOSS")
    session.commit()

    response = complete_admin_claim(session, claim.claim_code, restock=False)
    session.commit()

    assert response.status == "COMPLETED"
    payment = session.execute(select(Payment).where(Payment.order_id == claim.order_id)).scalar_one()
    assert payment.status == "REFUNDED"
    refund = session.execute(select(PaymentRefund).where(PaymentRefund.claim_id == claim.id)).scalar_one()
    assert refund.provider == "TOSS"


def test_complete_return_claim_with_restock_updates_inventory(session: Session) -> None:
    claim = _make_claim(session, status="IN_PROGRESS", claim_type="RETURN")
    session.commit()

    complete_admin_claim(session, claim.claim_code, restock=True)
    session.commit()

    claim_item = session.execute(select(OrderClaimItem).where(OrderClaimItem.claim_id == claim.id)).scalar_one()
    order_item = session.execute(select(OrderItem).where(OrderItem.id == claim_item.order_item_id)).scalar_one()
    inventory = session.execute(select(Inventory).where(Inventory.product_id == order_item.product_id)).scalar_one()
    movement = session.execute(
        select(InventoryMovement).where(InventoryMovement.reference_id == claim.claim_code)
    ).scalar_one()

    assert order_item.status == "RETURNED"
    assert inventory.stock_quantity == 11
    assert movement.movement_type == "RETURN_RESTOCK"


def test_complete_exchange_claim_has_no_payment_or_inventory_effect(session: Session) -> None:
    claim = _make_claim(session, status="IN_PROGRESS", claim_type="EXCHANGE")
    session.commit()

    response = complete_admin_claim(session, claim.claim_code, restock=False)
    session.commit()

    assert response.status == "COMPLETED"
    payment = session.execute(select(Payment).where(Payment.order_id == claim.order_id)).scalar_one()
    assert payment.status == "APPROVED"  # 변경 없음
    assert session.execute(select(PaymentRefund)).scalars().all() == []
    claim_item = session.execute(select(OrderClaimItem).where(OrderClaimItem.claim_id == claim.id)).scalar_one()
    order_item = session.execute(select(OrderItem).where(OrderItem.id == claim_item.order_item_id)).scalar_one()
    assert order_item.status == "EXCHANGED"
    events = _events(session, claim.id)
    assert len(events) == 2
    assert events[1].to_status == "COMPLETED"
    assert events[1].actor_type == "ADMIN"


def test_complete_is_idempotent_and_does_not_duplicate_event(session: Session) -> None:
    claim = _make_claim(session, status="IN_PROGRESS", claim_type="REFUND")
    session.commit()

    first = complete_admin_claim(session, claim.claim_code, restock=False)
    session.commit()
    second = complete_admin_claim(session, claim.claim_code, restock=False)
    session.commit()

    assert first.status == "COMPLETED"
    assert second.status == "COMPLETED"
    assert len(_events(session, claim.id)) == 2
    assert len(session.execute(select(PaymentRefund)).scalars().all()) == 1


@pytest.mark.parametrize("status", ["REQUESTED", "APPROVED", "REJECTED", "WITHDRAWN"])
def test_complete_rejects_non_in_progress_claim(session: Session, status: str) -> None:
    claim = _make_claim(session, status=status)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        complete_admin_claim(session, claim.claim_code, restock=False)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_NOT_IN_PROGRESS"


def test_complete_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        complete_admin_claim(session, "clm_does_not_exist", restock=False)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CLAIM_NOT_FOUND"
