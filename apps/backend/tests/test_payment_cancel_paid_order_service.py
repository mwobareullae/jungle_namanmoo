"""payment_cancel_service.cancel_paid_order() 서비스 테스트 (M1.5-B).

관리자 취소 승인에서 재사용할 공개 단일 주문 취소 서비스: 정상 취소, 멱등 재호출,
상태 불일치, 재고 누락, 실패 시 롤백(flush()까지만 하고 commit은 호출자 책임)을 검증한다.
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
    OrderItem,
    Payment,
    PaymentEvent,
)
from app.schemas.common import ApiError
from app.services.payment_cancel_service import cancel_paid_order


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
    order_status: str = "CANCEL_REQUESTED",
    payment_status: str | None = "APPROVED",
    payment_provider: str = "MOCK",
    item_status: str = "ORDERED",
    item_statuses_override: list[str] | None = None,
    item_count: int = 2,
    quantity_each: int = 1,
    with_inventory: bool = True,
) -> Order:
    global _seq
    _seq += 1
    now = datetime.now(UTC)
    user = User(
        email=f"cancelsvc{_seq}@example.com",
        display_name=None,
        status="ACTIVE",
        role="USER",
    )
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_cancelsvc_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_cancelsvc_{_seq}",
        status=order_status,
        subtotal_amount=1000 * item_count,
        total_amount=1000 * item_count,
        currency="KRW",
        item_count=item_count,
        total_quantity=item_count * quantity_each,
        ordered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    for idx in range(item_count):
        product_id = _seq * 100 + idx + 1
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product_id,
                seller_id=1,
                product_name_snapshot=f"상품{idx + 1}",
                brand_name_snapshot="브랜드",
                seller_name_snapshot="자사",
                unit_price=1000,
                quantity=quantity_each,
                line_subtotal=1000 * quantity_each,
                line_discount_amount=0,
                line_total=1000 * quantity_each,
                currency="KRW",
                status=item_statuses_override[idx] if item_statuses_override else item_status,
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
                payment_code=f"pay_cancelsvc_{_seq}",
                order_id=order.id,
                provider=payment_provider,
                status=payment_status,
                amount=1000 * item_count,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    return order


def _item_statuses(session: Session, order_id: int) -> list[str]:
    return list(session.execute(select(OrderItem.status).where(OrderItem.order_id == order_id)).scalars())


def _load_inventory(session: Session, product_id: int) -> Inventory:
    return session.execute(select(Inventory).where(Inventory.product_id == product_id)).scalar_one()


def test_cancel_paid_order_transitions_order_payment_items_and_restocks(session: Session) -> None:
    order = _make_order(session, order_status="CANCEL_REQUESTED", payment_status="APPROVED", item_count=2)
    session.commit()
    item_product_ids = [item.product_id for item in session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    ).scalars()]

    result = cancel_paid_order(session, order.order_code)
    session.commit()

    assert result.order_status == "CANCELED"
    assert result.payment_status == "CANCELED"
    assert result.idempotent_replay is False
    order_row = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
    payment_row = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert order_row.status == "CANCELED"
    assert order_row.canceled_at is not None
    assert payment_row.status == "CANCELED"
    assert _item_statuses(session, order.id) == ["CANCELED", "CANCELED"]
    for product_id in item_product_ids:
        inventory = _load_inventory(session, product_id)
        assert inventory.stock_quantity == 11
        movement = session.execute(
            select(InventoryMovement).where(InventoryMovement.product_id == product_id)
        ).scalar_one()
        assert movement.movement_type == "SALE_CANCEL"
        assert movement.quantity_delta == 1


def test_cancel_paid_order_is_idempotent_on_fully_canceled_order(session: Session) -> None:
    order = _make_order(session, order_status="CANCEL_REQUESTED", payment_status="APPROVED", item_count=1)
    session.commit()

    first = cancel_paid_order(session, order.order_code)
    session.commit()
    inventory_after_first = _load_inventory(
        session, session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one().product_id
    ).stock_quantity

    second = cancel_paid_order(session, order.order_code)
    session.commit()

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.order_status == "CANCELED"
    assert second.payment_status == "CANCELED"
    movements = session.execute(select(InventoryMovement)).scalars().all()
    assert len(movements) == 1
    final_inventory = _load_inventory(
        session, session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one().product_id
    )
    assert final_inventory.stock_quantity == inventory_after_first


@pytest.mark.parametrize(
    ("order_status", "payment_status"),
    [
        ("PAID", "APPROVED"),
        ("CANCEL_REQUESTED", "REFUNDED"),
        ("CANCELED", "APPROVED"),
    ],
)
def test_cancel_paid_order_rejects_state_that_is_neither_pending_nor_fully_canceled(
    session: Session,
    order_status: str,
    payment_status: str,
) -> None:
    order = _make_order(session, order_status=order_status, payment_status=payment_status, item_count=1)
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, order.order_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"


def test_cancel_paid_order_rejects_partially_canceled_items_as_inconsistent(session: Session) -> None:
    order = _make_order(session, order_status="CANCELED", payment_status="CANCELED", item_count=2)
    session.commit()
    first_item = session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id.asc())
    ).scalars().first()
    first_item.status = "CANCELED"
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, order.order_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"


def test_cancel_paid_order_raises_when_inventory_is_missing(session: Session) -> None:
    order = _make_order(
        session,
        order_status="CANCEL_REQUESTED",
        payment_status="APPROVED",
        item_count=1,
        with_inventory=False,
    )
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, order.order_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "INVENTORY_NOT_FOUND"


def test_cancel_paid_order_rejects_non_mock_payment_without_side_effects(session: Session) -> None:
    order = _make_order(
        session,
        order_status="CANCEL_REQUESTED",
        payment_status="APPROVED",
        payment_provider="TOSS",
        item_count=1,
    )
    item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
    inventory_before = _load_inventory(session, item.product_id).stock_quantity
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, order.order_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "MOCK_CANCEL_PROVIDER_MISMATCH"
    session.rollback()
    reloaded_order = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
    reloaded_payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert reloaded_order.status == "CANCEL_REQUESTED"
    assert reloaded_payment.status == "APPROVED"
    assert _item_statuses(session, order.id) == ["ORDERED"]
    assert _load_inventory(session, item.product_id).stock_quantity == inventory_before
    assert session.execute(select(InventoryMovement)).scalars().all() == []


def test_cancel_paid_order_simulates_toss_cancel_only_when_explicitly_enabled(
    session: Session,
) -> None:
    order = _make_order(
        session,
        order_status="CANCEL_REQUESTED",
        payment_status="APPROVED",
        payment_provider="TOSS",
        item_count=1,
    )
    item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
    inventory_before = _load_inventory(session, item.product_id).stock_quantity
    session.commit()

    result = cancel_paid_order(session, order.order_code, simulate_toss_cancel=True)
    session.commit()

    assert result.order_status == "CANCELED"
    assert result.payment_status == "CANCELED"
    assert _item_statuses(session, order.id) == ["CANCELED"]
    assert _load_inventory(session, item.product_id).stock_quantity == inventory_before + item.quantity
    event = session.execute(select(PaymentEvent).where(PaymentEvent.order_id == order.id)).scalar_one()
    assert event.event_type == "ADMIN_TOSS_CANCEL_SIMULATED"
    assert event.provider == "TOSS"
    assert event.status_before == "APPROVED"
    assert event.status_after == "CANCELED"
    assert event.raw_payload_json == {
        "mode": "INTERNAL_SIMULATION",
        "external_provider_called": False,
    }


def test_cancel_paid_order_rejects_pre_execution_partial_item_cancellation_without_double_restock(
    session: Session,
) -> None:
    order = _make_order(
        session,
        order_status="CANCEL_REQUESTED",
        payment_status="APPROVED",
        item_count=2,
        item_statuses_override=["CANCELED", "ORDERED"],
    )
    items = list(
        session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id.asc())
        ).scalars()
    )
    inventory_before = {item.product_id: _load_inventory(session, item.product_id).stock_quantity for item in items}
    session.commit()

    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, order.order_code)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ORDER_CANCEL_STATE_INCONSISTENT"
    session.rollback()
    reloaded_order = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
    reloaded_payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert reloaded_order.status == "CANCEL_REQUESTED"
    assert reloaded_payment.status == "APPROVED"
    for item in items:
        assert _load_inventory(session, item.product_id).stock_quantity == inventory_before[item.product_id]
    assert session.execute(select(InventoryMovement)).scalars().all() == []


def test_cancel_paid_order_only_flushes_and_lets_caller_roll_back(session: Session) -> None:
    order = _make_order(session, order_status="CANCEL_REQUESTED", payment_status="APPROVED", item_count=1)
    session.commit()

    cancel_paid_order(session, order.order_code)
    session.rollback()

    reloaded_order = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
    reloaded_payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
    assert reloaded_order.status == "CANCEL_REQUESTED"
    assert reloaded_payment.status == "APPROVED"
    assert _item_statuses(session, order.id) == ["ORDERED"]
    assert session.execute(select(InventoryMovement)).scalars().all() == []


def test_cancel_paid_order_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        cancel_paid_order(session, "ord_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "ORDER_NOT_FOUND"
