"""배송 상태 전이 서비스 테스트 (M1.5-A).

start_preparation(PAID→PREPARING_SHIPMENT) / start_shipment(→SHIPPED) /
complete_delivery(→DELIVERED) 세 전이 함수와 공통 로직(멱등·행 잠금·item_count 정합성)을
검증한다.
"""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Select, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderFulfillmentEvent, OrderItem, Payment
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
    item_status: str | None = None,
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
    resolved_item_status = item_status or {
        "PAID": "ORDERED",
        "PREPARING_SHIPMENT": "PREPARING_SHIPMENT",
        "SHIPPED": "SHIPPED",
        "DELIVERED": "DELIVERED",
    }.get(order_status, "ORDERED")
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
                status=resolved_item_status,
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
            select(OrderItem.status)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.id.asc())
        ).scalars()
    )


def _fulfillment_events(session: Session, order_id: int) -> list[OrderFulfillmentEvent]:
    return list(
        session.execute(
            select(OrderFulfillmentEvent)
            .where(OrderFulfillmentEvent.order_id == order_id)
            .order_by(OrderFulfillmentEvent.id.asc())
        ).scalars()
    )


def _naive(value: datetime) -> datetime:
    # SQLite 는 DateTime(timezone=True) 값도 조회 시 tzinfo 를 잃는다(Postgres 는 안 그럼) —
    # 같은 now 인지 비교할 때는 tzinfo 를 벗겨서 값 자체만 비교한다.
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


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


@pytest.mark.parametrize(
    ("order_status", "expected_item_status", "transition"),
    [
        ("PAID", "ORDERED", start_preparation),
        ("PREPARING_SHIPMENT", "PREPARING_SHIPMENT", start_shipment),
        ("SHIPPED", "SHIPPED", complete_delivery),
    ],
)
def test_transition_rejects_unexpected_order_item_status(
    session: Session,
    order_status: str,
    expected_item_status: str,
    transition,
) -> None:
    order = _make_order(
        session,
        order_status=order_status,
        payment_status="APPROVED",
        item_count=2,
    )
    session.flush()
    items = session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
    ).scalars().all()
    items[1].status = "RETURNED"
    session.commit()

    with pytest.raises(ApiError) as ei:
        transition(session, order_code=order.order_code)
    assert ei.value.status_code == 409
    assert ei.value.code == "ORDER_ITEMS_INCONSISTENT"

    # 첫 번째 아이템과 Order 는 UPDATE 됐더라도 API 경계의 rollback 으로 모두 원복된다.
    session.rollback()
    reloaded = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
    assert reloaded.status == order_status
    assert _item_statuses(session, reloaded.id) == [expected_item_status, "RETURNED"]
    assert session.execute(
        select(OrderFulfillmentEvent).where(OrderFulfillmentEvent.order_id == reloaded.id)
    ).scalars().all() == []


def test_prepare_idempotent_also_rejects_inconsistent_item_count(session: Session) -> None:
    # 멱등 경로(이미 목표 상태)도 item_count 정합성은 똑같이 확인해야 한다 —
    # 안 그러면 같은 손상 데이터인데 어느 상태에서 접근했느냐에 따라 결과가 달라진다.
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED", item_count=1)
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


# ---------------------------------------------------------------------------
# 행 잠금 회귀 가드
#
# 테스트는 SQLite로 도는데 SQLite는 .with_for_update()를 조용히 무시하므로, 실제
# Postgres에서 잠금이 걸리는지는 이 테스트 스위트로 확인할 수 없다. 대신 서비스가 실행한
# SELECT 문을 가로채 postgres dialect로 컴파일한 SQL에 FOR UPDATE 가 들어있는지 확인한다
# — 누군가 실수로 .with_for_update() 를 지워도 이 테스트가 즉시 잡아준다.
# ---------------------------------------------------------------------------


def test_prepare_locks_order_and_payment_rows_for_update(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED")
    order_code = order.order_code  # commit 으로 만료되기 전에 값을 미리 읽어둔다
    session.commit()

    captured_selects: list[Select] = []
    original_execute = session.execute

    def _spying_execute(statement, *args, **kwargs):
        if isinstance(statement, Select):
            captured_selects.append(statement)
        return original_execute(statement, *args, **kwargs)

    session.execute = _spying_execute  # type: ignore[method-assign]
    try:
        start_preparation(session, order_code=order_code)
    finally:
        session.execute = original_execute  # type: ignore[method-assign]

    # 정상 전이 1회는 Order 조회 + Payment 조회, 두 번의 SELECT 만 실행한다
    assert len(captured_selects) == 2
    for stmt in captured_selects:
        compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in compiled_sql


def test_prepare_idempotent_replay_does_not_lock_payment_row(session: Session) -> None:
    # 멱등 재요청은 쓰기가 없으므로 Payment 를 잠그지 않아야 한다(효율성 개선 확인).
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    order_code = order.order_code
    session.commit()

    captured_selects: list[Select] = []
    original_execute = session.execute

    def _spying_execute(statement, *args, **kwargs):
        if isinstance(statement, Select):
            captured_selects.append(statement)
        return original_execute(statement, *args, **kwargs)

    session.execute = _spying_execute  # type: ignore[method-assign]
    try:
        result = start_preparation(session, order_code=order_code)
    finally:
        session.execute = original_execute  # type: ignore[method-assign]

    assert result.idempotent_replay is True
    payment_selects = [
        stmt for stmt in captured_selects if "payments" in str(stmt).lower()
    ]
    assert payment_selects  # Payment 조회 자체는 여전히 일어남(available_actions 계산용)
    for stmt in payment_selects:
        compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" not in compiled_sql


# ---------------------------------------------------------------------------
# shipped_at/delivered_at + OrderFulfillmentEvent 기록
#
# 실제 전이 1건당 이벤트 1건, updated_at·배송 시각·이벤트 created_at 은 모두 같은
# now 를 쓴다. 멱등 재요청과 실패 경로(결제 미승인·item_count 불일치)는 시각도
# 이벤트도 생성하지 않는다(코드상 두 실패 분기 모두 이 로직보다 먼저 raise 한다).
# ---------------------------------------------------------------------------


def test_prepare_creates_fulfillment_event_without_shipment_timestamps(session: Session) -> None:
    order = _make_order(session, order_status="PAID", payment_status="APPROVED")
    session.commit()

    result = start_preparation(session, order_code=order.order_code)

    assert order.shipped_at is None
    assert order.delivered_at is None
    events = _fulfillment_events(session, order.id)
    assert len(events) == 1
    assert events[0].from_status == "PAID"
    assert events[0].to_status == "PREPARING_SHIPMENT"
    assert events[0].source == "ADMIN"
    assert events[0].reason == "START_PREPARATION"
    # updated_at·이벤트 created_at 은 같은 now 를 씀
    assert _naive(events[0].created_at) == _naive(order.updated_at)
    assert result.idempotent_replay is False


def test_shipment_sets_shipped_at_and_creates_event(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    session.commit()

    start_shipment(session, order_code=order.order_code)

    assert order.shipped_at is not None
    assert order.shipped_at == order.updated_at
    assert order.delivered_at is None
    events = _fulfillment_events(session, order.id)
    assert len(events) == 1
    assert events[0].from_status == "PREPARING_SHIPMENT"
    assert events[0].to_status == "SHIPPED"
    assert events[0].reason == "START_SHIPMENT"
    assert _naive(events[0].created_at) == _naive(order.shipped_at)


def test_delivery_sets_delivered_at_and_creates_event(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED")
    session.commit()

    complete_delivery(session, order_code=order.order_code)

    assert order.delivered_at is not None
    assert order.delivered_at == order.updated_at
    events = _fulfillment_events(session, order.id)
    assert len(events) == 1
    assert events[0].from_status == "SHIPPED"
    assert events[0].to_status == "DELIVERED"
    assert events[0].reason == "COMPLETE_DELIVERY"
    assert _naive(events[0].created_at) == _naive(order.delivered_at)


def test_shipment_idempotent_replay_keeps_timestamp_and_no_duplicate_event(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="APPROVED")
    session.commit()

    first = start_shipment(session, order_code=order.order_code)
    assert first.idempotent_replay is False
    shipped_at_after_first = order.shipped_at
    updated_at_after_first = order.updated_at
    assert len(_fulfillment_events(session, order.id)) == 1

    second = start_shipment(session, order_code=order.order_code)

    assert second.idempotent_replay is True
    assert order.shipped_at == shipped_at_after_first
    assert order.updated_at == updated_at_after_first
    assert len(_fulfillment_events(session, order.id)) == 1  # 새 이벤트 없음


def test_delivery_idempotent_replay_keeps_timestamp_and_no_duplicate_event(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED")
    session.commit()

    complete_delivery(session, order_code=order.order_code)
    delivered_at_after_first = order.delivered_at
    updated_at_after_first = order.updated_at

    complete_delivery(session, order_code=order.order_code)

    assert order.delivered_at == delivered_at_after_first
    assert order.updated_at == updated_at_after_first
    assert len(_fulfillment_events(session, order.id)) == 1


def test_shipment_rejects_unapproved_payment_creates_no_event_or_timestamp(session: Session) -> None:
    order = _make_order(session, order_status="PREPARING_SHIPMENT", payment_status="READY")
    session.commit()

    with pytest.raises(ApiError):
        start_shipment(session, order_code=order.order_code)

    assert order.shipped_at is None
    assert _fulfillment_events(session, order.id) == []


def test_delivery_inconsistent_item_count_creates_no_event_or_timestamp(session: Session) -> None:
    order = _make_order(session, order_status="SHIPPED", payment_status="APPROVED", item_count=1)
    order.item_count = 2
    session.flush()
    session.commit()

    with pytest.raises(ApiError):
        complete_delivery(session, order_code=order.order_code)

    assert order.delivered_at is None
    assert _fulfillment_events(session, order.id) == []
