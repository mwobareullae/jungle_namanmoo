from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, Order
from app.db.session import get_db
from app.main import app
from app.services.agent_order_tools import (
    confirm_agent_tool_call,
    lookup_order_status,
    prepare_recent_order_cancel,
)
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


def test_lookup_order_status_returns_order_ui_action(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-status@example.com",
        nickname="agent-status",
        quantity=1,
    )

    with Session(db_engine) as session:
        user = _load_user(session, "agent-status@example.com")
        response = lookup_order_status(session, user, conversation_id="conv_status")

    assert response.conversation_id == "conv_status"
    assert response.tool_name == "order_status_lookup"
    assert response.ui_action.type == "show_order_status"
    assert response.ui_action.target == "order_status"
    assert response.ui_action.payload["order_code"] == created["order_code"]
    assert response.ui_action.payload["order_status"] == "PENDING_PAYMENT"
    assert response.ui_action.payload["payment_status"] == "READY"
    assert response.items[0].id == created["order_code"]
    assert response.items[0].metadata["order_status"] == "PENDING_PAYMENT"


def test_prepare_recent_order_cancel_records_confirmation_without_canceling(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-prepare@example.com",
        nickname="agent-prepare",
        quantity=2,
    )

    with Session(db_engine) as session:
        user = _load_user(session, "agent-prepare@example.com")
        response = prepare_recent_order_cancel(
            session,
            user,
            conversation_id="conv_cancel",
            request_id="req_cancel",
        )
        session.commit()

    assert response.requires_confirmation is True
    assert response.tool_name == "cancel_recent_order"
    assert response.ui_action.type == "open_modal"
    assert response.ui_action.target == "order_cancel_confirm"
    assert response.ui_action.payload["order_code"] == created["order_code"]
    assert response.tool_call_id == response.ui_action.payload["tool_call_id"]

    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == created["order_code"])).scalar_one()
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == response.tool_call_id)
        ).scalar_one()
        inventory = _load_inventory(session, "prod_001")

    assert order.status == "PENDING_PAYMENT"
    assert inventory.reserved_quantity == 2
    assert tool_call.status == "AWAITING_CONFIRMATION"
    assert tool_call.confirmation_required is True
    assert tool_call.tool_name == "cancel_recent_order"
    assert tool_call.output_json["order_code"] == created["order_code"]
    assert tool_call.input_json == {
        "order_code": created["order_code"],
        "requested_action": "cancel_order",
    }


def test_confirm_cancel_tool_executes_pending_cancel_and_releases_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-confirm@example.com",
        nickname="agent-confirm",
        quantity=2,
    )

    with Session(db_engine) as session:
        user = _load_user(session, "agent-confirm@example.com")
        prepared = prepare_recent_order_cancel(session, user)
        session.commit()

    assert prepared.tool_call_id is not None
    response = client.post(
        f"/api/agent/tool-calls/{prepared.tool_call_id}/confirm",
        json={"action": "confirm"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == prepared.tool_call_id
    assert data["status"] == "EXECUTED"
    assert data["ui_action"]["type"] == "show_order_status"
    assert data["ui_action"]["payload"]["order_code"] == created["order_code"]
    assert data["ui_action"]["payload"]["status"] == "CANCELED"

    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == created["order_code"])).scalar_one()
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == prepared.tool_call_id)
        ).scalar_one()
        inventory = _load_inventory(session, "prod_001")

    assert order.status == "CANCELED"
    assert inventory.reserved_quantity == 0
    assert tool_call.status == "EXECUTED"
    assert tool_call.output_json["final_order_status"] == "CANCELED"
    assert tool_call.executed_at is not None


def test_reject_cancel_tool_does_not_cancel_order(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-reject@example.com",
        nickname="agent-reject",
        quantity=1,
    )

    with Session(db_engine) as session:
        user = _load_user(session, "agent-reject@example.com")
        prepared = prepare_recent_order_cancel(session, user)
        rejected = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=prepared.tool_call_id or "",
            action="reject",
        )
        session.commit()

    assert rejected.status == "REJECTED"
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == created["order_code"])).scalar_one()
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == prepared.tool_call_id)
        ).scalar_one()
        inventory = _load_inventory(session, "prod_001")

    assert order.status == "PENDING_PAYMENT"
    assert inventory.reserved_quantity == 1
    assert tool_call.status == "REJECTED"


def test_expired_cancel_tool_is_not_executed(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-expired@example.com",
        nickname="agent-expired",
        quantity=1,
    )

    with Session(db_engine) as session:
        user = _load_user(session, "agent-expired@example.com")
        prepared = prepare_recent_order_cancel(session, user)
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == prepared.tool_call_id)
        ).scalar_one()
        tool_call.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        expired = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=prepared.tool_call_id or "",
            action="confirm",
        )
        session.commit()

    assert expired.status == "EXPIRED"
    assert expired.error is not None
    assert expired.error.code == "AGENT_TOOL_CALL_EXPIRED"
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == created["order_code"])).scalar_one()
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == prepared.tool_call_id)
        ).scalar_one()
        inventory = _load_inventory(session, "prod_001")

    assert order.status == "PENDING_PAYMENT"
    assert inventory.reserved_quantity == 1
    assert tool_call.status == "EXPIRED"


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
        headers={"Idempotency-Key": f"agent-order-{email}"},
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


def _load_user(session: Session, email: str) -> User:
    return session.execute(select(User).where(User.email == email)).scalar_one()
