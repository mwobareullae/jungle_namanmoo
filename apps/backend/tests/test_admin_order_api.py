from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.session import get_db
from app.main import app


ADMIN_EMAIL = "admin-order@example.com"


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
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


def _signup(client: TestClient) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": ADMIN_EMAIL,
            "password": "password123",
            "nickname": "admin-order",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200


def _promote_to_admin(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def test_admin_orders_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/orders").status_code == 401


def test_admin_orders_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.get("/api/admin/orders").status_code == 403


def test_admin_orders_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    response = client.get("/api/admin/orders")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "summary", "next_cursor"}
    assert set(body["summary"].keys()) == {
        "pending_payment_count",
        "preparing_shipment_count",
        "cancel_requested_count",
        "reserved_quantity_total",
    }
    assert body["items"] == []  # 빈 DB


def test_admin_orders_rejects_invalid_status(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    assert client.get("/api/admin/orders", params={"order_status": "NOPE"}).status_code == 400
