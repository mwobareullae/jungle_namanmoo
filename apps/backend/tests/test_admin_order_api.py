import json
import logging
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.logging import PERFORMANCE_LOGGER_NAME
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderFulfillmentEvent, OrderItem, Payment
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
    assert set(body.keys()) == {"items", "summary", "pagination"}
    assert set(body["summary"].keys()) == {
        "pending_payment_count",
        "preparing_shipment_count",
        "shipped_count",
        "cancel_requested_count",
        "reserved_quantity_total",
    }
    assert set(body["pagination"].keys()) == {
        "page",
        "page_size",
        "total_items",
        "total_pages",
        "has_next",
        "has_prev",
    }
    assert body["items"] == []  # 빈 DB


def test_admin_orders_rejects_invalid_status(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)
    assert client.get("/api/admin/orders", params={"order_status": "NOPE"}).status_code == 400


# ---------------------------------------------------------------------------
# 배송 상태 전이 라우터 (M1.5-A Chunk 4)
# ---------------------------------------------------------------------------


def _authed_admin(client: TestClient, db_engine: Engine) -> None:
    _signup(client)
    _promote_to_admin(db_engine)


def _seed_order(
    db_engine: Engine,
    *,
    order_code: str,
    order_status: str,
    payment_status: str | None,
    item_count: int = 1,
    stored_item_count: int | None = None,
    item_status: str = "ORDERED",
) -> None:
    """관리자(ADMIN_EMAIL)를 주문자로 하는 주문·아이템·결제를 직접 시드한다.

    stored_item_count 를 item_count 와 다르게 주면 Order.item_count 와 실제
    OrderItem 행 수가 어긋난 상태(ORDER_ITEMS_INCONSISTENT 재현용)를 만들 수 있다.
    """
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        admin_user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        order = Order(
            order_code=order_code,
            user_id=admin_user.id,
            idempotency_key=f"key_{order_code}",
            status=order_status,
            subtotal_amount=1000,
            total_amount=1000,
            currency="KRW",
            item_count=stored_item_count if stored_item_count is not None else item_count,
            total_quantity=item_count,
            ordered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()
        for idx in range(item_count):
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=idx + 1,
                    seller_id=1,
                    product_name_snapshot=f"상품{idx + 1}",
                    brand_name_snapshot="브랜드",
                    seller_name_snapshot="자사",
                    unit_price=1000,
                    quantity=1,
                    line_subtotal=1000,
                    line_discount_amount=0,
                    line_total=1000,
                    currency="KRW",
                    status=item_status,
                    created_at=now,
                    updated_at=now,
                )
            )
        if payment_status is not None:
            session.add(
                Payment(
                    payment_code=f"pay_{order_code}",
                    order_id=order.id,
                    provider="MOCK",
                    status=payment_status,
                    amount=1000,
                    currency="KRW",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()


def test_admin_orders_exposes_ordered_at(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    _seed_order(
        db_engine,
        order_code="ord_api_ordered_at",
        order_status="PAID",
        payment_status="APPROVED",
    )

    response = client.get("/api/admin/orders")

    assert response.status_code == 200
    assert response.json()["items"][0]["ordered_at"] is not None


def _load_order_state(db_engine: Engine, order_code: str) -> tuple[str, list[str]]:
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == order_code)).scalar_one()
        item_statuses = list(
            session.execute(
                select(OrderItem.status).where(OrderItem.order_id == order.id)
            ).scalars()
        )
        return order.status, item_statuses


@pytest.mark.parametrize(
    ("path", "start_status", "start_item_status", "expected_status", "expected_actions"),
    [
        ("prepare", "PAID", "ORDERED", "PREPARING_SHIPMENT", ["START_SHIPMENT"]),
        ("dispatch", "PREPARING_SHIPMENT", "PREPARING_SHIPMENT", "SHIPPED", ["COMPLETE_DELIVERY"]),
        ("deliver", "SHIPPED", "SHIPPED", "DELIVERED", []),
    ],
)
def test_shipment_action_transitions_and_persists(
    client: TestClient,
    db_engine: Engine,
    path: str,
    start_status: str,
    start_item_status: str,
    expected_status: str,
    expected_actions: list[str],
) -> None:
    _authed_admin(client, db_engine)
    order_code = f"ord_api_{path}"
    _seed_order(
        db_engine,
        order_code=order_code,
        order_status=start_status,
        item_status=start_item_status,
        payment_status="APPROVED",
        item_count=2,
    )

    response = client.post(f"/api/admin/orders/{order_code}/ship/{path}")

    assert response.status_code == 200
    body = response.json()
    assert body["order_code"] == order_code
    assert body["order_status"] == expected_status
    assert body["available_actions"] == expected_actions

    persisted_status, item_statuses = _load_order_state(db_engine, order_code)
    assert persisted_status == expected_status
    assert item_statuses == [expected_status] * 2


def test_shipment_action_response_exposes_shipped_and_delivered_at(
    client: TestClient, db_engine: Engine
) -> None:
    _authed_admin(client, db_engine)
    order_code = "ord_api_shipment_timestamps"
    _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="APPROVED")

    prepare_body = client.post(f"/api/admin/orders/{order_code}/ship/prepare").json()
    assert prepare_body["shipped_at"] is None
    assert prepare_body["delivered_at"] is None

    dispatch_body = client.post(f"/api/admin/orders/{order_code}/ship/dispatch").json()
    assert dispatch_body["shipped_at"] is not None
    assert dispatch_body["delivered_at"] is None

    deliver_body = client.post(f"/api/admin/orders/{order_code}/ship/deliver").json()
    assert deliver_body["shipped_at"] is not None
    assert deliver_body["delivered_at"] is not None


def test_shipment_action_idempotent_replay_returns_200(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    order_code = "ord_api_idempotent"
    _seed_order(
        db_engine,
        order_code=order_code,
        order_status="PREPARING_SHIPMENT",
        item_status="PREPARING_SHIPMENT",
        payment_status="APPROVED",
    )

    response = client.post(f"/api/admin/orders/{order_code}/ship/prepare")

    assert response.status_code == 200
    assert response.json()["order_status"] == "PREPARING_SHIPMENT"


def test_shipment_action_rejects_wrong_order_status(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    order_code = "ord_api_skip"
    _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="APPROVED")

    # PAID 상태에서 dispatch(PREPARING_SHIPMENT 전용)를 바로 호출 — 건너뛰기 차단
    response = client.post(f"/api/admin/orders/{order_code}/ship/dispatch")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_SHIPPING_TRANSITION_NOT_ALLOWED"


def test_shipment_action_rejects_unapproved_payment(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    order_code = "ord_api_unapproved"
    _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="READY")

    response = client.post(f"/api/admin/orders/{order_code}/ship/prepare")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_PAYMENT_NOT_APPROVED"


def test_shipment_action_inconsistent_items_rolls_back(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    order_code = "ord_api_inconsistent"
    _seed_order(
        db_engine,
        order_code=order_code,
        order_status="PAID",
        payment_status="APPROVED",
        item_count=1,
        stored_item_count=2,  # 저장된 item_count(2) != 실제 OrderItem 수(1)
    )

    response = client.post(f"/api/admin/orders/{order_code}/ship/prepare")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_ITEMS_INCONSISTENT"

    # router 의 session.rollback() 이 실제로 DB에 반영됐는지 — Order·OrderItem 모두 원상태 유지
    persisted_status, item_statuses = _load_order_state(db_engine, order_code)
    assert persisted_status == "PAID"
    assert item_statuses == ["ORDERED"]


def test_shipment_action_unexpected_error_rolls_back_and_logs_failure(
    client: TestClient,
    db_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ApiError 가 아닌 예외(예: 예상 못 한 DB 오류)도 rollback + 실패 로그를 남겨야 한다.
    caplog.set_level(logging.INFO, logger=PERFORMANCE_LOGGER_NAME)
    logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    try:
        _authed_admin(client, db_engine)
        order_code = "ord_api_unexpected_error"
        _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="APPROVED")

        def _boom(session: Session, *, order_code: str) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr("app.api.routes.admin.orders.start_preparation", _boom)

        with pytest.raises(RuntimeError):
            client.post(f"/api/admin/orders/{order_code}/ship/prepare")

        events = [
            json.loads(record.getMessage())["event"]
            for record in caplog.records
            if record.name == PERFORMANCE_LOGGER_NAME
        ]
        assert "admin_order_shipping_transition_failed" in events
        assert "admin_order_shipping_transition_completed" not in events

        # 커밋된 적이 없으니 DB 상태는 그대로여야 함
        persisted_status, _ = _load_order_state(db_engine, order_code)
        assert persisted_status == "PAID"
    finally:
        logger.removeHandler(caplog.handler)


def test_shipment_action_commit_failure_rolls_back_and_logs_failure(
    client: TestClient,
    db_engine: Engine,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # session.commit() 자체가 실패(DB 연결 끊김, 제약조건 위반 등)해도 rollback과
    # 실패 로그가 남아야 한다 — commit 이 try 밖에 있으면 이 케이스가 빠진다.
    caplog.set_level(logging.INFO, logger=PERFORMANCE_LOGGER_NAME)
    logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    try:
        _authed_admin(client, db_engine)
        order_code = "ord_api_commit_fail"
        _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="APPROVED")

        def _boom_commit(self: Session) -> None:
            raise RuntimeError("commit boom")

        monkeypatch.setattr(Session, "commit", _boom_commit)

        with pytest.raises(RuntimeError):
            client.post(f"/api/admin/orders/{order_code}/ship/prepare")

        events = [
            json.loads(record.getMessage())["event"]
            for record in caplog.records
            if record.name == PERFORMANCE_LOGGER_NAME
        ]
        assert "admin_order_shipping_transition_failed" in events
        assert "admin_order_shipping_transition_completed" not in events

    finally:
        logger.removeHandler(caplog.handler)

    # monkeypatch 가 되돌려진 뒤(commit 다시 정상) 새 세션으로 조회 — rollback 이 실제로
    # DB에 반영되어 Order·OrderItem 모두 전이 전 상태로 남아 있어야 한다.
    persisted_status, item_statuses = _load_order_state(db_engine, order_code)
    assert persisted_status == "PAID"
    assert item_statuses == ["ORDERED"]


def test_shipment_action_commit_failure_rolls_back_timestamp_and_event(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # dispatch(SHIPPED 전이)에서 commit 이 실패하면 shipped_at·OrderFulfillmentEvent 도
    # Order.status 와 함께 롤백돼야 한다(같은 트랜잭션).
    _authed_admin(client, db_engine)
    order_code = "ord_api_commit_fail_shipped_at"
    _seed_order(
        db_engine,
        order_code=order_code,
        order_status="PREPARING_SHIPMENT",
        item_status="PREPARING_SHIPMENT",
        payment_status="APPROVED",
    )

    def _boom_commit(self: Session) -> None:
        raise RuntimeError("commit boom")

    monkeypatch.setattr(Session, "commit", _boom_commit)

    with pytest.raises(RuntimeError):
        client.post(f"/api/admin/orders/{order_code}/ship/dispatch")

    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == order_code)).scalar_one()
        assert order.status == "PREPARING_SHIPMENT"
        assert order.shipped_at is None
        events = session.execute(
            select(OrderFulfillmentEvent).where(OrderFulfillmentEvent.order_id == order.id)
        ).scalars().all()
        assert events == []


def test_shipment_action_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/admin/orders/ord_missing/ship/prepare").status_code == 401


def test_shipment_action_rejects_non_admin(client: TestClient) -> None:
    _signup(client)
    assert client.post("/api/admin/orders/ord_missing/ship/prepare").status_code == 403


def test_shipment_action_logs_completed_only_after_commit(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    # PERFORMANCE_LOGGER_NAME 은 propagate=False(app.core.logging) 라 caplog 기본
    # 캡처로는 안 보인다 — caplog 핸들러를 이 로거에 직접 붙여야 잡힌다.
    caplog.set_level(logging.INFO, logger=PERFORMANCE_LOGGER_NAME)
    logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    try:
        _authed_admin(client, db_engine)
        order_code = "ord_api_log_success"
        _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="APPROVED")

        response = client.post(f"/api/admin/orders/{order_code}/ship/prepare")
        assert response.status_code == 200

        events = [
            json.loads(record.getMessage())["event"]
            for record in caplog.records
            if record.name == PERFORMANCE_LOGGER_NAME
        ]
        assert "admin_order_shipping_transition_completed" in events
        assert "admin_order_shipping_transition_failed" not in events
    finally:
        logger.removeHandler(caplog.handler)


def test_shipment_action_logs_failed_only_not_completed(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=PERFORMANCE_LOGGER_NAME)
    logger = logging.getLogger(PERFORMANCE_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    try:
        _authed_admin(client, db_engine)
        order_code = "ord_api_log_failure"
        _seed_order(db_engine, order_code=order_code, order_status="PAID", payment_status="READY")

        response = client.post(f"/api/admin/orders/{order_code}/ship/prepare")
        assert response.status_code == 409

        events = [
            json.loads(record.getMessage())["event"]
            for record in caplog.records
            if record.name == PERFORMANCE_LOGGER_NAME
        ]
        assert "admin_order_shipping_transition_failed" in events
        assert "admin_order_shipping_transition_completed" not in events
    finally:
        logger.removeHandler(caplog.handler)
