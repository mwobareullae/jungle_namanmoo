from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas.agent import AgentChatResponse, AgentUiAction
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


def test_agent_chat_route_returns_runner_response(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_openai_agent_chat(*args, **kwargs) -> AgentChatResponse:
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
