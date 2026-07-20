from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderShippingAddress, UserAddress
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


@pytest.mark.parametrize(
    ("phone", "expected_phone"),
    [
        ("010-123-4567", "0101234567"),
        ("010 1234 5678", "01012345678"),
    ],
)
def test_create_address_normalizes_formatted_phone(
    client: TestClient,
    phone: str,
    expected_phone: str,
) -> None:
    _signup(client, email="address-phone-normalize@example.com", nickname="address-phone-normalize")

    response = client.post(
        "/api/me/addresses",
        json={
            "recipient_name": "배송 받는 사람",
            "phone": phone,
            "postal_code": "12345",
            "address1": "Seoul",
            "address2": "101",
        },
    )

    assert response.status_code == 200
    assert response.json()["phone"] == expected_phone


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipient_name", "Kim123"),
        ("phone", "010-1234-56"),
        ("postal_code", "1234a"),
        ("address2", "   "),
    ],
)
def test_create_address_rejects_invalid_required_values(client: TestClient, field: str, value: str) -> None:
    _signup(client, email=f"address-invalid-{field}@example.com", nickname=f"address-invalid-{field}")
    payload = {
        "recipient_name": "Recipient",
        "phone": "01012345678",
        "postal_code": "12345",
        "address1": "Seoul",
        "address2": "101",
    }
    payload[field] = value

    response = client.post("/api/me/addresses", json=payload)

    assert response.status_code == 400


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


def test_update_address_can_clear_delivery_memo_and_change_default(client: TestClient) -> None:
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
            "delivery_memo": None,
            "is_default": True,
        },
    )
    list_response = client.get("/api/me/addresses")

    assert response.status_code == 200
    data = response.json()
    assert data["recipient_name"] == "Updated"
    assert data["address2"] == "Before clear"
    assert data["delivery_memo"] is None
    assert data["is_default"] is True
    items_by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert items_by_id[second_id]["is_default"] is True
    assert items_by_id[first_id]["is_default"] is False


def test_update_address_rejects_empty_detail_address(client: TestClient) -> None:
    _signup(client, email="address-detail-required@example.com", nickname="address-detail-required")
    address_id = _create_address(client, recipient_name="Recipient")["id"]

    response = client.patch(f"/api/me/addresses/{address_id}", json={"address2": None})

    assert response.status_code == 400


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


def test_delete_address_used_by_order_detaches_order_snapshot(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="address-order-delete@example.com", nickname="address-order-delete")
    address_id = _create_address(client, recipient_name="Ordered", is_default=True)["id"]

    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == "address-order-delete@example.com")).scalar_one()
        now = datetime.now(UTC)
        order = Order(
            order_code="ord_address_delete_001",
            user_id=user.id,
            idempotency_key="address-delete-order",
            status="PENDING_PAYMENT",
            subtotal_amount=10000,
            shipping_fee=3000,
            discount_amount=0,
            total_amount=13000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            ordered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        order_id = order.id
        session.add(
            OrderShippingAddress(
                order_id=order_id,
                user_address_id=address_id,
                recipient_name="Ordered",
                phone="01012345678",
                postal_code="12345",
                address1="Seoul",
                address2="101",
                delivery_memo="Leave at door",
                created_at=now,
            )
        )
        session.commit()

    delete_response = client.delete(f"/api/me/addresses/{address_id}")
    list_response = client.get("/api/me/addresses")

    with Session(db_engine) as session:
        deleted_address = session.execute(select(UserAddress).where(UserAddress.id == address_id)).scalar_one_or_none()
        shipping_address = session.execute(
            select(OrderShippingAddress).where(OrderShippingAddress.order_id == order_id)
        ).scalar_one()

    assert delete_response.status_code == 200
    assert delete_response.json() == {"success": True}
    assert list_response.json()["items"] == []
    assert deleted_address is None
    assert shipping_address.user_address_id is None
    assert shipping_address.recipient_name == "Ordered"
    assert shipping_address.address1 == "Seoul"


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
    address2: str = "101",
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
