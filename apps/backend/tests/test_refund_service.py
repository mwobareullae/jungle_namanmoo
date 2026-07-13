from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentRefund
from app.schemas.claim import OrderClaimCreateRequest, OrderClaimItemRequest
from app.services.order_claim_service import create_claim
from app.services.refund_service import process_mock_refund


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


def test_mock_refund_updates_payment_restock_and_is_idempotent(db_engine: Engine) -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user = User(email="refund@example.com", display_name="refund-user")
        session.add(user)
        session.flush()
        order = Order(
            order_code="ord_refund_test",
            user_id=user.id,
            idempotency_key="refund-test-key",
            status="DELIVERED",
            subtotal_amount=1000,
            shipping_fee=0,
            discount_amount=0,
            total_amount=1000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            delivered_at=now,
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
            quantity=1,
            line_subtotal=1000,
            line_discount_amount=0,
            line_total=1000,
            currency="KRW",
            status="DELIVERED",
        )
        session.add(item)
        payment = Payment(
            payment_code="pay_refund_test",
            order_id=order.id,
            provider="MOCK",
            status="APPROVED",
            amount=1000,
            currency="KRW",
            approved_at=now,
        )
        session.add(payment)
        inventory = Inventory(
            product_id=1,
            stock_quantity=4,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="ON_SALE",
            inventory_source="TEST",
        )
        session.add(inventory)
        session.flush()
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "APPROVED"
        session.commit()

        first = process_mock_refund(session, claim.claim_code, restock=True, now=now)
        session.commit()
        second = process_mock_refund(session, claim.claim_code, restock=True, now=now)
        session.commit()

        saved_payment = session.execute(select(Payment)).scalar_one()
        saved_inventory = session.execute(select(Inventory)).scalar_one()
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == claim.claim_code)
        ).scalars().all()
        refunds = session.execute(select(PaymentRefund)).scalars().all()

    assert first.id == second.id
    assert saved_payment.status == "REFUNDED"
    assert saved_inventory.stock_quantity == 5
    assert len(movements) == 1
    assert movements[0].movement_type == "RETURN_RESTOCK"
    assert len(refunds) == 1
