"""관리자 클레임 목록·상세 조회 API 계약 테스트 (M1.5-B)."""

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
from app.db.models.commerce import Inventory, Order, OrderClaim, OrderClaimEvent, OrderClaimItem, OrderItem, Payment
from app.db.session import get_db
from app.main import app


ADMIN_EMAIL = "admin-claim@example.com"


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
            "nickname": "admin-claim",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200


def _promote_to_admin(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def _seed_claim(db_engine: Engine) -> str:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        buyer = User(email="buyer-claim@example.com", display_name="구매자", status="ACTIVE", role="USER")
        session.add(buyer)
        session.flush()
        order = Order(
            order_code="ord_api_claim",
            user_id=buyer.id,
            idempotency_key="key_api_claim",
            status="DELIVERED",
            subtotal_amount=10000,
            total_amount=10000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            ordered_at=now,
            delivered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        order_item = OrderItem(
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
            status="DELIVERED",
            created_at=now,
            updated_at=now,
        )
        session.add(order_item)
        session.flush()
        claim = OrderClaim(
            claim_code="clm_api_claim",
            order_id=order.id,
            user_id=buyer.id,
            claim_type="REFUND",
            status="REQUESTED",
            reason_code="DAMAGED",
            refund_amount=10000,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(claim)
        session.flush()
        session.add(
            OrderClaimItem(
                claim_id=claim.id,
                order_item_id=order_item.id,
                quantity=1,
                resolution="REFUND",
                created_at=now,
            )
        )
        session.add(
            OrderClaimEvent(
                claim_id=claim.id,
                from_status=None,
                to_status="REQUESTED",
                actor_type="USER",
                actor_id=buyer.id,
                reason="DAMAGED",
                created_at=now,
            )
        )
        session.commit()
    return "clm_api_claim"


def _seed_claim_for_decision(
    db_engine: Engine, *, suffix: str, status: str = "REQUESTED", claim_type: str = "REFUND"
) -> str:
    now = datetime.now(UTC)
    claim_code = f"clm_api_decision_{suffix}"
    with Session(db_engine) as session:
        buyer = User(email=f"buyer-claim-{suffix}@example.com", display_name=None, status="ACTIVE", role="USER")
        session.add(buyer)
        session.flush()
        order = Order(
            order_code=f"ord_api_decision_{suffix}",
            user_id=buyer.id,
            idempotency_key=f"key_api_decision_{suffix}",
            status="DELIVERED",
            subtotal_amount=10000,
            total_amount=10000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            ordered_at=now,
            delivered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        order_item = OrderItem(
            order_id=order.id,
            product_id=hash(suffix) % 100000 + 1,
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
            status="DELIVERED",
            created_at=now,
            updated_at=now,
        )
        session.add(order_item)
        session.add(
            Inventory(
                product_id=hash(suffix) % 100000 + 1,
                stock_quantity=10,
                reserved_quantity=0,
                safety_stock=0,
                sales_status="ON_SALE",
                inventory_source="TEST",
                updated_at=now,
            )
        )
        session.add(
            Payment(
                payment_code=f"pay_api_decision_{suffix}",
                order_id=order.id,
                provider="MOCK",
                status="APPROVED",
                amount=10000,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        resolution = "EXCHANGE" if claim_type == "EXCHANGE" else "REFUND"
        claim = OrderClaim(
            claim_code=claim_code,
            order_id=order.id,
            user_id=buyer.id,
            claim_type=claim_type,
            status=status,
            reason_code="DAMAGED",
            refund_amount=10000 if claim_type != "EXCHANGE" else None,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(claim)
        session.flush()
        session.add(
            OrderClaimItem(
                claim_id=claim.id, order_item_id=order_item.id, quantity=1, resolution=resolution, created_at=now
            )
        )
        session.add(
            OrderClaimEvent(
                claim_id=claim.id,
                from_status=None,
                to_status="REQUESTED",
                actor_type="USER",
                actor_id=buyer.id,
                reason="DAMAGED",
                created_at=now,
            )
        )
        session.commit()
    return claim_code


def test_list_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/order-claims").status_code == 401


def test_list_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.get("/api/admin/order-claims").status_code == 403


def test_list_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    _seed_claim(db_engine)

    response = client.get("/api/admin/order-claims")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "page", "page_size", "total_count"}
    assert body["total_count"] == 1
    item = body["items"][0]
    assert item["claim_code"] == "clm_api_claim"
    assert item["order_code"] == "ord_api_claim"
    assert item["status"] == "REQUESTED"
    assert item["available_actions"] == ["APPROVE", "REJECT"]


def test_list_rejects_invalid_status_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-claims", params={"status": "NOT_A_STATUS"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CLAIM_STATUS"


def test_list_rejects_invalid_claim_type_query(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-claims", params={"claim_type": "NOT_A_TYPE"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CLAIM_TYPE"


def test_detail_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/order-claims/clm_anything").status_code == 401


def test_detail_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.get("/api/admin/order-claims/clm_anything").status_code == 403


def test_detail_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    _seed_claim(db_engine)

    response = client.get("/api/admin/order-claims/clm_api_claim")

    assert response.status_code == 200
    body = response.json()
    assert body["claim_code"] == "clm_api_claim"
    assert body["order_status"] == "DELIVERED"
    assert body["payment_provider"] is None  # 시드에 Payment 레코드를 만들지 않은 경우
    assert body["product_summary"] == "상품A"
    assert len(body["items"]) == 1
    assert body["items"][0]["resolution"] == "REFUND"
    assert len(body["events"]) == 1
    assert body["events"][0]["to_status"] == "REQUESTED"


def test_detail_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.get("/api/admin/order-claims/clm_does_not_exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"


def test_approve_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/admin/order-claims/clm_anything/approve").status_code == 401


def test_approve_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.post("/api/admin/order-claims/clm_anything/approve").status_code == 403


def test_approve_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="approve")

    response = client.post(f"/api/admin/order-claims/{claim_code}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["available_actions"] == ["START"]


def test_approve_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.post("/api/admin/order-claims/clm_does_not_exist/approve")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"


def test_reject_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/admin/order-claims/clm_anything/reject", json={"rejection_reason": "사유"})
    assert response.status_code == 401


def test_reject_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    response = client.post("/api/admin/order-claims/clm_anything/reject", json={"rejection_reason": "사유"})
    assert response.status_code == 403


def test_reject_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="reject")

    response = client.post(
        f"/api/admin/order-claims/{claim_code}/reject",
        json={"rejection_reason": "사진상 파손 확인 안 됨"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["available_actions"] == []


def test_reject_requires_body(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="reject-missing-body")

    response = client.post(f"/api/admin/order-claims/{claim_code}/reject", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_reject_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.post(
        "/api/admin/order-claims/clm_does_not_exist/reject",
        json={"rejection_reason": "사유"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"


def test_start_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/admin/order-claims/clm_anything/start").status_code == 401


def test_start_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.post("/api/admin/order-claims/clm_anything/start").status_code == 403


def test_start_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="start", status="APPROVED")

    response = client.post(f"/api/admin/order-claims/{claim_code}/start")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["available_actions"] == ["COMPLETE"]


def test_start_rejects_requested_claim(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="start-not-approved", status="REQUESTED")

    response = client.post(f"/api/admin/order-claims/{claim_code}/start")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLAIM_NOT_APPROVED"


def test_start_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.post("/api/admin/order-claims/clm_does_not_exist/start")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"


def test_complete_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/admin/order-claims/clm_anything/complete", json={"restock": False})
    assert response.status_code == 401


def test_complete_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    response = client.post("/api/admin/order-claims/clm_anything/complete", json={"restock": False})
    assert response.status_code == 403


def test_complete_refund_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="complete", status="IN_PROGRESS", claim_type="REFUND")

    response = client.post(f"/api/admin/order-claims/{claim_code}/complete", json={"restock": False})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["available_actions"] == []
    assert body["completed_at"] is not None


def test_complete_exchange_returns_contract_for_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(
        db_engine, suffix="complete-exchange", status="IN_PROGRESS", claim_type="EXCHANGE"
    )

    response = client.post(f"/api/admin/order-claims/{claim_code}/complete", json={"restock": False})

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_complete_rejects_not_in_progress_claim(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="complete-not-in-progress", status="APPROVED")

    response = client.post(f"/api/admin/order-claims/{claim_code}/complete", json={"restock": False})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLAIM_NOT_IN_PROGRESS"


def test_complete_requires_body(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    claim_code = _seed_claim_for_decision(db_engine, suffix="complete-missing-body", status="IN_PROGRESS")

    response = client.post(f"/api/admin/order-claims/{claim_code}/complete", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_complete_not_found_returns_404(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)

    response = client.post("/api/admin/order-claims/clm_does_not_exist/complete", json={"restock": False})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"
