from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderItem
from app.db.session import get_db
from app.main import app


def test_order_claim_api_supports_eligibility_create_list_and_withdraw() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(email="claim-api@example.com", display_name="claim-api")
        session.add(user)
        session.flush()
        order = Order(
            order_code="ord_claim_api",
            user_id=user.id,
            idempotency_key="claim-api-key",
            status="DELIVERED",
            subtotal_amount=1000,
            shipping_fee=0,
            discount_amount=0,
            total_amount=1000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            delivered_at=now - timedelta(days=1),
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
        session.commit()
        user_id = int(user.id)
        order_code = order.order_code
        item_id = int(item.id)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    try:
        with TestClient(app) as client:
            eligibility = client.get(f"/api/orders/{order_code}/claim-eligibility")
            assert eligibility.status_code == 200
            assert eligibility.json()["eligible"] is True
            assert eligibility.json()["items"][0]["claimable_quantity"] == 1

            created = client.post(
                "/api/order-claims",
                json={
                    "order_code": order_code,
                    "claim_type": "RETURN",
                    "reason_code": "DAMAGED",
                    "items": [{"order_item_id": item_id, "quantity": 1}],
                },
            )
            assert created.status_code == 201
            claim_code = created.json()["claim_code"]
            assert created.json()["status"] == "REQUESTED"
            assert created.json()["refund_amount"] == 1000

            listed = client.get("/api/order-claims")
            assert listed.status_code == 200
            assert [claim["claim_code"] for claim in listed.json()["items"]] == [claim_code]

            withdrawn = client.post(f"/api/order-claims/{claim_code}/withdraw")
            assert withdrawn.status_code == 200
            assert withdrawn.json()["status"] == "WITHDRAWN"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
