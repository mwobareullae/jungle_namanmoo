from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, InventoryMovement, Order, Payment, PaymentEvent
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

def test_mock_confirm_approves_payment_and_converts_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    payment_code = _create_pending_order(
        client,
        db_engine,
        email="payment-confirm@example.com",
        nickname="payment-confirm",
        quantity=2,
    )["payment_code"]

    response = client.post(f"/api/payments/{payment_code}/mock/confirm")

    assert response.status_code == 200
    data = response.json()
    assert data["order_status"] == "PAID"
    assert data["payment_status"] == "APPROVED"
    assert data["approved_at"] is not None
    assert data["failed_at"] is None
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == data["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == payment_code)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()

    assert order.status == "PAID"
    assert order.paid_at is not None
    assert payment.status == "APPROVED"
    assert payment.approved_at is not None
    assert inventory.stock_quantity == 8
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "SALE_CONFIRM"]
    assert movements[1].quantity_delta == -2
    assert movements[1].stock_after == 8
    assert len(events) == 1
    assert events[0].event_type == "MOCK_PAYMENT_APPROVED"
    assert events[0].status_before == "READY"
    assert events[0].status_after == "APPROVED"


def test_mock_confirm_is_idempotent_and_does_not_deduct_stock_twice(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-idempotent@example.com",
        nickname="payment-idempotent",
        quantity=1,
    )

    first_response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")
    second_response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["order_status"] == "PAID"
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent)).scalars().all()

    assert inventory.stock_quantity == 9
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "SALE_CONFIRM"]
    assert len(events) == 1


def test_mock_fail_marks_payment_failed_and_releases_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-fail@example.com",
        nickname="payment-fail",
        quantity=1,
    )

    response = client.post(f"/api/payments/{pending['payment_code']}/mock/fail")

    assert response.status_code == 200
    assert response.json()["order_status"] == "PAYMENT_FAILED"
    assert response.json()["payment_status"] == "FAILED"
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()

    assert order.status == "PAYMENT_FAILED"
    assert payment.status == "FAILED"
    assert payment.failed_at is not None
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert movements[1].quantity_delta == -1
    assert len(events) == 1
    assert events[0].event_type == "MOCK_PAYMENT_FAILED"


def test_mock_payment_ownership_is_enforced(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-owner@example.com",
        nickname="payment-owner",
        quantity=1,
    )
    _signup(client, email="payment-other@example.com", nickname="payment-other")

    response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()

    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "READY"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1


def _create_pending_order(
    client: TestClient,
    db_engine: Engine,
    *,
    email: str,
    nickname: str,
    quantity: int,
) -> dict:
    _signup(client, email=email, nickname=nickname)
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": quantity})
    assert add_response.status_code == 200
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]
    order_response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": f"order-{email}"},
        json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "MOCK"},
    )
    assert order_response.status_code == 200
    data = order_response.json()
    return {
        "order_code": data["order_code"],
        "payment_code": data["payment"]["payment_code"],
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


def _load_inventory(session: Session, product_code: str) -> Inventory:
    product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
    return session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()
