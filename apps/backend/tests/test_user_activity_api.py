from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.commerce import RecentView, Wishlist
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


def _signup(client: TestClient, *, email: str, nickname: str) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200


def test_wishlist_requires_login(client: TestClient) -> None:
    response = client.get("/api/me/wishlist")
    assert response.status_code == 401


def test_wishlist_add_list_delete_is_idempotent_and_uses_storage_key(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="wishlist@example.com", nickname="찜유저")

    first_add = client.post("/api/me/wishlist", json={"product_id": "prod_001"})
    second_add = client.post("/api/me/wishlist", json={"product_id": "prod_001"})
    list_response = client.get("/api/me/wishlist")
    first_delete = client.delete("/api/me/wishlist/prod_001")
    second_delete = client.delete("/api/me/wishlist/prod_001")
    after_delete = client.get("/api/me/wishlist")

    with Session(db_engine) as session:
        wishlist_count = len(session.execute(select(Wishlist)).scalars().all())

    assert first_add.status_code == 200
    assert second_add.status_code == 200
    assert first_add.json()["id"] == second_add.json()["id"]
    assert list_response.status_code == 200
    assert [item["product_id"] for item in list_response.json()["items"]] == ["prod_001"]
    product = list_response.json()["items"][0]["product"]
    assert product["thumbnail_url"].startswith("products/")
    assert not product["thumbnail_url"].startswith("http")
    assert first_delete.status_code == 200
    assert first_delete.json() == {"success": True}
    assert second_delete.status_code == 200
    assert second_delete.json() == {"success": True}
    assert after_delete.json()["items"] == []
    assert wishlist_count == 0


def test_user_activity_records_behavior_events(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="activity-events@example.com", nickname="행동로그")

    headers = {
        "X-MWBL-Anonymous-User-Id": "anon_activity",
        "X-MWBL-Session-Id": "session_activity",
        "x-request-id": "request_activity",
    }
    wishlist_add = client.post(
        "/api/me/wishlist",
        json={"product_id": "prod_001"},
        headers=headers,
    )
    recent_view = client.post(
        "/api/me/recent",
        json={"product_id": "prod_002"},
        headers=headers,
    )
    wishlist_remove = client.delete("/api/me/wishlist/prod_001", headers=headers)

    assert wishlist_add.status_code == 200
    assert recent_view.status_code == 200
    assert wishlist_remove.status_code == 200

    with Session(db_engine) as session:
        events = session.execute(select(EventLog).order_by(EventLog.id)).scalars().all()

    assert [event.event_name for event in events] == [
        "wishlist_added",
        "recent_product_viewed",
        "wishlist_removed",
    ]
    assert [event.product_id for event in events] == ["prod_001", "prod_002", "prod_001"]
    assert {event.anonymous_user_id for event in events} == {"anon_activity"}
    assert {event.session_id for event in events} == {"session_activity"}
    assert {event.request_id for event in events} == {"request_activity"}
    assert all(event.user_id is not None for event in events)


def test_wishlist_is_owned_by_current_user(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="first@example.com", nickname="첫번째")
    assert client.post("/api/me/wishlist", json={"product_id": "prod_001"}).status_code == 200

    _signup(client, email="second@example.com", nickname="두번째")
    second_user_response = client.get("/api/me/wishlist")

    with Session(db_engine) as session:
        wishlist_count = len(session.execute(select(Wishlist)).scalars().all())

    assert second_user_response.status_code == 200
    assert second_user_response.json()["items"] == []
    assert wishlist_count == 1


def test_recent_view_upserts_and_orders_by_viewed_at(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="recent@example.com", nickname="최근유저")

    first_view = client.post("/api/me/recent", json={"product_id": "prod_001"})
    second_product_view = client.post("/api/me/recent", json={"product_id": "prod_002"})
    second_view = client.post("/api/me/recent", json={"product_id": "prod_001"})
    list_response = client.get("/api/me/recent")

    with Session(db_engine) as session:
        recent_rows = session.execute(select(RecentView)).scalars().all()

    assert first_view.status_code == 200
    assert second_product_view.status_code == 200
    assert second_view.status_code == 200
    assert first_view.json()["id"] == second_view.json()["id"]
    assert [item["product_id"] for item in list_response.json()["items"]] == ["prod_001", "prod_002"]
    assert len(recent_rows) == 2


def test_recent_view_delete_is_idempotent(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="recent-delete@example.com", nickname="최근삭제")
    assert client.post("/api/me/recent", json={"product_id": "prod_001"}).status_code == 200

    first_delete = client.delete("/api/me/recent/prod_001")
    second_delete = client.delete("/api/me/recent/prod_001")
    list_response = client.get("/api/me/recent")

    with Session(db_engine) as session:
        recent_count = len(session.execute(select(RecentView)).scalars().all())

    assert first_delete.status_code == 200
    assert first_delete.json() == {"success": True}
    assert second_delete.status_code == 200
    assert second_delete.json() == {"success": True}
    assert list_response.json()["items"] == []
    assert recent_count == 0


def test_user_activity_rejects_missing_product(client: TestClient) -> None:
    _signup(client, email="missing-product@example.com", nickname="없는상품")

    wishlist_response = client.post("/api/me/wishlist", json={"product_id": "missing"})
    recent_response = client.post("/api/me/recent", json={"product_id": "missing"})

    assert wishlist_response.status_code == 404
    assert wishlist_response.json()["error"]["code"] == "NOT_FOUND"
    assert recent_response.status_code == 404
    assert recent_response.json()["error"]["code"] == "NOT_FOUND"
