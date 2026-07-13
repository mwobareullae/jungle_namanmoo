from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentEvent
from app.db.session import get_db
from app.api.routes.payments import get_toss_payments_client
from app.main import app
from app.services.db_seed import seed_database
from app.services.payment_expiry_service import expire_pending_orders
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


def test_expire_pending_orders_marks_expired_and_releases_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    pending = _create_pending_order(
        client,
        db_engine,
        email="expiry-target@example.com",
        nickname="expiry-target",
        quantity=2,
    )
    _set_payment_expires_at(db_engine, pending["order_code"], now - timedelta(minutes=1))

    logs = _capture_performance_logs()
    try:
        with Session(db_engine) as session:
            result = expire_pending_orders(session, now=now, limit=100)
            session.commit()
    finally:
        logs.close()

    assert result.expired_count == 1
    assert result.order_codes == [pending["order_code"]]
    log_payload = next(line for line in logs.json_lines if line["event"] == "payment_expiry_sweep_completed")
    assert log_payload["limit"] == 100
    assert log_payload["scanned_count"] == 1
    assert log_payload["expired_count"] == 1
    assert log_payload["released_quantity_total"] == 2
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        order_item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()

    assert order.status == "EXPIRED"
    assert _as_utc(order.expired_at) == now
    assert payment.status == "EXPIRED"
    assert _as_utc(payment.expired_at) == now
    assert order_item.status == "CANCELED"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert movements[1].quantity_delta == -2
    assert movements[1].stock_after == 10
    assert len(events) == 1
    assert events[0].event_type == "ORDER_PAYMENT_EXPIRED"
    assert events[0].status_before == "READY"
    assert events[0].status_after == "EXPIRED"


def test_expire_pending_orders_is_idempotent(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    pending = _create_pending_order(
        client,
        db_engine,
        email="expiry-idempotent@example.com",
        nickname="expiry-idempotent",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, pending["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        first_result = expire_pending_orders(session, now=now, limit=100)
        second_result = expire_pending_orders(session, now=now, limit=100)
        session.commit()

    assert first_result.expired_count == 1
    assert second_result.expired_count == 0
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent)).scalars().all()

    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert len(events) == 1


def test_expire_pending_orders_skips_unexpired_and_already_paid_orders(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    unexpired = _create_pending_order(
        client,
        db_engine,
        email="expiry-unexpired@example.com",
        nickname="expiry-unexpired",
        product_code="prod_001",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, unexpired["order_code"], now + timedelta(minutes=5))
    paid = _create_pending_order(
        client,
        db_engine,
        email="expiry-paid@example.com",
        nickname="expiry-paid",
        product_code="prod_002",
        quantity=1,
    )
    confirm_response = _confirm_toss_payment(client, paid)
    assert confirm_response.status_code == 200
    _set_payment_expires_at(db_engine, paid["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        result = expire_pending_orders(session, now=now, limit=100)
        session.commit()

    assert result.expired_count == 0
    assert result.order_codes == []
    with Session(db_engine) as session:
        unexpired_order = session.execute(select(Order).where(Order.order_code == unexpired["order_code"])).scalar_one()
        paid_order = session.execute(select(Order).where(Order.order_code == paid["order_code"])).scalar_one()
        unexpired_inventory = _load_inventory(session, "prod_001")
        paid_inventory = _load_inventory(session, "prod_002")

    assert unexpired_order.status == "PENDING_PAYMENT"
    assert paid_order.status == "PAID"
    assert unexpired_inventory.stock_quantity == 10
    assert unexpired_inventory.reserved_quantity == 1
    assert paid_inventory.stock_quantity == 9
    assert paid_inventory.reserved_quantity == 0


def test_expire_pending_orders_respects_limit(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    first = _create_pending_order(
        client,
        db_engine,
        email="expiry-limit-first@example.com",
        nickname="expiry-limit-first",
        product_code="prod_001",
        quantity=1,
    )
    second = _create_pending_order(
        client,
        db_engine,
        email="expiry-limit-second@example.com",
        nickname="expiry-limit-second",
        product_code="prod_002",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, first["order_code"], now - timedelta(minutes=2))
    _set_payment_expires_at(db_engine, second["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        result = expire_pending_orders(session, now=now, limit=1)
        session.commit()

    assert result.expired_count == 1
    assert result.order_codes == [first["order_code"]]


def _create_pending_order(
    client: TestClient,
    db_engine: Engine,
    *,
    email: str,
    nickname: str,
    product_code: str = "prod_001",
    quantity: int,
) -> dict:
    _signup(client, email=email, nickname=nickname)
    _set_inventory(db_engine, product_code, stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": product_code, "quantity": quantity})
    assert add_response.status_code == 200
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]
    order_response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": f"order-{email}"},
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
            "payment_key": "toss_expiry_key",
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


def _set_payment_expires_at(
    db_engine: Engine,
    order_code: str,
    expires_at: datetime,
) -> None:
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == order_code)).scalar_one()
        order.payment_expires_at = expires_at
        session.commit()


def _load_inventory(session: Session, product_code: str) -> Inventory:
    product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
    return session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()


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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
