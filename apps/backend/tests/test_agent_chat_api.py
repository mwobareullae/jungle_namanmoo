import asyncio
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.db.base import Base
from app.db.session import get_db
from app.main import app, db_pool_timeout_handler
from app.core.config import settings
from app.schemas.agent import (
    AgentChatRequest,
    AgentContext,
    AgentContextResultItem,
    AgentConversationMessage,
    AgentLastToolResult,
    AgentChatResponse,
    AgentUiAction,
)
from app.schemas.common import ApiError
from app.services.agent_openai_runner import (
    AGENT_INSTRUCTIONS,
    _OpenAICircuitBreaker,
    _OpenAIConcurrencyLimiter,
    AgentWorkflowTiming,
    _build_agent_input,
    _classify_openai_failure,
    _expected_tool_error_response,
    _extract_retry_after_seconds,
    _get_openai_retry_delay_seconds,
    _log_openai_failure_counter,
    _resolve_agent_model,
    _is_retryable_openai_exception,
    _select_agent_tool_names,
    _to_agent_execution_error,
    run_openai_agent_chat,
)
from app.services.agent_idempotency import claim_agent_request_execution
from app.services.agent_policy import AGENT_TOOL_POLICIES
from app.services.agent_runtime_control import AgentGlobalSlotLease
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
def client(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        "app.api.routes.agent.get_default_agent_runtime_control",
        lambda: _PermissiveAgentRuntimeControl(),
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class _PermissiveAgentRuntimeControl:
    def check_rate_limit(self, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(check_ms=0.0)

    @asynccontextmanager
    async def acquire_global_slot(self):
        yield AgentGlobalSlotLease(
            slot_number=1,
            owner_token="test-owner",
            wait_ms=0.0,
            acquire_ms=0.0,
        )


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
    assert _classify_openai_failure(ServerFailure()) == "provider"

    class RateLimited(Exception):
        status_code = 429

    assert _is_retryable_openai_exception(RateLimited()) is True
    assert _classify_openai_failure(RateLimited()) == "rate_limit"
    assert _is_retryable_openai_exception(
        ApiError(429, "AGENT_OPENAI_BUSY", "busy")
    ) is False


def test_local_model_override_is_disabled_outside_explicit_local_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "openai_agent_local_trace_enabled", True)

    with pytest.raises(ApiError) as captured:
        _resolve_agent_model("gpt-5.4-mini")

    assert captured.value.code == "LOCAL_MODEL_OVERRIDE_NOT_AVAILABLE"

    monkeypatch.setattr(settings, "app_env", "local")
    model, source = _resolve_agent_model("gpt-5.4-mini")
    assert (model, source) == ("gpt-5.4-mini", "local_header_override")


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


def test_agent_openai_failure_counters_use_existing_performance_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "app.services.agent_openai_runner.log_performance_event",
        lambda event, **_kwargs: events.append(event),
    )

    rate_limited = SimpleNamespace(status_code=429)
    _log_openai_failure_counter(
        rate_limited,
        request_id="req-rate",
        duration_ms=10.0,
    )
    _log_openai_failure_counter(
        TimeoutError(),
        request_id="req-timeout",
        duration_ms=20.0,
    )
    _log_openai_failure_counter(
        ApiError(503, "AGENT_OPENAI_CIRCUIT_OPEN", "open"),
        request_id="req-circuit",
        duration_ms=30.0,
    )

    assert events == [
        "AGENT_OPENAI_RATE_LIMITED",
        "AGENT_OPENAI_TIMEOUT",
        "AGENT_OPENAI_CIRCUIT_OPEN",
    ]


@pytest.mark.anyio
async def test_db_pool_timeout_is_logged_and_returns_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "app.main.log_performance_event",
        lambda event, **_kwargs: events.append(event),
    )

    response = await db_pool_timeout_handler(None, SQLAlchemyTimeoutError("pool exhausted"))

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "DB_POOL_TIMEOUT"
    assert events == ["DB_POOL_TIMEOUT"]


def test_agent_circuit_breaker_opens_after_transient_failure_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_agent_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "openai_agent_circuit_cooldown_seconds", 30.0)
    breaker = _OpenAICircuitBreaker()

    breaker.before_call()
    assert breaker.record_failure("provider") is False
    assert breaker.record_failure("provider") is True

    with pytest.raises(Exception, match="AI 연결이 불안정해요"):
        breaker.before_call()


def test_agent_circuit_breaker_ignores_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_agent_circuit_failure_threshold", 2)
    breaker = _OpenAICircuitBreaker()

    assert breaker.record_failure("rate_limit") is False
    assert breaker.record_failure("rate_limit") is False
    breaker.before_call()

    assert breaker.record_failure("provider") is False
    assert breaker.record_failure("provider") is True
    with pytest.raises(ApiError) as captured:
        breaker.before_call()
    assert captured.value.code == "AGENT_OPENAI_CIRCUIT_OPEN"


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


@pytest.mark.anyio
async def test_agent_resilience_integration_limits_concurrency_without_opening_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import Runner

    limiter = _OpenAIConcurrencyLimiter(
        max_concurrency=2,
        queue_timeout_seconds=0.02,
        retry_after_seconds=4,
    )
    breaker = _OpenAICircuitBreaker()
    release = asyncio.Event()
    both_entered = asyncio.Event()
    entered = 0

    async def fake_run(*_args, **_kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await release.wait()
        return SimpleNamespace(final_output="정상 응답")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        limiter,
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        breaker,
    )

    async def invoke(index: int):
        try:
            return await run_openai_agent_chat(
                Session(),
                AgentChatRequest(message=f"보습 세럼 추천 요청 {index}"),
                request_id=f"req-load-{index}",
            )
        except ApiError as exc:
            return exc

    tasks = [asyncio.create_task(invoke(index)) for index in range(4)]
    await asyncio.wait_for(both_entered.wait(), timeout=1)
    await asyncio.sleep(0.04)
    release.set()
    results = await asyncio.gather(*tasks)

    successes = [result for result in results if isinstance(result, AgentChatResponse)]
    rejected = [result for result in results if isinstance(result, ApiError)]
    assert len(successes) == 2
    assert len(rejected) == 2
    assert all(error.code == "AGENT_OPENAI_BUSY" for error in rejected)
    assert all(error.headers == {"Retry-After": "4"} for error in rejected)

    # Local capacity rejections must not poison the process-wide provider circuit.
    breaker.before_call()
    follow_up = await invoke(5)
    assert isinstance(follow_up, AgentChatResponse)
    assert follow_up.message == "정상 응답"


@pytest.mark.anyio
async def test_agent_resilience_integration_retries_429_without_opening_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import Runner

    class RateLimited(Exception):
        status_code = 429
        headers = {"Retry-After": "0"}

    breaker = _OpenAICircuitBreaker()
    provider_calls = 0
    should_succeed = False

    async def fake_run(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if not should_succeed:
            raise RateLimited()
        return SimpleNamespace(final_output="회로 정상")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 1)
    monkeypatch.setattr(settings, "openai_agent_circuit_failure_threshold", 2)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        breaker,
    )

    for index in range(3):
        with pytest.raises(ApiError) as captured:
            await run_openai_agent_chat(
                Session(),
                AgentChatRequest(message=f"세럼 추천 {index}"),
            )
        assert captured.value.code == "AGENT_OPENAI_RATE_LIMITED"

    assert provider_calls == 6
    breaker.before_call()
    should_succeed = True
    response = await run_openai_agent_chat(
        Session(),
        AgentChatRequest(message="세럼 추천 정상화"),
    )
    assert response.message == "회로 정상"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider_error", "expected_error_code"),
    [
        (TimeoutError("provider timeout"), "AGENT_OPENAI_TIMEOUT"),
        (
            type("ProviderServerFailure", (Exception,), {"status_code": 503})(),
            "AGENT_OPENAI_UNAVAILABLE",
        ),
    ],
)
async def test_agent_resilience_integration_opens_circuit_only_for_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
    provider_error: Exception,
    expected_error_code: str,
) -> None:
    from agents import Runner

    breaker = _OpenAICircuitBreaker()
    provider_calls = 0

    async def fake_run(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise provider_error

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(settings, "openai_agent_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "openai_agent_circuit_cooldown_seconds", 30.0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        breaker,
    )

    for _ in range(2):
        with pytest.raises(ApiError) as captured:
            await run_openai_agent_chat(
                Session(),
                AgentChatRequest(message="민감 피부 세럼 추천"),
            )
        assert captured.value.code == expected_error_code

    with pytest.raises(ApiError) as blocked:
        await run_openai_agent_chat(
            Session(),
            AgentChatRequest(message="회로 차단 확인"),
        )
    assert blocked.value.code == "AGENT_OPENAI_CIRCUIT_OPEN"
    assert provider_calls == 2


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


def test_agent_instructions_require_one_clarification_before_ambiguous_tool_use() -> None:
    assert "do not call a tool" in AGENT_INSTRUCTIONS
    assert "exactly one brief clarification question in Korean" in AGENT_INSTRUCTIONS


def test_guest_tool_exposure_removes_every_authenticated_tool() -> None:
    tool_names = _select_agent_tool_names(
        user=None,
        context=AgentContext(
            page="product_detail",
            current_product_id="prod_001",
            visible_product_ids=["prod_001", "prod_002"],
            recommendation_id="rec_001",
        ),
        last_tool_result=None,
    )

    assert set(tool_names) == {
        "create_recommendation",
        "find_similar_products",
        "compare_products",
        "refine_product_results",
        "get_cart",
        "add_to_cart",
    }
    assert all(not AGENT_TOOL_POLICIES[name].requires_auth for name in tool_names)


@pytest.mark.parametrize(
    ("page", "expected_count"),
    [
        ("product_detail", 12),
        ("search_results", 11),
        ("order_history", 9),
        ("order_detail", 9),
        ("checkout", 10),
        ("payment_complete", 9),
        ("skin_test", 6),
        ("login", 6),
        ("home", 17),
    ],
)
def test_authenticated_tool_exposure_is_conservative_by_page(
    page: str,
    expected_count: int,
) -> None:
    tool_names = _select_agent_tool_names(
        user=SimpleNamespace(id=1),
        context=AgentContext(
            page=page,
            current_product_id="prod_001",
            visible_product_ids=["prod_001", "prod_002"],
            recommendation_id="rec_001",
            cart_item_ids=[1],
        ),
        last_tool_result=None,
    )

    assert len(tool_names) == expected_count


def test_shipping_address_tool_stays_available_for_interrupted_checkout() -> None:
    without_continuation = _select_agent_tool_names(
        user=SimpleNamespace(id=1),
        context=AgentContext(page="product_detail"),
        last_tool_result=None,
    )
    with_continuation = _select_agent_tool_names(
        user=SimpleNamespace(id=1),
        context=AgentContext(page="product_detail", cart_item_ids=[10]),
        last_tool_result=None,
    )

    assert "register_shipping_address" not in without_continuation
    assert "register_shipping_address" in with_continuation


def test_demo_flow_tools_remain_exposed_across_context_changes() -> None:
    user = SimpleNamespace(id=1)
    search_tools = set(
        _select_agent_tool_names(
            user=user,
            context=AgentContext(
                page="search_results",
                recommendation_id="rec_001",
                visible_product_ids=["prod_001", "prod_002"],
            ),
            last_tool_result=None,
        )
    )
    product_tools = set(
        _select_agent_tool_names(
            user=user,
            context=AgentContext(
                page="product_detail",
                current_product_id="prod_001",
                visible_product_ids=["prod_001", "prod_002"],
            ),
            last_tool_result=None,
        )
    )
    pending_address_tools = set(
        _select_agent_tool_names(
            user=user,
            context=AgentContext(page="product_detail", cart_item_ids=[10]),
            last_tool_result=None,
        )
    )
    checkout_tools = set(
        _select_agent_tool_names(
            user=user,
            context=AgentContext(page="checkout", cart_item_ids=[10]),
            last_tool_result=None,
        )
    )

    assert {"create_recommendation", "refine_product_results"} <= search_tools
    assert {
        "find_similar_products",
        "compare_products",
        "prepare_product_checkout",
    } <= product_tools
    assert "register_shipping_address" in pending_address_tools
    assert {"prepare_order", "bulk_wishlist_by_popular_ingredient"} <= checkout_tools


@pytest.mark.anyio
async def test_runner_passes_only_selected_guest_tools_and_logs_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import Runner

    captured_tool_names: list[str] = []
    selected_events: list[dict[str, object]] = []

    async def fake_run(agent, *_args, **_kwargs):
        captured_tool_names.extend(tool.name for tool in agent.tools)
        return SimpleNamespace(final_output="조건을 조금 더 알려주세요.")

    def capture_event(event: str, **kwargs) -> None:
        if event == "agent_tools_selected":
            selected_events.append(kwargs["metadata"])

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner.log_performance_event",
        capture_event,
    )

    await run_openai_agent_chat(
        Session(),
        AgentChatRequest(
            message="이 화면에서 도와줘",
            context=AgentContext(
                page="product_detail",
                current_product_id="prod_001",
                visible_product_ids=["prod_001", "prod_002"],
                recommendation_id="rec_001",
            ),
        ),
    )

    assert captured_tool_names == [
        "create_recommendation",
        "find_similar_products",
        "compare_products",
        "refine_product_results",
        "get_cart",
        "add_to_cart",
    ]
    assert selected_events == [
        {
            "authenticated": False,
            "page": "product_detail",
            "tool_count": 6,
            "tool_names": captured_tool_names,
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("담아줘", "담을 상품을 알려주세요"),
        ("추천해줘", "어떤 피부 고민이나 조건"),
        ("피부 때문에 고민이에요", "여드름, 피지, 모공, 속건조, 홍조, 잡티, 피부결"),
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
        headers={"X-MWBL-Session-Id": "sess_agent_route"},
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
    assert runner_arguments["session_id"] == "sess_agent_route"


def test_agent_chat_route_writes_local_raw_trace(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "openai_agent_local_trace_enabled", True)
    monkeypatch.setattr(settings, "openai_agent_local_trace_dir", str(tmp_path))

    captured_model_overrides: list[str | None] = []

    async def fake_run_openai_agent_chat(*_args, **kwargs) -> AgentChatResponse:
        trace = kwargs["local_trace"]
        assert trace is not None
        captured_model_overrides.append(kwargs["model_override"])
        kwargs["workflow_timing"].agent_runner_ms = 123.4
        return AgentChatResponse(
            conversation_id="conv-local-trace-route",
            message="Raw local trace response.",
            tool_name="create_recommendation",
            ui_action=AgentUiAction(
                type="show_products",
                target="product_results",
                payload={"recommendation_id": "rec_local_trace"},
            ),
        )

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)

    response = client.post(
        "/api/agent/chat",
        headers={"X-Agent-Local-Model": "gpt-5.4-mini"},
        json={
            "message": "Trace the exact local request values.",
            "conversation_id": "conv-local-trace-route",
            "context": {"page": "home", "filters": {"skin_type": "dry"}},
        },
    )

    assert response.status_code == 200
    assert response.headers["x-agent-local-trace-id"]
    trace_files = list(tmp_path.glob("*.json"))
    assert len(trace_files) == 1
    trace_payload = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert trace_payload["request"]["message"] == "Trace the exact local request values."
    assert trace_payload["final_response"]["payload"]["tool_name"] == "create_recommendation"
    assert trace_payload["route"]["outcome"] == "succeeded"
    assert trace_payload["timings_ms"]["agent_runner_ms"] == 123.4
    assert trace_payload["route"]["requested_model"] == "gpt-5.4-mini"
    assert captured_model_overrides == ["gpt-5.4-mini"]


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


def test_agent_chat_allows_the_same_message_with_a_new_idempotency_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    async def fake_run_openai_agent_chat(*_args, **_kwargs) -> AgentChatResponse:
        nonlocal call_count
        call_count += 1
        return AgentChatResponse(conversation_id="conv-new-key", message="새 요청으로 처리했어요.")

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)
    payload = {"message": "보습 세럼을 추천해 주세요."}

    first = client.post(
        "/api/agent/chat",
        json=payload,
        headers={"Idempotency-Key": "agent-new-key-0001"},
    )
    second = client.post(
        "/api/agent/chat",
        json=payload,
        headers={"Idempotency-Key": "agent-new-key-0002"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count == 2


def test_agent_chat_rate_limit_happens_before_runner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RateLimitedControl:
        def check_rate_limit(self, **_kwargs) -> None:
            raise ApiError(
                429,
                "AGENT_RATE_LIMITED",
                "AI 요청이 잠시 많아요.",
                headers={"Retry-After": "42"},
            )

    async def fail_if_runner_is_called(*_args, **_kwargs) -> AgentChatResponse:
        raise AssertionError("rate limited request must not enter the Agent runner")

    monkeypatch.setattr(
        "app.api.routes.agent.get_default_agent_runtime_control",
        lambda: RateLimitedControl(),
    )
    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fail_if_runner_is_called)

    response = client.post("/api/agent/chat", json={"message": "보습 세럼을 추천해 주세요."})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    assert response.json()["error"]["code"] == "AGENT_RATE_LIMITED"


def test_agent_chat_returns_capacity_error_when_redis_admission_is_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableControl:
        def check_rate_limit(self, **_kwargs) -> None:
            raise ApiError(
                503,
                "AGENT_CAPACITY_UNAVAILABLE",
                "AI 요청 제어 서비스를 사용할 수 없어요.",
            )

    async def fail_if_runner_is_called(*_args, **_kwargs) -> AgentChatResponse:
        raise AssertionError("unavailable admission must not enter the Agent runner")

    monkeypatch.setattr(
        "app.api.routes.agent.get_default_agent_runtime_control",
        lambda: UnavailableControl(),
    )
    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fail_if_runner_is_called)

    response = client.post("/api/agent/chat", json={"message": "보습 세럼을 추천해 주세요."})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_CAPACITY_UNAVAILABLE"


def test_agent_chat_logs_admission_workflow_and_persist_timings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    async def fake_run_openai_agent_chat(*_args, **kwargs) -> AgentChatResponse:
        timing = kwargs["workflow_timing"]
        assert isinstance(timing, AgentWorkflowTiming)
        timing.global_slot_wait_ms = 12.5
        timing.global_slot_acquire_ms = 0.4
        timing.llm_workflow_ms = 34.5
        timing.tool_execution_ms = 7.5
        timing.global_slot_acquired = True
        return AgentChatResponse(conversation_id="conv-timing", message="완료했어요.")

    def capture_event(event: str, **kwargs) -> None:
        if event == "agent_request_completed":
            events.append(kwargs["metadata"])

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", fake_run_openai_agent_chat)
    monkeypatch.setattr("app.api.routes.agent.log_performance_event", capture_event)

    response = client.post("/api/agent/chat", json={"message": "보습 세럼을 추천해 주세요."})

    assert response.status_code == 200
    assert len(events) == 1
    metadata = events[0]
    assert metadata["agent_outcome"] == "succeeded"
    assert metadata["agent_global_slot_acquired"] is True
    assert metadata["agent_global_slot_wait_ms"] == 12.5
    assert metadata["agent_global_slot_acquire_ms"] == 0.4
    assert metadata["agent_llm_workflow_ms"] == 34.5
    assert metadata["agent_tool_execution_ms"] == 7.5
    assert metadata["agent_response_persist_ms"] >= 0
    assert metadata["agent_total_ms"] >= 0


def test_agent_chat_distinguishes_local_queue_rejection_from_global_slot_rejection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, object]] = []

    async def reject_from_local_queue(*_args, **kwargs) -> AgentChatResponse:
        timing = kwargs["workflow_timing"]
        assert isinstance(timing, AgentWorkflowTiming)
        timing.global_slot_acquired = True
        raise ApiError(
            429,
            "AGENT_OPENAI_BUSY",
            "local semaphore is busy",
            headers={"Retry-After": "2"},
        )

    def capture_event(event: str, **kwargs) -> None:
        if event == "agent_request_completed":
            events.append(kwargs["metadata"])

    monkeypatch.setattr("app.api.routes.agent.run_openai_agent_chat", reject_from_local_queue)
    monkeypatch.setattr("app.api.routes.agent.log_performance_event", capture_event)

    response = client.post("/api/agent/chat", json={"message": "recommend a moisturizer"})

    assert response.status_code == 429
    assert len(events) == 1
    assert events[0]["agent_outcome"] == "local_queue_rejected"
    assert events[0]["agent_global_slot_acquired"] is True
    assert events[0]["agent_global_slot_rejected"] is False


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


@pytest.mark.anyio
async def test_agent_trace_adds_only_safe_correlation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agents
    from agents import Runner

    captured_trace: dict[str, object] = {}

    @contextmanager
    def fake_trace(workflow_name: str, **kwargs):
        captured_trace["workflow_name"] = workflow_name
        captured_trace.update(kwargs)
        yield SimpleNamespace()

    async def fake_run(*_args, **_kwargs):
        return SimpleNamespace(final_output="처리했어요.")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(agents, "trace", fake_trace)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )

    metadata = {
        "request_id": "req-trace-1",
        "conversation_id": "conv-trace-1",
        "environment": "test",
        "route": "/api/agent/chat",
        "authenticated": True,
        "agent_release": "test-release",
    }
    response = await run_openai_agent_chat(
        Session(),
        AgentChatRequest(
            message="사용자 메시지 원문은 trace metadata에 넣지 않아요.",
            context=AgentContext(order_code="ord-private", route="/orders/private"),
        ),
        user=SimpleNamespace(id=999, email="private@example.com"),
        trace_metadata=metadata,
    )

    assert response.message == "처리했어요."
    assert captured_trace["workflow_name"] == "mwobarellae_action_agent"
    assert captured_trace["group_id"] == "conv-trace-1"
    assert captured_trace["metadata"] == metadata
    rendered_metadata = str(captured_trace["metadata"])
    assert "private@example.com" not in rendered_metadata
    assert "ord-private" not in rendered_metadata
    assert "사용자 메시지" not in rendered_metadata


@pytest.mark.anyio
async def test_agent_runner_writes_local_raw_input_schema_and_output(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agents
    from agents import Runner

    from app.services.agent_local_trace import create_agent_local_trace

    @contextmanager
    def fake_trace(*_args, **_kwargs):
        yield SimpleNamespace()

    async def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            final_output="Raw runner output.",
            new_items=[],
            raw_responses=[
                SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=100,
                        output_tokens=10,
                        total_tokens=110,
                        input_tokens_details=SimpleNamespace(cached_tokens=20),
                        output_tokens_details=SimpleNamespace(reasoning_tokens=4),
                    )
                )
            ],
            input_guardrail_results=[],
            output_guardrail_results=[],
        )

    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "openai_agent_local_trace_enabled", True)
    monkeypatch.setattr(settings, "openai_agent_local_trace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(agents, "trace", fake_trace)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )

    request = AgentChatRequest(
        message="Show a moisturizing serum for dry skin.",
        context=AgentContext(page="home", filters={"skin_type": "dry"}),
    )
    trace = create_agent_local_trace(
        request_id="req-local-runner",
        route="/api/agent/chat",
        request_payload=request,
        authenticated=False,
    )
    assert trace is not None

    response = await run_openai_agent_chat(
        Session(),
        request,
        local_trace=trace,
        workflow_timing=AgentWorkflowTiming(),
        model_override="gpt-5.4-mini",
    )
    trace.capture_final_response(response.model_dump(mode="json"), model_dump_ms=0.0, json_encode_ms=0.0)
    written_path = trace.finish(outcome="succeeded")

    assert written_path is not None
    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert json.loads(payload["agent"]["input"])["message"] == request.message
    assert payload["agent"]["selected_tool_count"] > 0
    assert payload["agent"]["runner_attempts"][0]["outcome"] == "succeeded"
    assert payload["agent"]["runner_result"]["final_output"] == "Raw runner output."
    assert payload["timings_ms"]["agent_model_and_orchestration_ms"] >= 0
    assert payload["agent"]["model"] == "gpt-5.4-mini"
    assert payload["agent"]["model_source"] == "local_header_override"
    assert payload["agent"]["runner_result"]["usage_breakdown"]["cached_input_tokens"] == 20
    assert payload["agent"]["runner_result"]["cost_estimate"]["estimated_cost_usd"] == 0.0001065


@pytest.mark.anyio
async def test_global_queue_wait_does_not_consume_agent_execution_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import Runner

    class DelayedGlobalControl:
        @asynccontextmanager
        async def acquire_global_slot(self):
            await asyncio.sleep(0.03)
            yield AgentGlobalSlotLease(
                slot_number=1,
                owner_token="delayed-owner",
                wait_ms=30.0,
                acquire_ms=0.2,
            )

    async def fake_run(*_args, **_kwargs):
        return SimpleNamespace(final_output="대기 뒤에 정상 실행했어요.")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_agent_timeout_seconds", 0.02)
    monkeypatch.setattr(settings, "openai_agent_max_retries", 0)
    monkeypatch.setattr(Runner, "run", fake_run)
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CONCURRENCY_LIMITER",
        _OpenAIConcurrencyLimiter(max_concurrency=3, queue_timeout_seconds=0.1),
    )
    monkeypatch.setattr(
        "app.services.agent_openai_runner._OPENAI_CIRCUIT_BREAKER",
        _OpenAICircuitBreaker(),
    )

    timing = AgentWorkflowTiming()
    response = await run_openai_agent_chat(
        Session(),
        AgentChatRequest(message="보습 세럼을 추천해 주세요."),
        runtime_control=DelayedGlobalControl(),
        workflow_timing=timing,
    )

    assert response.message == "대기 뒤에 정상 실행했어요."
    assert timing.global_slot_acquired is True
    assert timing.global_slot_wait_ms >= 25
    assert timing.llm_workflow_ms < 20
