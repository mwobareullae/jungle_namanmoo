from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderClaimEvent, OrderClaimItem, OrderItem
from app.schemas.claim import OrderClaimCreateRequest, OrderClaimItemRequest
from app.schemas.common import ApiError
from app.services.order_claim_service import create_claim, withdraw_claim


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


def _create_delivered_order(session: Session) -> tuple[User, Order, OrderItem]:
    user = User(email="claim@example.com", display_name="claim-user")
    session.add(user)
    session.flush()
    delivered_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    order = Order(
        order_code="ord_claim_test",
        user_id=user.id,
        idempotency_key="claim-test-key",
        status="DELIVERED",
        subtotal_amount=2000,
        shipping_fee=0,
        discount_amount=0,
        total_amount=2000,
        currency="KRW",
        item_count=1,
        total_quantity=2,
        delivered_at=delivered_at,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=1,
        seller_id=1,
        product_name_snapshot="Test product",
        brand_name_snapshot="Test brand",
        seller_name_snapshot="Test seller",
        unit_price=1000,
        quantity=2,
        line_subtotal=2000,
        line_discount_amount=0,
        line_total=2000,
        currency="KRW",
        status="DELIVERED",
    )
    session.add(item)
    session.commit()
    return user, order, item


def test_create_claim_allows_partial_quantity_and_records_event(db_engine: Engine) -> None:
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                reason_detail="Package was damaged.",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim_status = claim.status
        refund_amount = claim.refund_amount
        session.commit()

        claim_item = session.execute(select(OrderClaimItem)).scalar_one()
        event = session.execute(select(OrderClaimEvent)).scalar_one()

    assert claim_status == "REQUESTED"
    assert refund_amount == 1000
    assert claim_item.quantity == 1
    assert claim_item.resolution == "REFUND"
    assert event.to_status == "REQUESTED"
    assert event.actor_type == "USER"


def test_create_claim_rejects_quantity_already_reserved_by_active_claim(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        request = OrderClaimCreateRequest(
            order_code=order.order_code,
            claim_type="EXCHANGE",
            reason_code="SIZE",
            items=[OrderClaimItemRequest(order_item_id=item.id, quantity=2)],
        )
        create_claim(session, user, request)
        session.commit()

        with pytest.raises(ApiError) as error:
            create_claim(session, user, request)

    assert error.value.code == "CLAIM_QUANTITY_EXCEEDED"


def test_withdraw_claim_is_only_allowed_while_requested(db_engine: Engine) -> None:
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="CHANGE_OF_MIND",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        session.commit()

        withdrawn = withdraw_claim(session, user, claim.claim_code, now=now + timedelta(hours=1))
        withdrawn_status = withdrawn.status
        session.commit()

    assert withdrawn_status == "WITHDRAWN"
