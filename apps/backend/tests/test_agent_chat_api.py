from collections.abc import Generator
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.core.config import settings
from app.schemas.agent import (
    AgentChatRequest,
    AgentContextResultItem,
    AgentConversationMessage,
    AgentLastToolResult,
    AgentChatResponse,
    AgentUiAction,
)
from app.services.agent_openai_runner import _build_agent_input, _to_agent_execution_error, run_openai_agent_chat
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


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (TimeoutError(), 504, "AGENT_OPENAI_TIMEOUT"),
        (type("APIConnectionError", (Exception,), {})(), 503, "AGENT_OPENAI_UNAVAILABLE"),
        (type("RateLimitError", (Exception,), {"status_code": 429})(), 429, "AGENT_OPENAI_RATE_LIMITED"),
        (type("AuthenticationError", (Exception,), {"status_code": 401})(), 503, "AGENT_OPENAI_CONFIGURATION_ERROR"),
        (type("InternalServerError", (Exception,), {"status_code": 500})(), 503, "AGENT_OPENAI_UNAVAILABLE"),
        (RuntimeError("database details must not leak"), 503, "AGENT_EXECUTION_FAILED"),
    ],
)
def test_agent_execution_errors_are_classified_without_leaking_details(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    mapped = _to_agent_execution_error(error)

    assert mapped.status_code == status_code
    assert mapped.code == code
    assert "database details" not in mapped.message


@pytest.mark.anyio
async def test_agent_runner_uses_explicit_openai_timeout_and_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_runner_run(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(final_output="요청을 확인했어요.")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_timeout_seconds", 25)
    monkeypatch.setattr(settings, "openai_agent_max_retries", 1)
    monkeypatch.setattr("agents.Runner.run", fake_runner_run)

    response = await run_openai_agent_chat(Session(), AgentChatRequest(message="도움이 필요해요."))

    run_config = captured["run_config"]
    client = run_config.model_provider._client
    assert client.timeout == 25
    assert client.max_retries == 1
    assert response.message == "요청을 확인했어요."


@pytest.mark.anyio
async def test_agent_bulk_cart_request_returns_clarification_without_openai() -> None:
    request = AgentChatRequest(message="1~5위 장바구니에 담아줘")

    response = await run_openai_agent_chat(Session(), request)

    assert response.error is not None
    assert response.error.code == "AGENT_CLARIFICATION_REQUIRED"
    assert response.tool_name is None
    assert "한 번에 담는 기능" in response.message


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
