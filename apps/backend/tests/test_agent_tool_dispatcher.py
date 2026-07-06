from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.agent import AgentToolCall
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory
from app.schemas.common import ApiError
from app.services.agent_policy import AGENT_TOOL_POLICIES
from app.services.agent_tool_dispatcher import execute_agent_tool, list_agent_tool_names
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


def test_dispatcher_lists_registered_agent_tools() -> None:
    assert set(list_agent_tool_names()) == set(AGENT_TOOL_POLICIES)


def test_dispatcher_executes_product_tool_and_records_tool_call(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = execute_agent_tool(
            session,
            tool_name="find_similar_products",
            arguments={"product_id": "prod_001", "limit": 3},
            conversation_id="conv_dispatch",
            request_id="req_dispatch",
            session_id="sess_dispatch",
            anonymous_user_id="anon_dispatch",
        )
        session.commit()

    assert response.tool_name == "find_similar_products"
    assert response.conversation_id == "conv_dispatch"
    assert [item.id for item in response.items] == ["prod_002"]

    with Session(db_engine) as session:
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.request_id == "req_dispatch")
        ).scalar_one()

    assert tool_call.tool_name == "find_similar_products"
    assert tool_call.status == "EXECUTED"
    assert tool_call.confirmation_required is False
    assert tool_call.input_json == {"product_id": "prod_001", "limit": 3, "min_price": None, "max_price": None}
    assert tool_call.output_json["tool_name"] == "find_similar_products"
    assert tool_call.output_json["items"][0]["id"] == "prod_002"
    assert tool_call.executed_at is not None
    assert tool_call.latency_ms is not None


def test_dispatcher_rejects_unknown_tool(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(session, tool_name="not_a_tool", arguments={})

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "UNKNOWN_AGENT_TOOL"


def test_dispatcher_rejects_invalid_arguments(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="compare_products",
                arguments={"product_ids": ["prod_001"]},
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_TOOL_ARGUMENT_INVALID"


def test_dispatcher_rejects_auth_required_tool_without_user(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="order_status_lookup",
                arguments={},
            )

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AGENT_AUTH_REQUIRED"


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
