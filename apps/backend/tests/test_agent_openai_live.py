import asyncio
import json
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.agent import AgentToolCall
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory
from app.db.session import get_db
from app.main import app
from app.schemas.agent import AgentChatRequest, AgentContext
from app.services.agent_openai_runner import run_openai_agent_chat
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OPENAI_AGENT_LIVE") != "1",
    reason="Set RUN_OPENAI_AGENT_LIVE=1 to spend OpenAI API credits on this live smoke test.",
)


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


def test_openai_agent_selects_similar_product_tool(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = asyncio.run(
            run_openai_agent_chat(
                session,
                AgentChatRequest(
                    message="Show similar products for the current product.",
                    conversation_id="conv_live_similar",
                    context=AgentContext(
                        page="product_detail",
                        current_product_id="prod_001",
                        visible_product_ids=["prod_001"],
                    ),
                ),
                request_id="req_live_similar",
            )
        )

    assert response.tool_name == "find_similar_products"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "similar_products"
    assert [item.id for item in response.items] == ["prod_002"]
    assert response.message
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))


def test_openai_agent_selects_compare_products_tool(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = asyncio.run(
            run_openai_agent_chat(
                session,
                AgentChatRequest(
                    message="Compare the selected products.",
                    conversation_id="conv_live_compare",
                    context=AgentContext(
                        page="product_detail",
                        selected_product_ids=["prod_001", "prod_002"],
                        visible_product_ids=["prod_001", "prod_002"],
                    ),
                ),
                request_id="req_live_compare",
            )
        )

    assert response.tool_name == "compare_products"
    assert response.ui_action.type == "show_product_comparison"
    assert response.ui_action.target == "product_comparison"
    assert [item.id for item in response.items] == ["prod_001", "prod_002"]
    assert response.ui_action.payload["layout_hint"] == "bottom_panel"
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))


def test_openai_agent_selects_refine_results_tool(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = asyncio.run(
            run_openai_agent_chat(
                session,
                AgentChatRequest(
                    message="From these products, only show items under 20,000 KRW.",
                    conversation_id="conv_live_refine",
                    context=AgentContext(
                        page="recommendation_results",
                        visible_product_ids=["prod_001", "prod_002"],
                    ),
                ),
                request_id="req_live_refine",
            )
        )

    assert response.tool_name == "refine_product_results"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "refined_products"
    assert [item.id for item in response.items] == ["prod_001"]
    assert response.ui_action.payload["filters"]["max_price"] == 20_000
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))


def test_openai_agent_asks_followup_when_similar_context_is_missing(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        response = asyncio.run(
            run_openai_agent_chat(
                session,
                AgentChatRequest(
                    message="Show me similar products.",
                    conversation_id="conv_live_missing_context",
                    context=AgentContext(page="home"),
                ),
                request_id="req_live_missing_context",
            )
        )

    assert response.tool_name is None
    assert response.ui_action.type == "noop"
    assert response.items == []
    assert response.message
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))


def test_agent_chat_endpoint_runs_openai_agent(client: TestClient, db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Show similar products for the product I am viewing.",
            "conversation_id": "conv_live_endpoint",
            "context": {
                "page": "product_detail",
                "current_product_id": "prod_001",
                "visible_product_ids": ["prod_001"],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tool_name"] == "find_similar_products"
    assert data["ui_action"]["type"] == "show_products"
    assert data["ui_action"]["target"] == "similar_products"
    assert [item["id"] for item in data["items"]] == ["prod_002"]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def test_agent_chat_endpoint_runs_order_status_tool(client: TestClient, db_engine: Engine) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-live-status@example.com",
        nickname="agent-live-status",
        quantity=1,
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Show my latest order status.",
            "conversation_id": "conv_live_order_status",
            "context": {"page": "my_orders"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tool_name"] == "order_status_lookup"
    assert data["ui_action"]["type"] == "show_order_status"
    assert data["ui_action"]["target"] == "order_status"
    assert data["ui_action"]["payload"]["order_code"] == created["order_code"]
    assert data["items"][0]["id"] == created["order_code"]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def test_agent_chat_endpoint_prepares_order_cancel_confirmation(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = _create_pending_order(
        client,
        db_engine,
        email="agent-live-cancel@example.com",
        nickname="agent-live-cancel",
        quantity=1,
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Cancel my latest order.",
            "conversation_id": "conv_live_cancel",
            "context": {"page": "my_orders"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["requires_confirmation"] is True
    assert data["tool_name"] == "cancel_recent_order"
    assert data["ui_action"]["type"] == "open_modal"
    assert data["ui_action"]["target"] == "order_cancel_confirm"
    assert data["ui_action"]["payload"]["order_code"] == created["order_code"]
    assert data["tool_call_id"] == data["ui_action"]["payload"]["tool_call_id"]

    with Session(db_engine) as session:
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.tool_call_id == data["tool_call_id"])
        ).scalar_one()
    assert tool_call.status == "AWAITING_CONFIRMATION"
    assert tool_call.confirmation_required is True
    print(json.dumps(data, ensure_ascii=False, indent=2))


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
        headers={"Idempotency-Key": f"agent-live-order-{email}"},
        json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "MOCK"},
    )
    assert order_response.status_code == 200
    return order_response.json()


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
