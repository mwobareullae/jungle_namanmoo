"""배송 상태 전이 서비스 테스트 (M1.5-A).

Chunk 1: start_preparation(PAID → PREPARING_SHIPMENT)만 검증한다.
start_shipment / complete_delivery 는 다음 Chunk 에서 추가한다.
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
from app.db.models.commerce import Order, OrderItem, Payment
from app.schemas.common import ApiError
from app.services.admin.order_service import complete_delivery, start_preparation, start_shipment


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


def _make_order(
    session: Session,
    *,
    order_status: str = "PAID",
    payment_status: str | None = "APPROVED",
    item_count: int = 1,
) -> Order:
    global _seq
    _seq += 1
    now = datetime.now(UTC)
    user = User(
        email=f"ship{_seq}@example.com",
        display_name=None,
        status="ACTIVE",
        role="USER",
    )
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_ship_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_ship_{_seq}",
        status=order_status,
        subtotal_amount=1000,
        total_amount=1000,
        currency="KRW",
        item_count=item_count,
        total_quantity=item_count,
        ordered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    for idx in range(item_count):
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=idx + 1,
                seller_id=1,
                product_name_snapshot=f"상품{idx + 1}",
                brand_name_snapshot="브랜드",
                seller_name_snapshot="자사",
                unit_price=1000,
                quantity=1,
                line_subtotal=1000,
                line_discount_amount=0,
                line_total=1000,
                currency="KRW",
                status="ORDERED",
                created_at=now,
                updated_at=now,
            )
        )
    if payment_status is not None:
        session.add(
            Payment(
                payment_code=f"pay_ship_{_seq}",
                order_id=order.id,
                provider="MOCK",
                status=payment_status,
                amount=1000,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    return order


def _item_statuses(session: Session, order_id: int) -> list[str]:
    return list(
        session.execute(
            select(OrderItem.status).where(OrderItem.order_id == order_id)
        ).scalars()
    )


def test_prepare_paid_approved_transitions_order_and_items(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED", item_count=3)
    session.commit()

    result = start_preparation(session, order_code=order.order_code)

    assert result.idempotent_replay is False
    assert result.previous_status == "PAID"
    assert result.response.order_status == "PREPARING_SHIPMENT"
    # 배송준비중의 다음 액션은 배송 시작
    assert result.response.available_actions == ["START_SHIPMENT"]
    # Order 와 모든 OrderItem 이 함께 전이됨
    assert order.status == "PREPARING_SHIPMENT"
    assert _item_statuses(session, order.id) == ["PREPARING_SHIPMENT"] * 3


def test_prepare_idempotent_when_already_preparing(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    session.commit()
    before_updated_at = order.updated_at

    result = start_preparation(session, order_code=order.order_code)

    assert result.idempotent_replay is True
    assert result.response.order_status == "PREPARING_SHIPMENT"
    assert result.response.available_actions == ["START_SHIPMENT"]
    # 멱등 재요청은 updated_at 을 다시 바꾸지 않음
    assert order.updated_at == before_updated_at


@pytest.mark.parametrize("later_status", ["SHIPPED", "DELIVERED"])
def test_prepare_rejects_already_shipped_or_delivered(session: Session, later_status: str) -> None:
    order = _make_order(session, order_status=later_status, payment_status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_prepare_rejects_other_order_status(session: Session) -> None:
    order = _make_order(session, order_status="PENDING_PAYMENT", payment_status="READY")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code=order.order_code)
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_prepare_rejects_missing_payment(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status=None)
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_FOUND"


def test_prepare_rejects_unapproved_payment(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="READY")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_APPROVED"


def test_prepare_order_not_found(session: Session) -> None:
    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code="ord_does_not_exist")
    assert ei.value.status_code == 404
    assert ei.value.code == "ORDER_NOT_FOUND"


def test_prepare_rollback_reverts_order_and_items(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED", item_count=2)
    session.commit()

    result = start_preparation(session, order_code=order.order_code)
    assert result.response.order_status == "PREPARING_SHIPMENT"
    assert result.updated_item_count == 2

    # 서비스는 flush 까지만 하므로, router 가 롤백하면 Order·OrderItem 모두 원복돼야 함
    session.rollback()

    reloaded = session.execute(
        select(Order).where(Order.order_code == order.order_code)
    ).scalar_one()
    assert reloaded.status == "PAID"
    assert _item_statuses(session, reloaded.id) == ["ORDERED", "ORDERED"]


def test_prepare_inconsistent_item_count_rejected(session: Session) -> None:
    # 저장된 item_count(2)와 실제 OrderItem 수(1)가 어긋난 이상 데이터
    order = _make_order(session, order_status="PAID", payment_status="APPROVED", item_count=1)
    order.item_count = 2
    session.flush()
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_preparation(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_ITEMS_INCONSISTENT"


def test_prepare_idempotent_ignores_missing_payment(session: Session) -> None:
    # 이미 목표 상태면 결제 확인보다 멱등 판정이 먼저 — 결제 누락이어도 200, actions=[]
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status=None)
    session.commit()

    result = start_preparation(session, order_code=order.order_code)
    assert result.idempotent_replay is True
    assert result.response.order_status == "PREPARING_SHIPMENT"
    assert result.response.available_actions == []


def test_prepare_idempotent_ignores_unapproved_payment(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="READY")
    session.commit()

    result = start_preparation(session, order_code=order.order_code)
    assert result.idempotent_replay is True
    assert result.response.available_actions == []


# ---------------------------------------------------------------------------
# start_shipment: PREPARING_SHIPMENT -> SHIPPED
#
# 공통 로직(rowcount 검증·rollback·404)은 start_preparation 테스트에서 이미 검증했으므로
# 여기서는 start_shipment 의 상태 매핑(expected/target/action)이 정확한지만 확인한다.
# ---------------------------------------------------------------------------


def test_shipment_preparing_approved_transitions_to_shipped(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED", item_count=2)
    session.commit()

    result = start_shipment(session, order_code=order.order_code)

    assert result.idempotent_replay is False
    assert result.previous_status == "PREPARING_SHIPMENT"
    assert result.action == "START_SHIPMENT"
    assert result.response.order_status == "SHIPPED"
    assert order.status == "SHIPPED"


def test_shipment_syncs_all_order_items(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED", item_count=3)
    session.commit()

    result = start_shipment(session, order_code=order.order_code)

    assert result.updated_item_count == 3
    assert _item_statuses(session, order.id) == ["SHIPPED"] * 3


def test_shipment_response_available_actions_is_complete_delivery(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    session.commit()

    result = start_shipment(session, order_code=order.order_code)

    assert result.response.available_actions == ["COMPLETE_DELIVERY"]


def test_shipment_idempotent_when_already_shipped(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED")
    session.commit()
    before_updated_at = order.updated_at

    result = start_shipment(session, order_code=order.order_code)

    assert result.idempotent_replay is True
    assert result.response.order_status == "SHIPPED"
    assert order.updated_at == before_updated_at


def test_shipment_rejects_skip_from_paid(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_shipment(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_shipment_rejects_revert_from_delivered(session: Session) -> None:
    order = _make_order(session, order_status="DELIVERED", payment_status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_shipment(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_shipment_rejects_missing_payment(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status=None)
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_shipment(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_FOUND"


def test_shipment_rejects_unapproved_payment(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="READY")
    session.commit()

    with pytest.raises(ApiError) as ei:
        start_shipment(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_APPROVED"


# ---------------------------------------------------------------------------
# complete_delivery: SHIPPED -> DELIVERED (최종 상태)
#
# 공통 로직(rowcount 검증·rollback·404)은 start_preparation 테스트에서 이미 검증했으므로
# 여기서는 complete_delivery 의 상태 매핑과 "최종 상태라 available_actions 항상 []" 만 확인한다.
# ---------------------------------------------------------------------------


def test_delivery_shipped_approved_transitions_to_delivered(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED", item_count=2)
    session.commit()

    result = complete_delivery(session, order_code=order.order_code)

    assert result.idempotent_replay is False
    assert result.previous_status == "SHIPPED"
    assert result.action == "COMPLETE_DELIVERY"
    assert result.response.order_status == "DELIVERED"
    assert order.status == "DELIVERED"


def test_delivery_syncs_all_order_items(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED", item_count=3)
    session.commit()

    result = complete_delivery(session, order_code=order.order_code)

    assert result.updated_item_count == 3
    assert _item_statuses(session, order.id) == ["DELIVERED"] * 3


def test_delivery_response_available_actions_is_empty(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED")
    session.commit()

    result = complete_delivery(session, order_code=order.order_code)

    assert result.response.available_actions == []


def test_delivery_idempotent_when_already_delivered(session: Session) -> None:
    order = _make_order(session, order_status="DELIVERED", payment_status="APPROVED")
    session.commit()
    before_updated_at = order.updated_at

    result = complete_delivery(session, order_code=order.order_code)

    assert result.idempotent_replay is True
    assert result.response.order_status == "DELIVERED"
    assert result.response.available_actions == []
    assert order.updated_at == before_updated_at


def test_delivery_rejects_skip_from_paid(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as ei:
        complete_delivery(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_delivery_rejects_skip_from_preparing_shipment(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    session.commit()

    with pytest.raises(ApiError) as ei:
        complete_delivery(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_delivery_rejects_missing_payment(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status=None)
    session.commit()

    with pytest.raises(ApiError) as ei:
        complete_delivery(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_FOUND"


def test_delivery_rejects_unapproved_payment(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="READY")
    session.commit()

    with pytest.raises(ApiError) as ei:
        complete_delivery(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_PAYMENT_NOT_APPROVED"
