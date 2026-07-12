from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.commerce import Order, OrderFulfillmentEvent, OrderItem
from app.schemas.common import ApiError
from app.services.fulfillment_service import transition_fulfillment_status


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _create_order(session: Session) -> Order:
    order = Order(
        order_code="ord_fulfillment_test",
        user_id=1,
        idempotency_key="fulfillment-test-key",
        status="PAID",
        subtotal_amount=1000,
        shipping_fee=0,
        discount_amount=0,
        total_amount=1000,
        currency="KRW",
        item_count=1,
        total_quantity=1,
    )
    session.add(order)
    session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=1,
            seller_id=1,
            product_name_snapshot="Test product",
            brand_name_snapshot="Test brand",
            seller_name_snapshot="Test seller",
            unit_price=1000,
            quantity=1,
            line_subtotal=1000,
            line_discount_amount=0,
            line_total=1000,
            currency="KRW",
            status="ORDERED",
        )
    )
    session.commit()
    return order


def test_fulfillment_transition_updates_order_item_timestamp_and_history(db_engine: Engine) -> None:
    transition_time = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        order = _create_order(session)
        transition_fulfillment_status(session, order.order_code, "PREPARING_SHIPMENT", now=transition_time)
        transition_fulfillment_status(session, order.order_code, "SHIPPED", now=transition_time)
        transition_fulfillment_status(session, order.order_code, "DELIVERED", now=transition_time)
        session.commit()

        saved_order = session.execute(select(Order).where(Order.id == order.id)).scalar_one()
        item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
        events = session.execute(
            select(OrderFulfillmentEvent)
            .where(OrderFulfillmentEvent.order_id == order.id)
            .order_by(OrderFulfillmentEvent.id.asc())
        ).scalars().all()

    assert saved_order.status == "DELIVERED"
    assert saved_order.shipped_at == transition_time.replace(tzinfo=None)
    assert saved_order.delivered_at == transition_time.replace(tzinfo=None)
    assert item.status == "DELIVERED"
    assert [event.to_status for event in events] == ["PREPARING_SHIPMENT", "SHIPPED", "DELIVERED"]
    assert events[1].from_status == "PREPARING_SHIPMENT"


def test_fulfillment_transition_rejects_skipping_status(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        order = _create_order(session)

        with pytest.raises(ApiError) as error:
            transition_fulfillment_status(session, order.order_code, "DELIVERED")

    assert error.value.status_code == 409
    assert error.value.code == "INVALID_FULFILLMENT_TRANSITION"
