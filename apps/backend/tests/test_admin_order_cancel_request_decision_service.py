"""관리자 취소 요청 승인·거절 서비스 테스트 (M1.5-B).

승인은 payment_cancel_service.cancel_paid_order() 를 재사용해 실제 취소를 처리하고,
거절은 Order 를 PAID 로 되돌린다. 두 액션 모두 OrderCancelRequest 상태 전이와
같은 트랜잭션에서 처리되며, 멱등·상태 불일치·롤백을 검증한다.
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
    OrderCancelRequest,
    OrderItem,
    Payment,
    PaymentEvent,
)
from app.schemas.common import ApiError
from app.services.admin.order_cancel_request_service import (
    approve_admin_cancel_request,
    reject_admin_cancel_request,
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


def _make_cancel_request(
    session: Session,
    *,
    request_status: str = "REQUESTED",
    order_status: str = "CANCEL_REQUESTED",
    payment_status: str | None = "APPROVED",
    payment_provider: str = "MOCK",
    decision_reason: str | None = None,
    processed_at: datetime | None = None,
    with_inventory: bool = True,
) -> OrderCancelRequest:
    global _seq
    _seq += 1
    now = datetime.now(UTC)
    user = User(email=f"cancelreqdec{_seq}@example.com", display_name=None, status="ACTIVE", role="USER")
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_cancelreqdec_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_cancelreqdec_{_seq}",
        status=order_status,
        subtotal_amount=10000,
        total_amount=10000,
        currency="KRW",
        item_count=1,
        total_quantity=1,
        ordered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    product_id = _seq
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=product_id,
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
            status="ORDERED",
            created_at=now,
            updated_at=now,
        )
    )
    if with_inventory:
        session.add(
            Inventory(
                product_id=product_id,
                stock_quantity=10,
                reserved_quantity=0,
                safety_stock=0,
                sales_status="ON_SALE",
                inventory_source="TEST",
                updated_at=now,
            )
        )
    if payment_status is not None:
        session.add(
            Payment(
                payment_code=f"pay_cancelreqdec_{_seq}",
                order_id=order.id,
                provider=payment_provider,
                status=payment_status,
                amount=10000,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    request = OrderCancelRequest(
        request_code=f"ocr_dec_{_seq}",
        order_id=order.id,
        user_id=user.id,
        status=request_status,
        reason_code="CHANGE_OF_MIND",
        decision_reason=decision_reason,
        requested_at=now,
        processed_at=processed_at,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    session.flush()
    return request


def _load_inventory(session: Session, product_id: int) -> Inventory:
    return session.execute(select(Inventory).where(Inventory.product_id == product_id)).scalar_one()


# ---- 승인 ----


def test_approve_transitions_request_order_payment_and_restocks(session: Session) -> None:
    request = _make_cancel_request(session, payment_provider="MOCK")
    session.commit()

    response = approve_admin_cancel_request(session, request.request_code)
    session.commit()

    assert response.status == "APPROVED"
    assert response.order_status == "CANCELED"
    assert response.available_actions == []
    reloaded_request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == request.id)
    ).scalar_one()
    order = session.execute(select(Order).where(Order.id == request.order_id)).scalar_one()
    payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert reloaded_request.status == "APPROVED"
    assert reloaded_request.processed_at is not None
    assert order.status == "CANCELED"
    assert payment.status == "CANCELED"
    product_id = session.execute(
        select(OrderItem.product_id).where(OrderItem.order_id == order.id)
    ).scalar_one()
    assert _load_inventory(session, product_id).stock_quantity == 11


def test_approve_is_idempotent_on_replay(session: Session) -> None:
    request = _make_cancel_request(session, payment_provider="MOCK")
    session.commit()

    first = approve_admin_cancel_request(session, request.request_code)
    session.commit()
    second = approve_admin_cancel_request(session, request.request_code)
    session.commit()

    assert first.order_status == "CANCELED"
    assert second.order_status == "CANCELED"
    movements = session.execute(select(InventoryMovement)).scalars().all()
    assert len(movements) == 1


def test_approve_rejects_when_approved_request_has_inconsistent_order_state(session: Session) -> None:
    # Request 는 이미 APPROVED 라고 기록돼 있는데 Order 가 실제로는 CANCELED 가 아닌
    # 데이터 불일치 상황 — cancel_paid_order() 를 다시 호출해 "재실행"으로 조용히
    # 복구하면 안 되고, 정합성 오류로 거부해야 한다.
    request = _make_cancel_request(
        session,
        request_status="APPROVED",
        order_status="CANCEL_REQUESTED",
        payment_status="APPROVED",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_cancel_request(session, request.request_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"
    order = session.execute(select(Order).where(Order.id == request.order_id)).scalar_one()
    assert order.status == "CANCEL_REQUESTED"  # 조용히 취소 처리되지 않았어야 함


def test_approve_rejects_when_requested_but_order_already_canceled_elsewhere(session: Session) -> None:
    # Request 는 아직 REQUESTED 인데 Order/Payment 는 이미 CANCELED — 정상 흐름으로는
    # 나올 수 없는 상태(다른 경로가 관리자 승인 없이 처리한 경우 등)라 그대로 승인 처리해
    # 흡수하지 않고 정합성 오류로 거부해야 한다.
    request = _make_cancel_request(
        session,
        request_status="REQUESTED",
        order_status="CANCELED",
        payment_status="CANCELED",
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_cancel_request(session, request.request_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"
    reloaded_request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == request.id)
    ).scalar_one()
    assert reloaded_request.status == "REQUESTED"  # 조용히 APPROVED 로 넘어가지 않았어야 함


def test_approve_simulates_toss_cancel_and_records_payment_event(session: Session) -> None:
    request = _make_cancel_request(session, payment_provider="TOSS")
    session.commit()

    response = approve_admin_cancel_request(session, request.request_code)
    session.commit()

    assert response.status == "APPROVED"
    assert response.order_status == "CANCELED"
    payment = session.execute(select(Payment).where(Payment.order_id == request.order_id)).scalar_one()
    assert payment.provider == "TOSS"
    assert payment.status == "CANCELED"
    event = session.execute(select(PaymentEvent).where(PaymentEvent.order_id == request.order_id)).scalar_one()
    assert event.event_type == "ADMIN_TOSS_CANCEL_SIMULATED"
    assert event.raw_payload_json["external_provider_called"] is False


def test_approve_rejects_already_rejected_request(session: Session) -> None:
    request = _make_cancel_request(
        session,
        request_status="REJECTED",
        order_status="PAID",
        decision_reason="이미 거절됨",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_cancel_request(session, request.request_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CANCEL_REQUEST_ALREADY_REJECTED"


def test_approve_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        approve_admin_cancel_request(session, "ocr_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CANCEL_REQUEST_NOT_FOUND"


def test_approve_rolls_back_request_status_when_cancel_execution_fails(session: Session) -> None:
    request = _make_cancel_request(session, payment_provider="MOCK", with_inventory=False)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        approve_admin_cancel_request(session, request.request_code)
    assert exc_info.value.code == "INVENTORY_NOT_FOUND"
    session.rollback()

    reloaded_request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == request.id)
    ).scalar_one()
    order = session.execute(select(Order).where(Order.id == request.order_id)).scalar_one()
    assert reloaded_request.status == "REQUESTED"
    assert reloaded_request.processed_at is None
    assert order.status == "CANCEL_REQUESTED"


# ---- 거절 ----


def test_reject_transitions_request_and_restores_order_to_paid(session: Session) -> None:
    request = _make_cancel_request(session)
    session.commit()

    response = reject_admin_cancel_request(session, request.request_code, rejection_reason="배송 준비를 계속 진행합니다.")
    session.commit()

    assert response.status == "REJECTED"
    assert response.order_status == "PAID"
    assert response.decision_reason == "배송 준비를 계속 진행합니다."
    assert response.available_actions == []
    order = session.execute(select(Order).where(Order.id == request.order_id)).scalar_one()
    payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert order.status == "PAID"
    assert payment.status == "APPROVED"


def test_reject_is_idempotent_on_replay(session: Session) -> None:
    request = _make_cancel_request(session)
    session.commit()

    first = reject_admin_cancel_request(session, request.request_code, rejection_reason="사유1")
    session.commit()
    second = reject_admin_cancel_request(session, request.request_code, rejection_reason="사유2")
    session.commit()

    assert first.order_status == "PAID"
    assert second.order_status == "PAID"
    reloaded_request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == request.id)
    ).scalar_one()
    assert reloaded_request.decision_reason == "사유1"  # 재호출은 새 사유로 덮어쓰지 않는다


def test_reject_rejects_when_rejected_request_has_inconsistent_payment_state(session: Session) -> None:
    # Request 는 이미 REJECTED, Order 도 PAID 로 맞는데 Payment 가 APPROVED 가 아닌
    # 불일치 상황 — 기존에는 Order.status 만 확인해 이 경우를 그냥 통과시켰다.
    request = _make_cancel_request(
        session,
        request_status="REJECTED",
        order_status="PAID",
        payment_status="CANCELED",
        decision_reason="이전 거절 사유",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_cancel_request(session, request.request_code, rejection_reason="새 사유")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"


def test_reject_requires_non_blank_reason(session: Session) -> None:
    request = _make_cancel_request(session)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_cancel_request(session, request.request_code, rejection_reason="   ")

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "REJECTION_REASON_REQUIRED"


def test_reject_rejects_already_approved_request(session: Session) -> None:
    request = _make_cancel_request(
        session,
        request_status="APPROVED",
        order_status="CANCELED",
        payment_status="CANCELED",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_cancel_request(session, request.request_code, rejection_reason="이제와서 거절")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CANCEL_REQUEST_ALREADY_APPROVED"


def test_reject_rejects_inconsistent_order_state(session: Session) -> None:
    request = _make_cancel_request(session, order_status="PAID")
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        reject_admin_cancel_request(session, request.request_code, rejection_reason="사유")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"


def test_reject_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        reject_admin_cancel_request(session, "ocr_does_not_exist", rejection_reason="사유")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CANCEL_REQUEST_NOT_FOUND"


def test_reject_rolls_back_when_session_is_rolled_back(session: Session) -> None:
    request = _make_cancel_request(session)
    session.commit()

    reject_admin_cancel_request(session, request.request_code, rejection_reason="사유")
    session.rollback()

    reloaded_request = session.execute(
        select(OrderCancelRequest).where(OrderCancelRequest.id == request.id)
    ).scalar_one()
    order = session.execute(select(Order).where(Order.id == request.order_id)).scalar_one()
    assert reloaded_request.status == "REQUESTED"
    assert order.status == "CANCEL_REQUESTED"
