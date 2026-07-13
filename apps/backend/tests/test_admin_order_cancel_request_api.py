"""관리자 취소 요청 목록·상세 조회 API 계약 테스트 (M1.5-B)."""

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
from app.db.models.commerce import Order, OrderCancelRequest, OrderItem, Payment
from app.db.session import get_db
from app.main import app


ADMIN_EMAIL = "admin-cancelreq@example.com"


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
            "nickname": "admin-cancelreq",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200


def _promote_to_admin(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def _seed_cancel_request(db_engine: Engine) -> str:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        buyer = User(email="buyer-cancelreq@example.com", display_name="구매자", status="ACTIVE", role="USER")
        session.add(buyer)
        session.flush()
        order = Order(
            order_code="ord_api_cancelreq",
            user_id=buyer.id,
            idempotency_key="key_api_cancelreq",
            status="CANCEL_REQUESTED",
            subtotal_amount=10000,
            total_amount=10000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            ordered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=1,
                seller_id=1,
                product_name_snapshot="상품A",
                brand_name_snapshot="브랜드",
                seller_name_snapshot="자사",
                unit_price=10000,
                quantity=1,
                line_subtotal=10000,
                line_discount_amount=0,
                line_total=10000,
                currency="KRW",
                status="ORDERED",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Payment(
                payment_code="pay_api_cancelreq",
                order_id=order.id,
                provider="MOCK",
                status="APPROVED",
                amount=10000,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
        request = OrderCancelRequest(
            request_code="ocr_api_cancelreq",
            order_id=order.id,
            user_id=buyer.id,
            status="REQUESTED",
            reason_code="CHANGE_OF_MIND",
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(request)
        session.commit()
    return "ocr_api_cancelreq"


def test_list_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/order-cancel-requests").status_code == 401


def test_list_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.get("/api/admin/order-cancel-requests").status_code == 403


def test_list_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    _seed_cancel_request(db_engine)

    response = client.get("/api/admin/order-cancel-requests")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "next_cursor"}
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["request_code"] == "ocr_api_cancelreq"
    assert item["order_code"] == "ord_api_cancelreq"
    assert item["status"] == "REQUESTED"
    assert item["available_actions"] == ["APPROVE", "REJECT"]


def test_list_rejects_invalid_status_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-cancel-requests", params={"status": "NOT_A_STATUS"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CANCEL_REQUEST_STATUS"


def test_list_rejects_invalid_cursor_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-cancel-requests", params={"cursor": "not-a-number"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_list_rejects_invalid_limit_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-cancel-requests", params={"limit": 0})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_LIMIT"


def test_detail_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/order-cancel-requests/ocr_anything").status_code == 401


def test_detail_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.get("/api/admin/order-cancel-requests/ocr_anything").status_code == 403


def test_detail_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    _seed_cancel_request(db_engine)

    response = client.get("/api/admin/order-cancel-requests/ocr_api_cancelreq")

    assert response.status_code == 200
    body = response.json()
    assert body["request_code"] == "ocr_api_cancelreq"
    assert body["order_status"] == "CANCEL_REQUESTED"
    assert body["payment_status"] == "APPROVED"
    assert body["payment_provider"] == "MOCK"
    assert body["product_summary"] == "상품A"


def test_detail_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-cancel-requests/ocr_does_not_exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CANCEL_REQUEST_NOT_FOUND"
