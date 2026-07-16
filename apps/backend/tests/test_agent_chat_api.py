from collections.abc import Generator
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas.agent import (
    AgentChatRequest,
    AgentContextResultItem,
    AgentConversationMessage,
    AgentLastToolResult,
    AgentChatResponse,
    AgentUiAction,
)
from app.services.agent_openai_runner import _build_agent_input
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


def test_agent_input_includes_bounded_conversation_context() -> None:
    request = AgentChatRequest(
        message="그중 두 번째를 비교해줘",
        recent_messages=[
            AgentConversationMessage(role="user", content="비슷한 상품 보여줘"),
            AgentConversationMessage(role="assistant", content="두 상품을 찾았어요."),
        ],
        last_tool_result=AgentLastToolResult(
            action_type="show_products",
            target="similar_products",
            items=[
                AgentContextResultItem(item_type="product", id="prod_001", title="첫 번째 상품"),
                AgentContextResultItem(item_type="product", id="prod_002", title="두 번째 상품"),
            ],
        ),
    )

    payload = json.loads(_build_agent_input(request))

    assert payload["recent_messages"][-1] == {"role": "assistant", "content": "두 상품을 찾았어요."}
    assert payload["last_tool_result"]["items"][1]["id"] == "prod_002"
    assert payload["message"] == "그중 두 번째를 비교해줘"


def test_agent_input_omits_empty_context_fields() -> None:
    payload = json.loads(_build_agent_input(AgentChatRequest(message="보습 세럼 추천해줘")))

    assert payload == {"message": "보습 세럼 추천해줘"}


def test_agent_chat_route_returns_runner_response(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    runner_arguments: dict[str, object] = {}

    async def fake_run_openai_agent_chat(*args, **kwargs) -> AgentChatResponse:
        runner_arguments.update(kwargs)
        return AgentChatResponse(
            conversation_id="conv_route",
            message="Similar products are ready.",
            tool_name="find_similar_products",
            ui_action=AgentUiAction(
                type="show_products",
                target="similar_products",
                payload={"source_product_id": "prod_001", "products": []},
            ),
            items=[],
        )

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)

    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Show similar products for the current product.",
            "conversation_id": "conv_route",
            "context": {"current_product_id": "prod_001", "page": "product_detail"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "conv_route"
    assert data["tool_name"] == "find_similar_products"
    assert data["ui_action"]["type"] == "show_products"
    assert data["ui_action"]["target"] == "similar_products"
    assert "mwbl_cart=" in response.headers["set-cookie"]
    assert isinstance(runner_arguments["anonymous_cart_id"], str)


def test_agent_chat_rejects_sensitive_input_before_runner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args, **kwargs) -> AgentChatResponse:
        raise AssertionError("runner must not receive sensitive input")

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fail_if_called)

    response = client.post(
        "/api/agent/chat",
        json={"message": "password: secret-value"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_SENSITIVE_INPUT"
