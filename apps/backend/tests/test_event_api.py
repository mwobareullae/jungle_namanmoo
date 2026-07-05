from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.events import EventLog
from app.db.session import get_db
from app.main import app
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


def test_event_api_accepts_unknown_event_name_and_metadata(
    client: TestClient,
    db_engine: Engine,
) -> None:
    response = client.post(
        "/api/events",
        json={
            "event_name": "frontend.home.hero_clicked",
            "anonymous_user_id": "anon_test",
            "session_id": "session_test",
            "product_id": "prod_001",
            "metadata": {
                "section_id": "home_hero",
                "latency_ms": 123,
            },
        },
        headers={"x-request-id": "request_test"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["event_id"]
    assert data["event_name"] == "frontend.home.hero_clicked"
    assert data["official_event"] is False
    assert data["duplicate"] is False

    with Session(db_engine) as session:
        event = session.execute(select(EventLog)).scalar_one()

    assert event.anonymous_user_id == "anon_test"
    assert event.session_id == "session_test"
    assert event.request_id == "request_test"
    assert event.product_id == "prod_001"
    assert event.metadata_json["section_id"] == "home_hero"


def test_event_api_deduplicates_by_event_id(
    client: TestClient,
    db_engine: Engine,
) -> None:
    payload = {
        "event_id": "evt_same",
        "event_name": "product_viewed",
        "product_id": "prod_001",
    }

    first_response = client.post("/api/events", json=payload)
    second_response = client.post("/api/events", json={**payload, "product_id": "prod_002"})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["duplicate"] is False
    assert second_response.json()["duplicate"] is True

    with Session(db_engine) as session:
        events = session.execute(select(EventLog)).scalars().all()

    assert len(events) == 1
    assert events[0].product_id == "prod_001"


def test_event_api_sets_logged_in_user_from_session(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client)

    response = client.post(
        "/api/events",
        json={
            "event_name": "cart_added",
            "cart_id": 1,
            "metadata": {"quantity": 2},
        },
    )

    assert response.status_code == 200
    assert response.json()["official_event"] is True

    with Session(db_engine) as session:
        event = session.execute(select(EventLog)).scalar_one()

    assert event.user_id is not None
    assert event.event_name == "cart_added"


def test_event_api_rejects_sensitive_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/events",
        json={
            "event_name": "product_viewed",
            "metadata": {"email": "user@example.com"},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EVENT_METADATA_CONTAINS_SENSITIVE_DATA"


def test_event_batch_api_stores_multiple_events(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/events/batch",
        json={
            "events": [
                {
                    "event_id": "batch_evt_1",
                    "event_name": "recommendation_product_impression",
                    "recommendation_id": "rec_001",
                    "product_id": "prod_001",
                    "rank": 1,
                },
                {
                    "event_id": "batch_evt_2",
                    "event_name": "recommendation_product_impression",
                    "recommendation_id": "rec_001",
                    "product_id": "prod_002",
                    "rank": 2,
                },
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["accepted_count"] == 2
    assert data["duplicate_count"] == 0

    with Session(db_engine) as session:
        events = session.execute(select(EventLog).order_by(EventLog.rank)).scalars().all()

    assert [event.product_id for event in events] == ["prod_001", "prod_002"]


def _signup(client: TestClient) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "event-user@example.com",
            "password": "password123",
            "nickname": "event-user",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200
