from collections.abc import Generator
from datetime import UTC, datetime
import json
import logging

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, Order, OrderClaim, OrderItem
from app.schemas.common import ApiError
from app.services.agent_openai_runner import CommerceAgentContext, _execute_tool
from app.services.agent_order_tools import confirm_agent_tool_call
from app.services.cart_service import get_cart_response
from app.services.agent_policy import AGENT_TOOL_POLICIES
from app.services.agent_tool_dispatcher import execute_agent_tool, list_agent_tool_names
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR
from tests.test_review_api import _create_order_item


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

    logs = _capture_performance_logs()
    with Session(db_engine) as session:
        try:
            response = execute_agent_tool(
                session,
                tool_name="find_similar_products",
                arguments={"product_id": "prod_001", "limit": 2},
                conversation_id="conv_dispatch",
                request_id="req_dispatch",
                session_id="sess_dispatch",
                anonymous_user_id="anon_dispatch",
            )
            session.commit()
        finally:
            logs.close()

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
    assert tool_call.input_json == {"product_id": "prod_001", "limit": 2, "min_price": None, "max_price": None}
    assert tool_call.output_json["tool_name"] == "find_similar_products"
    assert tool_call.output_json["items"][0]["id"] == "prod_002"
    assert tool_call.executed_at is not None
    assert tool_call.latency_ms is not None
    performance_payload = next(
        line for line in logs.json_lines if line["event"] == "agent_tool_completed"
    )
    assert performance_payload["request_id"] == "req_dispatch"
    assert performance_payload["tool_name"] == "find_similar_products"
    assert performance_payload["status"] == "EXECUTED"
    assert performance_payload["item_count"] == 1


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


def test_prepare_review_draft_uses_reviewable_purchase_without_creating_review(db_engine: Engine) -> None:
    email = "agent-review@example.com"
    with Session(db_engine) as session:
        session.add(User(email=email, display_name="agent-review"))
        session.commit()
    order_item_id = _create_order_item(db_engine, email=email, item_status="DELIVERED")

    with Session(db_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        response = execute_agent_tool(
            session,
            tool_name="prepare_review_draft",
            arguments={
                "rating": 4,
                "review_text": "보습감은 좋았지만 마무리가 조금 끈적였어요.",
            },
            user=user,
            conversation_id="conv_review",
        )

    assert response.ui_action.type == "navigate"
    assert response.ui_action.target == "review_write"
    assert response.ui_action.payload["order_item_id"] == order_item_id
    assert response.ui_action.payload["rating"] == 4
    assert response.ui_action.payload["review_text"] == "보습감은 좋았지만 마무리가 조금 끈적였어요."


def test_prepare_claim_draft_checks_real_eligibility_without_creating_claim(db_engine: Engine) -> None:
    email = "agent-claim@example.com"
    with Session(db_engine) as session:
        session.add(User(email=email, display_name="agent-claim"))
        session.commit()
    order_item_id = _create_order_item(db_engine, email=email, item_status="DELIVERED")

    with Session(db_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        order_code = session.scalar(
            select(Order.order_code).join(OrderItem, OrderItem.order_id == Order.id).where(OrderItem.id == order_item_id)
        )
        order = session.scalar(select(Order).where(Order.order_code == order_code))
        order.status = "DELIVERED"
        order.delivered_at = datetime.now(UTC)
        session.flush()
        response = execute_agent_tool(
            session,
            tool_name="prepare_claim_draft",
            arguments={
                "order_code": order_code,
                "order_item_id": order_item_id,
                "claim_type": "RETURN",
                "reason_code": "CHANGE_OF_MIND",
                "reason_detail": "향이 저와 맞지 않아요.",
            },
            user=user,
            conversation_id="conv_claim",
        )
        claim_count = len(session.scalars(select(OrderClaim)).all())

    assert claim_count == 0
    assert response.requires_confirmation is False
    assert response.ui_action.type == "navigate"
    assert response.ui_action.target == "claim_request"
    assert response.ui_action.payload == {
        "order_code": order_code,
        "order_item_id": order_item_id,
        "claim_type": "RETURN",
        "reason_code": "CHANGE_OF_MIND",
        "reason_detail": "향이 저와 맞지 않아요.",
    }


def test_compose_cart_requires_confirmation_before_bulk_add(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    with Session(db_engine) as session:
        user = User(email="compose@example.com", display_name="compose-user")
        session.add(user)
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="compose_cart",
            arguments={"categories": ["cream", "serum"], "max_budget": 50_000},
            user=user,
            conversation_id="conv_compose",
            request_id="req_compose",
        )
        session.commit()

        assert response.requires_confirmation is True
        assert response.tool_call_id is not None
        assert [item.id for item in response.items] == ["prod_001", "prod_002"]
        assert sum(item.price or 0 for item in response.items) == 42_800
        assert get_cart_response(session, user, None).items == []

        confirmed = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=response.tool_call_id,
            action="confirm",
        )
        session.commit()
        cart = get_cart_response(session, user, None)

    assert confirmed.status == "EXECUTED"
    assert confirmed.ui_action.type == "show_cart"
    assert {item.product_id for item in cart.items} == {"prod_001", "prod_002"}


def test_openai_tool_returns_structured_login_action_for_anonymous_user(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_login_required",
            request_id="req_login_required",
            session_id=None,
            anonymous_user_id=None,
        )
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="add_to_cart",
            arguments={"product_id": "prod_001", "quantity": 1},
        )

    payload = json.loads(result)
    assert payload["conversation_id"] == "conv_login_required"
    assert payload["tool_name"] == "add_to_cart"
    assert payload["error"]["code"] == "AGENT_AUTH_REQUIRED"
    assert payload["ui_action"]["type"] == "noop"
    assert context.last_tool_response is not None


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
