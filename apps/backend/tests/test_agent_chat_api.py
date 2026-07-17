import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
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
from app.core.config import settings
from app.schemas.agent import (
    AgentChatRequest,
    AgentContextResultItem,
    AgentConversationMessage,
    AgentLastToolResult,
    AgentChatResponse,
    AgentUiAction,
)
from app.schemas.common import ApiError
from app.services.agent_openai_runner import (
    _OpenAICircuitBreaker,
    _OpenAIConcurrencyLimiter,
    _build_agent_input,
    _expected_tool_error_response,
    _extract_retry_after_seconds,
    _get_openai_retry_delay_seconds,
    _is_retryable_openai_exception,
    _to_agent_execution_error,
    run_openai_agent_chat,
)
from app.services.agent_idempotency import claim_agent_request_execution
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


@pytest.mark.parametrize(
    ("error", "code", "message", "retryable"),
    [
        (ApiError(400, "EMPTY_CART", "Cart is empty."), "AGENT_CART_EMPTY", "장바구니가 비어 있어요. 상품을 먼저 담아주세요.", False),
        (ApiError(409, "OUT_OF_STOCK", "Product is out of stock."), "AGENT_OUT_OF_STOCK", "해당 상품은 일시품절이에요.", False),
        (ApiError(409, "INSUFFICIENT_STOCK", "Requested quantity exceeds stock."), "AGENT_INSUFFICIENT_STOCK", "요청한 수량만큼 재고가 없어요.", False),
        (ApiError(500, "DATABASE_FAILURE", "relation internal_table does not exist"), "AGENT_TOOL_EXECUTION_FAILED", "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.", True),
    ],
)
def test_expected_tool_errors_are_safe_and_localized(
    error: ApiError,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    response = _expected_tool_error_response("conv_test", tool_name="get_cart", error=error)

    assert response.error is not None
    assert response.error.code == code
    assert response.error.message == message
    assert response.error.retryable is retryable
    assert "internal_table" not in response.message


def test_agent_retry_policy_only_retries_transient_provider_failures() -> None:
    assert _is_retryable_openai_exception(TimeoutError()) is True
    assert _is_retryable_openai_exception(ConnectionError()) is True
    assert _is_retryable_openai_exception(ValueError("invalid tool arguments")) is False

    class ServerFailure(Exception):
        status_code = 503

    assert _is_retryable_openai_exception(ServerFailure()) is True


def test_agent_retry_prefers_provider_retry_after_header() -> None:
    class RateLimited(Exception):
        status_code = 429
        headers = {"Retry-After": "0.75"}

    error = RateLimited()

    assert _extract_retry_after_seconds(error) == pytest.approx(0.75)
    assert _get_openai_retry_delay_seconds(
        error,
        retry_count=0,
        remaining_budget_seconds=2.0,
    ) == pytest.approx(0.75)


def test_agent_retry_uses_backoff_with_jitter_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.agent_openai_runner.random.uniform", lambda *_args: 0.05)

    assert _get_openai_retry_delay_seconds(
        TimeoutError(),
        retry_count=0,
        remaining_budget_seconds=2.0,
    ) == pytest.approx(0.25)


def test_agent_retry_skips_attempt_when_retry_after_exceeds_budget() -> None:
    class RateLimited(Exception):
        status_code = 429
        headers = {"retry-after": "3"}

    assert _get_openai_retry_delay_seconds(
        RateLimited(),
        retry_count=0,
        remaining_budget_seconds=1.0,
    ) is None


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
async def test_agent_openai_concurrency_limiter_rejects_requests_beyond_capacity() -> None:
    limiter = _OpenAIConcurrencyLimiter(
        max_concurrency=2,
        queue_timeout_seconds=0.02,
        retry_after_seconds=3,
    )
    release = asyncio.Event()
    entered = 0
    both_entered = asyncio.Event()

    async def hold_slot() -> None:
        nonlocal entered
        async with limiter.limit():
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()

    holders = [asyncio.create_task(hold_slot()) for _ in range(2)]
    await asyncio.wait_for(both_entered.wait(), timeout=1)

    async def overflow() -> ApiError:
        with pytest.raises(ApiError) as captured:
            async with limiter.limit():
                raise AssertionError("overflow request must not enter the provider slot")
        return captured.value

    overflow_errors = await asyncio.gather(overflow(), overflow())
    assert all(error.status_code == 429 for error in overflow_errors)
    assert all(error.code == "AGENT_OPENAI_BUSY" for error in overflow_errors)
    assert all(error.headers == {"Retry-After": "3"} for error in overflow_errors)

    release.set()
    await asyncio.gather(*holders)


def test_api_error_response_includes_retry_after_header(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_busy(*_args, **_kwargs) -> AgentChatResponse:
        raise ApiError(
            429,
            "AGENT_OPENAI_BUSY",
            "AI 요청이 잠시 많아요. 잠시 후 다시 시도해주세요.",
            headers={"Retry-After": "2"},
        )

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", reject_busy)
    response = client.post("/api/agent/chat", json={"message": "보습 세럼 추천해줘"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    assert response.json()["error"]["code"] == "AGENT_OPENAI_BUSY"


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


def test_agent_chat_replays_completed_response_for_same_idempotency_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def fake_run_openai_agent_chat(*_args, **_kwargs) -> AgentChatResponse:
        nonlocal call_count
        call_count += 1
        return AgentChatResponse(
            conversation_id="conv_idempotent",
            message="장바구니에 담았어요.",
            tool_name="add_to_cart",
            ui_action=AgentUiAction(type="show_cart", target="cart", payload={"cart_item_id": 1}),
        )

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)
    headers = {"Idempotency-Key": "agent-request-replay-0001"}
    payload = {"message": "현재 상품을 장바구니에 담아줘"}

    first = client.post("/api/agent/chat", json=payload, headers=headers)
    second = client.post("/api/agent/chat", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert call_count == 1


def test_agent_chat_rejects_different_request_with_reused_idempotency_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_openai_agent_chat(*_args, **_kwargs) -> AgentChatResponse:
        return AgentChatResponse(conversation_id="conv_idempotent", message="확인했어요.")

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)
    headers = {"Idempotency-Key": "agent-request-reuse-0001"}

    assert client.post("/api/agent/chat", json={"message": "보습 세럼 추천해줘"}, headers=headers).status_code == 200
    response = client.post("/api/agent/chat", json={"message": "진정 토너 추천해줘"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_IDEMPOTENCY_KEY_REUSED"


def test_agent_request_allows_retry_after_stale_pending_execution(db_engine: Engine) -> None:
    request = AgentChatRequest(message="현재 상품을 장바구니에 담아줘")
    key = "agent-request-stale-0001"

    with Session(db_engine) as session:
        execution, replay = claim_agent_request_execution(
            session,
            idempotency_key=key,
            request=request,
            user_id=123,
            anonymous_cart_id=None,
        )
        assert execution is not None
        assert replay is None
        execution.updated_at = datetime.now(UTC) - timedelta(minutes=3)
        session.commit()

    with Session(db_engine) as session:
        retried_execution, replay = claim_agent_request_execution(
            session,
            idempotency_key=key,
            request=request,
            user_id=123,
            anonymous_cart_id=None,
        )

        assert retried_execution is not None
        assert retried_execution.status == "PENDING"
        assert replay is None


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
