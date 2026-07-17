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
from app.services.agent_openai_runner import (
    _OpenAICircuitBreaker,
    _build_agent_input,
    _is_retryable_openai_exception,
    run_openai_agent_chat,
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


def test_agent_retry_policy_only_retries_transient_provider_failures() -> None:
    assert _is_retryable_openai_exception(TimeoutError()) is True
    assert _is_retryable_openai_exception(ConnectionError()) is True
    assert _is_retryable_openai_exception(ValueError("invalid tool arguments")) is False

    class ServerFailure(Exception):
        status_code = 503

    assert _is_retryable_openai_exception(ServerFailure()) is True


def test_agent_circuit_breaker_opens_after_transient_failure_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_agent_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "openai_agent_circuit_cooldown_seconds", 30.0)
    breaker = _OpenAICircuitBreaker()

    breaker.before_call()
    assert breaker.record_transient_failure() is False
    assert breaker.record_transient_failure() is True

    with pytest.raises(Exception, match="AI 연결이 불안정해요"):
        breaker.before_call()


@pytest.mark.anyio
async def test_agent_bulk_cart_request_returns_clarification_without_openai() -> None:
    request = AgentChatRequest(message="1~5위 장바구니에 담아줘")

    response = await run_openai_agent_chat(Session(), request)

    assert response.error is not None
    assert response.error.code == "AGENT_CLARIFICATION_REQUIRED"
    assert response.tool_name is None
    assert "한 번에 담는 기능" in response.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("담아줘", "담을 상품을 알려주세요"),
        ("추천해줘", "어떤 피부 고민이나 조건"),
        ("상위 상품 담아줘", "몇 개 담을까요"),
    ],
)
async def test_agent_ambiguous_requests_ask_for_missing_scope_without_openai(message: str, expected: str) -> None:
    response = await run_openai_agent_chat(Session(), AgentChatRequest(message=message))

    assert response.error is not None
    assert response.error.code == "AGENT_CLARIFICATION_REQUIRED"
    assert response.tool_name is None
    assert expected in response.message


@pytest.mark.anyio
async def test_agent_multi_action_request_requires_staged_selection_without_openai() -> None:
    response = await run_openai_agent_chat(
        Session(),
        AgentChatRequest(message="인기 상품 중 수부지에 맞는 제품 4개 장바구니에 담아줘"),
    )

    assert response.error is not None
    assert response.error.code == "AGENT_CLARIFICATION_REQUIRED"
    assert response.tool_name is None
    assert "먼저 조건에 맞는 추천 결과" in response.message


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
