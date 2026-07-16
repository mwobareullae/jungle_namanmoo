from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory
from app.db.session import get_db
from app.api.routes.payments import get_toss_payments_client
from app.main import app
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session, EXAMPLES_DIR)
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_orders_returns_current_user_order_list_with_cursor(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-list@example.com", nickname="order-list")
    first = _create_pending_order(client, db_engine, product_code="prod_001", quantity=1, key="first-list")
    second = _create_pending_order(client, db_engine, product_code="prod_002", quantity=1, key="second-list")

    first_page = client.get("/api/orders", params={"limit": 1})

    assert first_page.status_code == 200
    first_data = first_page.json()
    assert len(first_data["items"]) == 1
    assert first_data["items"][0]["order_code"] == second["order_code"]
    assert first_data["items"][0]["status"] == "PENDING_PAYMENT"
    assert first_data["items"][0]["thumbnail_storage_key"].startswith("products/")
    assert first_data["items"][0]["title"]
    assert first_data["next_cursor"] is not None

    second_page = client.get("/api/orders", params={"limit": 1, "cursor": first_data["next_cursor"]})

    assert second_page.status_code == 200
    second_data = second_page.json()
    assert len(second_data["items"]) == 1
    assert second_data["items"][0]["order_code"] == first["order_code"]
    assert second_data["next_cursor"] is None


def test_get_orders_can_filter_by_status(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-status@example.com", nickname="order-status")
    pending = _create_pending_order(client, db_engine, product_code="prod_001", quantity=1, key="pending-status")
    paid = _create_pending_order(client, db_engine, product_code="prod_002", quantity=1, key="paid-status")
    confirm_response = _confirm_toss_payment(client, paid)
    assert confirm_response.status_code == 200

    response = client.get("/api/orders", params={"status": "PAID"})

    assert response.status_code == 200
    data = response.json()
    assert [item["order_code"] for item in data["items"]] == [paid["order_code"]]
    assert pending["order_code"] not in [item["order_code"] for item in data["items"]]


def test_get_order_summary_returns_all_status_counts_for_current_user(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-summary@example.com", nickname="order-summary")
    pending = _create_pending_order(
        client,
        db_engine,
        product_code="prod_001",
        quantity=1,
        key="summary-pending",
    )
    paid = _create_pending_order(
        client,
        db_engine,
        product_code="prod_002",
        quantity=1,
        key="summary-paid",
    )
    assert _confirm_toss_payment(client, paid).status_code == 200

    response = client.get("/api/orders/summary")

    assert response.status_code == 200
    status_counts = response.json()["status_counts"]
    assert status_counts["PENDING_PAYMENT"] == 1
    assert status_counts["PAID"] == 1
    assert status_counts["DELIVERED"] == 0
    assert set(status_counts) == {
        "PENDING_PAYMENT",
        "PAID",
        "PAYMENT_FAILED",
        "EXPIRED",
        "CANCELED",
        "PREPARING_SHIPMENT",
        "SHIPPED",
        "DELIVERED",
        "CANCEL_REQUESTED",
        "REFUND_REQUESTED",
        "REFUNDED",
        "RETURN_REQUESTED",
        "RETURNED",
        "EXCHANGE_REQUESTED",
        "EXCHANGED",
    }
    assert pending["order_code"]


def test_get_order_summary_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/orders/summary")

    assert response.status_code == 401


def test_get_order_detail_returns_order_snapshots(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-detail@example.com", nickname="order-detail")
    created = _create_pending_order(
        client,
        db_engine,
        product_code="prod_001",
        quantity=2,
        key="detail-order",
        source="ai_recommendation",
        recommendation_id="rec_detail",
        recommendation_rank=3,
    )

    response = client.get(f"/api/orders/{created['order_code']}")

    assert response.status_code == 200
    data = response.json()
    assert data["order_code"] == created["order_code"]
    assert data["status"] == "PENDING_PAYMENT"
    assert data["subtotal"] == 39800
    assert data["shipping_fee"] == 3000
    assert data["total"] == 42800
    assert data["payment"]["payment_code"] == created["payment_code"]
    assert data["payment"]["status"] == "READY"
    assert data["payment_expires_at"] is not None
    assert data["shipped_at"] is None
    assert data["delivered_at"] is None
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["product_id"] == "prod_001"
    assert item["product_name"]
    assert item["brand_name"]
    assert item["seller_name"]
    assert item["thumbnail_storage_key"].startswith("products/")
    assert item["unit_price"] == 19900
    assert item["quantity"] == 2
    assert item["line_total"] == 39800
    assert item["source"] == "ai_recommendation"
    assert item["recommendation_id"] == "rec_detail"
    assert item["recommendation_rank"] == 3
    assert data["shipping_address"]["recipient_name"] == "Kim Wonwoo"
    assert data["shipping_address"]["address1"] == "Seoul"
    assert data["shipping_groups"][0]["shipping_fee"] == 3000


def test_get_order_detail_ownership_is_enforced(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-owner@example.com", nickname="order-owner")
    created = _create_pending_order(client, db_engine, product_code="prod_001", quantity=1, key="owner-order")
    _signup(client, email="order-other@example.com", nickname="order-other")

    response = client.get(f"/api/orders/{created['order_code']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORDER_NOT_FOUND"


def _create_pending_order(
    client: TestClient,
    db_engine: Engine,
    *,
    product_code: str,
    quantity: int,
    key: str,
    source: str | None = None,
    recommendation_id: str | None = None,
    recommendation_rank: int | None = None,
) -> dict:
    _set_inventory(db_engine, product_code, stock_quantity=10)
    body = {"product_id": product_code, "quantity": quantity}
    if source is not None:
        body["source"] = source
    if recommendation_id is not None:
        body["recommendation_id"] = recommendation_id
    if recommendation_rank is not None:
        body["recommendation_rank"] = recommendation_rank
    add_response = client.post("/api/cart/items", json=body)
    assert add_response.status_code == 200
    item_id = next(item["id"] for item in add_response.json()["items"] if item["product_id"] == product_code)
    address_id = _create_address(client)["id"]
    order_response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": key},
        json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "TOSS"},
    )
    assert order_response.status_code == 200
    data = order_response.json()
    return {
        "order_code": data["order_code"],
        "payment_code": data["payment"]["payment_code"],
        "amount": data["total"],
    }


def _confirm_toss_payment(client: TestClient, pending: dict):
    app.dependency_overrides[get_toss_payments_client] = lambda: _FakeTossConfirmClient()
    return client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_order_query_key",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )


class _FakeTossConfirmClient:
    def confirm_payment(self, *, payment_key: str, order_code: str, amount: int) -> dict:
        return {
            "paymentKey": payment_key,
            "orderId": order_code,
            "totalAmount": amount,
            "status": "DONE",
            "method": "카드",
            "approvedAt": "2026-07-05T12:00:00+09:00",
        }


def _signup(client: TestClient, *, email: str, nickname: str) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200


def _create_address(client: TestClient) -> dict:
    response = client.post(
        "/api/me/addresses",
        json={
            "recipient_name": "Kim Wonwoo",
            "phone": "01012345678",
            "postal_code": "12345",
            "address1": "Seoul",
            "address2": "101",
            "delivery_memo": "Leave at door",
            "is_default": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def _set_inventory(
    db_engine: Engine,
    product_code: str,
    *,
    stock_quantity: int,
    reserved_quantity: int = 0,
    safety_stock: int = 0,
    sales_status: str = "ON_SALE",
) -> None:
    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
        inventory = session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one_or_none()
        if inventory is None:
            inventory = Inventory(
                product_id=product.id,
                stock_quantity=stock_quantity,
                reserved_quantity=reserved_quantity,
                safety_stock=safety_stock,
                sales_status=sales_status,
                inventory_source="TEST",
            )
            session.add(inventory)
        else:
            inventory.stock_quantity = stock_quantity
            inventory.reserved_quantity = reserved_quantity
            inventory.safety_stock = safety_stock
            inventory.sales_status = sales_status
        session.commit()
