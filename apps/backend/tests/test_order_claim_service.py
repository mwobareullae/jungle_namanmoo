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


CLAIM_TEST_DELIVERED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
CLAIM_TEST_NOW = CLAIM_TEST_DELIVERED_AT + timedelta(days=1)


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
        delivered_at=CLAIM_TEST_DELIVERED_AT,
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
            now=CLAIM_TEST_NOW,
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
        create_claim(session, user, request, now=CLAIM_TEST_NOW)
        session.commit()

        with pytest.raises(ApiError) as error:
            create_claim(session, user, request, now=CLAIM_TEST_NOW)

    assert error.value.code == "CLAIM_QUANTITY_EXCEEDED"


def test_create_claim_rejects_quantity_already_completed_by_prior_claim(db_engine: Engine) -> None:
    # 이미 COMPLETED(처리 완료)된 클레임의 수량은 다시 청구할 수 없어야 한다.
    # CLAIM_QUANTITY_CONSUMING_STATUSES 가 COMPLETED 를 빼놓았을 때는 이미 환불된 수량을
    # 같은 상품에 대해 재청구할 수 있는 버그가 있었다.
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=2)],
            ),
            now=CLAIM_TEST_NOW,
        )
        claim.status = "COMPLETED"
        session.commit()

        with pytest.raises(ApiError) as error:
            create_claim(
                session,
                user,
                OrderClaimCreateRequest(
                    order_code=order.order_code,
                    claim_type="EXCHANGE",
                    reason_code="SIZE",
                    items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
                ),
                now=CLAIM_TEST_NOW,
            )

    assert error.value.code == "CLAIM_QUANTITY_EXCEEDED"


def test_create_claim_rejects_mixed_return_and_exchange_double_claim(db_engine: Engine) -> None:
    # 같은 상품 수량을 환불로 전부 청구한 뒤, 남은 게 없는데 교환으로 또 청구할 수 없어야
    # 한다 — 수량 합산이 claim_type(resolution)과 무관하게 order_item_id 단위로 이뤄져야 한다.
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=2)],
            ),
            now=CLAIM_TEST_NOW,
        )
        session.commit()

        with pytest.raises(ApiError) as error:
            create_claim(
                session,
                user,
                OrderClaimCreateRequest(
                    order_code=order.order_code,
                    claim_type="EXCHANGE",
                    reason_code="SIZE",
                    items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
                ),
                now=CLAIM_TEST_NOW,
            )

    assert error.value.code == "CLAIM_QUANTITY_EXCEEDED"


@pytest.mark.parametrize("prior_status", ["REJECTED", "WITHDRAWN"])
def test_create_claim_allows_quantity_after_rejected_or_withdrawn_claim(
    db_engine: Engine, prior_status: str
) -> None:
    # REJECTED/WITHDRAWN 은 수량을 소비한 것으로 치지 않으므로, 그 수량은 다시 청구할 수 있어야 한다.
    with Session(db_engine) as session:
        user, order, item = _create_delivered_order(session)
        first = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=2)],
            ),
            now=CLAIM_TEST_NOW,
        )
        first.status = prior_status
        session.commit()

        second = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="EXCHANGE",
                reason_code="SIZE",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=2)],
            ),
            now=CLAIM_TEST_NOW,
        )
        second_status = second.status
        session.commit()

    assert second_status == "REQUESTED"


def test_withdraw_claim_is_only_allowed_while_requested(db_engine: Engine) -> None:
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
            now=CLAIM_TEST_NOW,
        )
        session.commit()

        withdrawn = withdraw_claim(
            session,
            user,
            claim.claim_code,
            now=CLAIM_TEST_NOW + timedelta(hours=1),
        )
        withdrawn_status = withdrawn.status
        session.commit()

    assert withdrawn_status == "WITHDRAWN"
