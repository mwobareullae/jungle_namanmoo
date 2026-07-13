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
from app.db.models.catalog import Product
from app.db.models.commerce import (
    Inventory,
    InventoryMovement,
    Order,
    OrderCancelRequest,
    OrderItem,
    Payment,
    PaymentEvent,
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


def test_cancel_pending_payment_order_releases_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-pending@example.com",
        nickname="cancel-pending",
        quantity=2,
    )

    logs = _capture_performance_logs()
    try:
        response = client.post(
            f"/api/orders/{pending['order_code']}/cancel",
            headers={"x-request-id": "order-cancel-request"},
        )
    finally:
        logs.close()

    assert response.status_code == 200
    assert response.json() == {
        "order_code": pending["order_code"],
        "status": "CANCELED",
        "request_code": None,
    }
    log_payload = next(line for line in logs.json_lines if line["event"] == "order_cancel_completed")
    assert log_payload["request_id"] == "order-cancel-request"
    assert log_payload["order_status"] == "CANCELED"
    assert log_payload["payment_status"] == "CANCELED"
    assert log_payload["released_quantity_total"] == 2
    assert log_payload["idempotent_replay"] is False
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        order_item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        event_log = session.execute(
            select(EventLog).where(EventLog.event_name == "order_cancelled", EventLog.order_id == order.id)
        ).scalar_one()

    assert order.status == "CANCELED"
    assert order.canceled_at is not None
    assert payment.status == "CANCELED"
    assert payment.canceled_at is not None
    assert order_item.status == "CANCELED"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert movements[1].quantity_delta == -2
    assert movements[1].stock_after == 10
    assert len(events) == 1
    assert events[0].event_type == "ORDER_PAYMENT_CANCELED"
    assert events[0].status_before == "READY"
    assert events[0].status_after == "CANCELED"
    assert event_log.user_id == order.user_id
    assert event_log.request_id == response.headers["x-request-id"]
    assert event_log.metadata_json["order_status"] == "CANCELED"
    assert event_log.metadata_json["payment_status"] == "CANCELED"


def test_cancel_pending_payment_order_is_idempotent(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-idempotent@example.com",
        nickname="cancel-idempotent",
        quantity=1,
    )

    first_response = client.post(f"/api/orders/{pending['order_code']}/cancel")
    second_response = client.post(f"/api/orders/{pending['order_code']}/cancel")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "CANCELED"
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent)).scalars().all()
        event_logs = session.execute(select(EventLog).where(EventLog.event_name == "order_cancelled")).scalars().all()

    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert len(events) == 1
    assert len(event_logs) == 1


def test_cancel_paid_order_moves_to_cancel_requested_without_stock_change(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-paid@example.com",
        nickname="cancel-paid",
        quantity=2,
    )
    confirm_response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")
    assert confirm_response.status_code == 200

    response = client.post(f"/api/orders/{pending['order_code']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["order_code"] == pending["order_code"]
    assert body["status"] == "CANCEL_REQUESTED"
    assert body["request_code"] is not None
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        event_log = session.execute(
            select(EventLog).where(EventLog.event_name == "order_cancelled", EventLog.order_id == order.id)
        ).scalar_one()
        cancel_request = session.execute(
            select(OrderCancelRequest).where(OrderCancelRequest.order_id == order.id)
        ).scalar_one()

    assert order.status == "CANCEL_REQUESTED"
    assert order.canceled_at is None
    assert payment.status == "APPROVED"
    assert inventory.stock_quantity == 8
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "SALE_CONFIRM"]
    assert len(events) == 1
    assert events[0].event_type == "MOCK_PAYMENT_APPROVED"
    assert event_log.metadata_json["order_status"] == "CANCEL_REQUESTED"
    assert event_log.metadata_json["payment_status"] == "APPROVED"
    assert cancel_request.request_code == body["request_code"]
    assert cancel_request.status == "REQUESTED"
    assert cancel_request.user_id == order.user_id
    assert cancel_request.processed_at is None


def test_cancel_requested_order_replay_returns_same_request_code(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-replay@example.com",
        nickname="cancel-replay",
        quantity=1,
    )
    assert client.post(f"/api/payments/{pending['payment_code']}/mock/confirm").status_code == 200

    first = client.post(f"/api/orders/{pending['order_code']}/cancel")
    second = client.post(f"/api/orders/{pending['order_code']}/cancel")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["request_code"] is not None
    assert second.json()["request_code"] == first.json()["request_code"]
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        cancel_requests = session.execute(
            select(OrderCancelRequest).where(OrderCancelRequest.order_id == order.id)
        ).scalars().all()

    assert len(cancel_requests) == 1


def test_cancel_requested_order_without_request_record_returns_409(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-orphan@example.com",
        nickname="cancel-orphan",
        quantity=1,
    )
    assert client.post(f"/api/payments/{pending['payment_code']}/mock/confirm").status_code == 200
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        order.status = "CANCEL_REQUESTED"
        session.commit()

    logs = _capture_performance_logs()
    try:
        response = client.post(f"/api/orders/{pending['order_code']}/cancel")
    finally:
        logs.close()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_CANCEL_REQUEST_NOT_FOUND"
    failure_log = next(line for line in logs.json_lines if line["event"] == "order_cancel_failed")
    assert failure_log["error_code"] == "ORDER_CANCEL_REQUEST_NOT_FOUND"
    assert not any(line["event"] == "order_cancel_completed" for line in logs.json_lines)
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        cancel_requests = session.execute(
            select(OrderCancelRequest).where(OrderCancelRequest.order_id == order.id)
        ).scalars().all()

    assert order.status == "CANCEL_REQUESTED"
    assert cancel_requests == []


def test_paid_order_cancel_rolls_back_when_request_row_creation_fails(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def override_get_db() -> Generator[Session, None, None]:
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as boom_client:
            pending = _create_pending_order(
                boom_client,
                db_engine,
                email="cancel-rollback@example.com",
                nickname="cancel-rollback",
                quantity=1,
            )
            assert boom_client.post(f"/api/payments/{pending['payment_code']}/mock/confirm").status_code == 200

            original_flush = Session.flush

            def _boom_flush(self: Session, *args: object, **kwargs: object) -> None:
                if any(isinstance(obj, OrderCancelRequest) for obj in self.new):
                    raise RuntimeError("flush boom")
                return original_flush(self, *args, **kwargs)

            monkeypatch.setattr(Session, "flush", _boom_flush)

            response = boom_client.post(f"/api/orders/{pending['order_code']}/cancel")

        assert response.status_code == 500
    finally:
        app.dependency_overrides.clear()

    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        cancel_requests = session.execute(
            select(OrderCancelRequest).where(OrderCancelRequest.order_id == order.id)
        ).scalars().all()
        inventory = _load_inventory(session, "prod_001")

    assert order.status == "PAID"
    assert cancel_requests == []
    assert payment.status == "APPROVED"
    assert inventory.stock_quantity == 9
    assert inventory.reserved_quantity == 0


def test_cancel_order_ownership_is_enforced(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="cancel-owner@example.com",
        nickname="cancel-owner",
        quantity=1,
    )
    _signup(client, email="cancel-other@example.com", nickname="cancel-other")

    response = client.post(f"/api/orders/{pending['order_code']}/cancel")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORDER_NOT_FOUND"
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")

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
