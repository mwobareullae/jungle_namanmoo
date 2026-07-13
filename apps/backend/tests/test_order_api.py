from collections.abc import Generator
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import (
    Cart,
    CartItem,
    Inventory,
    InventoryMovement,
    Order,
    OrderItem,
    OrderShippingAddress,
    OrderShippingGroup,
    Payment,
    UserAddress,
)
from app.db.models.events import EventLog
from app.db.session import get_db
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


def test_create_order_reserves_inventory_and_snapshots_selected_items(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-create@example.com", nickname="order-create")
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    first_add = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 2})
    second_add = client.post(
        "/api/cart/items",
        json={
            "product_id": "prod_002",
            "quantity": 1,
            "source": "ai_recommendation",
            "recommendation_id": "rec_order",
            "recommendation_rank": 2,
        },
    )
    assert first_add.status_code == 200
    assert second_add.status_code == 200
    selected_item_id = next(item["id"] for item in second_add.json()["items"] if item["product_id"] == "prod_002")
    address_id = _create_address(client)["id"]

    logs = _capture_performance_logs()
    try:
        response = client.post(
            "/api/orders",
            headers={"Idempotency-Key": "order-create-key", "x-request-id": "order-create-request"},
            json={
                "cart_item_ids": [selected_item_id],
                "address_id": address_id,
                "payment_provider": "TOSS",
            },
        )
    finally:
        logs.close()

    assert response.status_code == 200
    data = response.json()
    assert data["order_code"].startswith("ord_")
    assert data["status"] == "PENDING_PAYMENT"
    assert data["payment"]["payment_code"].startswith("pay_")
    assert data["payment"]["provider"] == "TOSS"
    assert data["payment"]["status"] == "READY"
    assert data["subtotal"] == 22900
    assert data["shipping_fee"] == 3000
    assert data["discount_total"] == 0
    assert data["total"] == 25900
    log_payload = next(line for line in logs.json_lines if line["event"] == "order_create_completed")
    assert log_payload["request_id"] == "order-create-request"
    assert log_payload["requested_item_count"] == 1
    assert log_payload["selected_item_count"] == 1
    assert log_payload["reserved_item_count"] == 1
    assert log_payload["reserved_quantity_total"] == 1
    assert log_payload["seller_count"] == 1
    assert log_payload["subtotal_amount"] == 22900
    assert log_payload["shipping_fee"] == 3000
    assert log_payload["total_amount"] == 25900
    assert log_payload["payment_provider"] == "TOSS"
    assert log_payload["idempotent_replay"] is False

    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == "order-create@example.com")).scalar_one()
        order = session.execute(select(Order).where(Order.order_code == data["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.order_id == order.id)).scalar_one()
        order_item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
        shipping_address = session.execute(
            select(OrderShippingAddress).where(OrderShippingAddress.order_id == order.id)
        ).scalar_one()
        shipping_group = session.execute(select(OrderShippingGroup).where(OrderShippingGroup.order_id == order.id)).scalar_one()
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        prod_001_inventory = _load_inventory(session, "prod_001")
        prod_002_inventory = _load_inventory(session, "prod_002")
        active_cart = session.execute(
            select(Cart).where(Cart.user_id == user.id, Cart.status == "ACTIVE")
        ).scalar_one()
        active_items = session.execute(select(CartItem).where(CartItem.cart_id == active_cart.id)).scalars().all()
        order_created_event = session.execute(
            select(EventLog).where(EventLog.event_name == "order_created", EventLog.order_id == order.id)
        ).scalar_one()

    assert order.cart_id is not None
    assert order.item_count == 1
    assert order.total_quantity == 1
    assert payment.amount == 25900
    assert payment.provider_order_id == order.order_code
    assert order_item.cart_item_id == selected_item_id
    assert order_item.product_name_snapshot
    assert order_item.brand_name_snapshot
    assert order_item.seller_name_snapshot
    assert order_item.thumbnail_storage_key_snapshot.startswith("products/")
    assert order_item.unit_price == 22900
    assert order_item.line_total == 22900
    assert order_item.source == "ai_recommendation"
    assert order_item.recommendation_id == "rec_order"
    assert order_item.recommendation_rank == 2
    assert shipping_address.user_address_id == address_id
    assert shipping_address.recipient_name == "Kim Wonwoo"
    assert shipping_group.item_subtotal == 22900
    assert shipping_group.shipping_fee == 3000
    assert len(movements) == 1
    assert movements[0].movement_type == "RESERVE"
    assert movements[0].quantity_delta == 1
    assert prod_001_inventory.reserved_quantity == 0
    assert prod_002_inventory.reserved_quantity == 1
    assert [item.product_id for item in active_items] == [_product_id(db_engine, "prod_001")]
    assert order_created_event.user_id == user.id
    assert order_created_event.request_id == response.headers["x-request-id"]
    assert order_created_event.metadata_json["order_code"] == order.order_code
    assert order_created_event.metadata_json["payment_provider"] == "TOSS"
    assert order_created_event.metadata_json["total"] == 25900


def test_create_order_is_idempotent_and_does_not_reserve_twice(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-idempotent@example.com", nickname="order-idempotent")
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]
    request_body = {"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "TOSS"}
    headers = {"Idempotency-Key": "same-order-key"}

    first_response = client.post("/api/orders", headers=headers, json=request_body)
    second_response = client.post("/api/orders", headers=headers, json=request_body)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["order_code"] == first_response.json()["order_code"]
    with Session(db_engine) as session:
        orders = session.execute(select(Order)).scalars().all()
        payments = session.execute(select(Payment)).scalars().all()
        movements = session.execute(select(InventoryMovement).where(InventoryMovement.movement_type == "RESERVE")).scalars().all()
        event_logs = session.execute(select(EventLog).where(EventLog.event_name == "order_created")).scalars().all()
        inventory = _load_inventory(session, "prod_001")

    assert len(orders) == 1
    assert len(payments) == 1
    assert len(movements) == 1
    assert len(event_logs) == 1
    assert inventory.reserved_quantity == 1


def test_create_order_with_direct_address_can_save_address_book(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-direct-address@example.com", nickname="order-direct-address")
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    item_id = add_response.json()["items"][0]["id"]

    response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": "direct-address-key"},
        json={
            "cart_item_ids": [item_id],
            "shipping_address": {
                "recipient_name": "Direct User",
                "phone": "01099998888",
                "postal_code": "99999",
                "address1": "Busan",
                "address2": None,
                "delivery_memo": "Call first",
                "save_to_address_book": True,
                "set_as_default": True,
            },
            "payment_provider": "TOSS",
        },
    )

    assert response.status_code == 200
    with Session(db_engine) as session:
        saved_address = session.execute(select(UserAddress)).scalar_one()
        order = session.execute(select(Order)).scalar_one()
        shipping_address = session.execute(
            select(OrderShippingAddress).where(OrderShippingAddress.order_id == order.id)
        ).scalar_one()

    assert saved_address.recipient_name == "Direct User"
    assert saved_address.is_default is True
    assert shipping_address.user_address_id == saved_address.id
    assert shipping_address.delivery_memo == "Call first"


def test_create_order_rejects_missing_idempotency_key(client: TestClient) -> None:
    _signup(client, email="order-no-key@example.com", nickname="order-no-key")

    response = client.post("/api/orders", json={"cart_item_ids": [1], "address_id": 1})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_create_order_rejects_insufficient_stock_without_reserving(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="order-stock@example.com", nickname="order-stock")
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 2})
    item_id = add_response.json()["items"][0]["id"]
    _set_inventory(db_engine, "prod_001", stock_quantity=1)
    address_id = _create_address(client)["id"]

    logs = _capture_performance_logs()
    try:
        response = client.post(
            "/api/orders",
            headers={"Idempotency-Key": "stock-fail-key", "x-request-id": "order-stock-fail-request"},
            json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "TOSS"},
        )
    finally:
        logs.close()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    log_payload = next(line for line in logs.json_lines if line["event"] == "order_create_failed")
    assert log_payload["request_id"] == "order-stock-fail-request"
    assert log_payload["requested_item_count"] == 1
    assert log_payload["payment_provider"] == "TOSS"
    assert log_payload["error_code"] == "INSUFFICIENT_STOCK"
    with Session(db_engine) as session:
        order_count = len(session.execute(select(Order)).scalars().all())
        inventory = _load_inventory(session, "prod_001")

    assert order_count == 0
    assert inventory.reserved_quantity == 0


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


def _load_inventory(session: Session, product_code: str) -> Inventory:
    product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
    return session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()


def _product_id(db_engine: Engine, product_code: str) -> int:
    with Session(db_engine) as session:
        product_id = session.execute(select(Product.id).where(Product.product_code == product_code)).scalar_one()
    return int(product_id)


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    logger.setLevel(logging.INFO)
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler
