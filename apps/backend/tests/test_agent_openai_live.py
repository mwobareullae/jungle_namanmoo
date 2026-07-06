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
