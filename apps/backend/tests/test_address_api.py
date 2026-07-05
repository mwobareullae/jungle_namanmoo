from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.commerce import UserAddress
from app.db.session import get_db
from app.main import app


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


def test_addresses_require_login(client: TestClient) -> None:
    response = client.get("/api/me/addresses")

    assert response.status_code == 401


def test_create_first_address_sets_default_and_trims_values(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="address-first@example.com", nickname="address-first")

    response = client.post(
        "/api/me/addresses",
        json={
            "recipient_name": "  Kim Wonwoo  ",
            "phone": " 01012345678 ",
            "postal_code": " 12345 ",
            "address1": " Seoul ",
            "address2": " 101 ",
            "delivery_memo": " Leave at door ",
            "is_default": False,
        },
    )
    list_response = client.get("/api/me/addresses")

    with Session(db_engine) as session:
        row = session.execute(select(UserAddress)).scalar_one()

    assert response.status_code == 200
    data = response.json()
    assert data["recipient_name"] == "Kim Wonwoo"
    assert data["phone"] == "01012345678"
    assert data["postal_code"] == "12345"
    assert data["address1"] == "Seoul"
    assert data["address2"] == "101"
    assert data["delivery_memo"] == "Leave at door"
    assert data["is_default"] is True
    assert list_response.json()["items"][0]["id"] == data["id"]
    assert row.is_default is True


def test_creating_new_default_unsets_previous_default(client: TestClient) -> None:
    _signup(client, email="address-default@example.com", nickname="address-default")
    first_id = _create_address(client, recipient_name="First", is_default=True)["id"]
    second_id = _create_address(client, recipient_name="Second", is_default=True)["id"]

    response = client.get("/api/me/addresses")

    items = response.json()["items"]
    assert response.status_code == 200
    assert [item["id"] for item in items] == [second_id, first_id]
    assert items[0]["is_default"] is True
    assert items[1]["is_default"] is False


def test_update_address_can_clear_optional_values_and_change_default(client: TestClient) -> None:
    _signup(client, email="address-update@example.com", nickname="address-update")
    first_id = _create_address(client, recipient_name="First", is_default=True)["id"]
    second_id = _create_address(
        client,
        recipient_name="Second",
        address2="Before clear",
        delivery_memo="Before clear",
        is_default=False,
    )["id"]

    response = client.patch(
        f"/api/me/addresses/{second_id}",
        json={
            "recipient_name": "Updated",
            "address2": None,
            "delivery_memo": None,
            "is_default": True,
        },
    )
    list_response = client.get("/api/me/addresses")

    assert response.status_code == 200
    data = response.json()
    assert data["recipient_name"] == "Updated"
    assert data["address2"] is None
    assert data["delivery_memo"] is None
    assert data["is_default"] is True
    items_by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert items_by_id[second_id]["is_default"] is True
    assert items_by_id[first_id]["is_default"] is False


def test_update_default_false_keeps_one_default_address(client: TestClient) -> None:
    _signup(client, email="address-keep-default@example.com", nickname="address-keep-default")
    first_id = _create_address(client, recipient_name="First", is_default=True)["id"]

    single_response = client.patch(f"/api/me/addresses/{first_id}", json={"is_default": False})
    second_id = _create_address(client, recipient_name="Second", is_default=False)["id"]
    unset_first_response = client.patch(f"/api/me/addresses/{first_id}", json={"is_default": False})
    list_response = client.get("/api/me/addresses")

    items_by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert single_response.status_code == 200
    assert single_response.json()["is_default"] is True
    assert unset_first_response.status_code == 200
    assert items_by_id[first_id]["is_default"] is False
    assert items_by_id[second_id]["is_default"] is True


def test_delete_default_address_promotes_latest_remaining_address(client: TestClient) -> None:
    _signup(client, email="address-delete@example.com", nickname="address-delete")
    first_id = _create_address(client, recipient_name="First", is_default=True)["id"]
    second_id = _create_address(client, recipient_name="Second", is_default=True)["id"]

    delete_response = client.delete(f"/api/me/addresses/{second_id}")
    list_response = client.get("/api/me/addresses")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == first_id
    assert items[0]["is_default"] is True


def test_address_ownership_is_enforced(client: TestClient) -> None:
    _signup(client, email="address-owner@example.com", nickname="address-owner")
    owned_by_first_user = _create_address(client, recipient_name="Owner")["id"]

    _signup(client, email="address-other@example.com", nickname="address-other")
    list_response = client.get("/api/me/addresses")
    patch_response = client.patch(
        f"/api/me/addresses/{owned_by_first_user}",
        json={"recipient_name": "Hacked"},
    )
    delete_response = client.delete(f"/api/me/addresses/{owned_by_first_user}")

    assert list_response.status_code == 200
    assert list_response.json()["items"] == []
    assert patch_response.status_code == 404
    assert patch_response.json()["error"]["code"] == "ADDRESS_NOT_FOUND"
    assert delete_response.status_code == 404
    assert delete_response.json()["error"]["code"] == "ADDRESS_NOT_FOUND"


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


def _create_address(
    client: TestClient,
    *,
    recipient_name: str,
    address2: str | None = None,
    delivery_memo: str | None = None,
    is_default: bool = False,
) -> dict:
    response = client.post(
        "/api/me/addresses",
        json={
            "recipient_name": recipient_name,
            "phone": "01012345678",
            "postal_code": "12345",
            "address1": "Seoul",
            "address2": address2,
            "delivery_memo": delivery_memo,
            "is_default": is_default,
        },
    )
    assert response.status_code == 200
    return response.json()
