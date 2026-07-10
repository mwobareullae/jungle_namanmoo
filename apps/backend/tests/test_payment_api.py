from collections.abc import Generator
import hashlib
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.payments import get_toss_payments_client
from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, InventoryMovement, Order, Payment, PaymentAttempt, PaymentEvent
from app.db.models.events import EventLog
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR
from app.services.toss_payments_client import TossPaymentsClientError
from app.services.payment_reconciliation_service import reconcile_pending_payments


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

def test_mock_confirm_approves_payment_and_converts_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    payment_code = _create_pending_order(
        client,
        db_engine,
        email="payment-confirm@example.com",
        nickname="payment-confirm",
        quantity=2,
    )["payment_code"]

    logs = _capture_performance_logs()
    try:
        response = client.post(
            f"/api/payments/{payment_code}/mock/confirm",
            headers={"x-request-id": "payment-confirm-request"},
        )
    finally:
        logs.close()

    assert response.status_code == 200
    data = response.json()
    assert data["order_status"] == "PAID"
    assert data["payment_status"] == "APPROVED"
    assert data["approved_at"] is not None
    assert data["failed_at"] is None
    log_payload = next(line for line in logs.json_lines if line["event"] == "payment_confirm_completed")
    assert log_payload["request_id"] == "payment-confirm-request"
    assert log_payload["provider"] == "MOCK"
    assert log_payload["order_status"] == "PAID"
    assert log_payload["payment_status"] == "APPROVED"
    assert log_payload["confirmed_quantity_total"] == 2
    assert log_payload["idempotent_replay"] is False
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == data["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == payment_code)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        event_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "order_completed", EventLog.order_id == order.id)
        ).scalars().all()
        started_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "payment_started", EventLog.order_id == order.id)
        ).scalars().all()

    assert order.status == "PAID"
    assert order.paid_at is not None
    assert payment.status == "APPROVED"
    assert payment.approved_at is not None
    assert log_payload["amount"] == payment.amount
    assert inventory.stock_quantity == 8
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "SALE_CONFIRM"]
    assert movements[1].quantity_delta == -2
    assert movements[1].stock_after == 8
    assert len(events) == 1
    assert events[0].event_type == "MOCK_PAYMENT_APPROVED"
    assert events[0].status_before == "READY"
    assert events[0].status_after == "APPROVED"
    assert len(event_logs) == 1
    assert event_logs[0].source == "mock_payment_confirm"
    assert event_logs[0].user_id == order.user_id
    assert event_logs[0].request_id == response.headers["x-request-id"]
    assert event_logs[0].metadata_json["payment_status"] == "APPROVED"
    assert event_logs[0].metadata_json["amount"] == payment.amount
    assert len(started_logs) == 1
    assert started_logs[0].source == "mock_payment_confirm"
    assert started_logs[0].metadata_json["payment_status"] == "READY"


def test_mock_confirm_is_idempotent_and_does_not_deduct_stock_twice(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-idempotent@example.com",
        nickname="payment-idempotent",
        quantity=1,
    )

    first_response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")
    second_response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["order_status"] == "PAID"
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent)).scalars().all()
        event_logs = session.execute(select(EventLog).where(EventLog.event_name == "order_completed")).scalars().all()

    assert inventory.stock_quantity == 9
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "SALE_CONFIRM"]
    assert len(events) == 1
    assert len(event_logs) == 1


def test_mock_fail_marks_payment_failed_and_releases_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-fail@example.com",
        nickname="payment-fail",
        quantity=1,
    )

    logs = _capture_performance_logs()
    try:
        response = client.post(
            f"/api/payments/{pending['payment_code']}/mock/fail",
            headers={"x-request-id": "payment-fail-request"},
        )
    finally:
        logs.close()

    assert response.status_code == 200
    assert response.json()["order_status"] == "PAYMENT_FAILED"
    assert response.json()["payment_status"] == "FAILED"
    log_payload = next(line for line in logs.json_lines if line["event"] == "payment_fail_completed")
    assert log_payload["request_id"] == "payment-fail-request"
    assert log_payload["provider"] == "MOCK"
    assert log_payload["payment_status"] == "FAILED"
    assert log_payload["order_status"] == "PAYMENT_FAILED"
    assert log_payload["released_quantity_total"] == 1
    assert log_payload["idempotent_replay"] is False
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        event_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "payment_failed", EventLog.order_id == order.id)
        ).scalars().all()

    assert order.status == "PAYMENT_FAILED"
    assert payment.status == "FAILED"
    assert payment.failed_at is not None
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert movements[1].quantity_delta == -1
    assert len(events) == 1
    assert events[0].event_type == "MOCK_PAYMENT_FAILED"
    assert len(event_logs) == 1
    assert event_logs[0].source == "mock_payment_fail"
    assert event_logs[0].user_id == order.user_id
    assert event_logs[0].request_id == response.headers["x-request-id"]
    assert event_logs[0].metadata_json["payment_status"] == "FAILED"


def test_mock_payment_ownership_is_enforced(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="payment-owner@example.com",
        nickname="payment-owner",
        quantity=1,
    )
    _signup(client, email="payment-other@example.com", nickname="payment-other")

    response = client.post(f"/api/payments/{pending['payment_code']}/mock/confirm")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()

    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "READY"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1


@pytest.mark.parametrize("endpoint", ["confirm", "fail"])
def test_mock_payment_endpoint_rejects_toss_payment(
    client: TestClient,
    db_engine: Engine,
    endpoint: str,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email=f"mock-provider-{endpoint}@example.com",
        nickname=f"mock-provider-{endpoint}",
        quantity=1,
        payment_provider="TOSS",
    )

    response = client.post(f"/api/payments/{pending['payment_code']}/mock/{endpoint}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYMENT_PROVIDER_MISMATCH"
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        attempts = session.execute(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment.id)).scalars().all()

    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "READY"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1
    assert events == []


@pytest.mark.parametrize("payment_provider", ["KAKAO_PAY", "NAVER_PAY"])
def test_order_rejects_unsupported_payment_provider(
    client: TestClient,
    db_engine: Engine,
    payment_provider: str,
) -> None:
    email = f"unsupported-{payment_provider.lower()}@example.com"
    _signup(client, email=email, nickname=f"unsupported-{payment_provider.lower()}")
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]

    response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": f"unsupported-{payment_provider.lower()}"},
        json={
            "cart_item_ids": [item_id],
            "address_id": address_id,
            "payment_provider": payment_provider,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_PAYMENT_PROVIDER"
    with Session(db_engine) as session:
        assert session.execute(select(Order)).scalars().all() == []
        assert session.execute(select(Payment)).scalars().all() == []
        inventory = _load_inventory(session, "prod_001")
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0


def test_toss_confirm_approves_payment_and_records_provider_key(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-confirm@example.com",
        nickname="toss-confirm",
        quantity=2,
        payment_provider="TOSS",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_payment_key_confirm",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 200
    assert response.json()["order_status"] == "PAID"
    assert response.json()["payment_status"] == "APPROVED"
    assert fake_toss.calls == [
        {
            "payment_key": "toss_payment_key_confirm",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        }
    ]
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        attempts = session.execute(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment.id)).scalars().all()
        event_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "order_completed", EventLog.order_id == order.id)
        ).scalars().all()

    assert payment.provider == "TOSS"
    assert payment.provider_payment_key == "toss_payment_key_confirm"
    assert payment.provider_order_id == pending["order_code"]
    assert inventory.stock_quantity == 8
    assert inventory.reserved_quantity == 0
    assert len(events) == 1
    assert len(attempts) == 1
    assert attempts[0].operation == "CONFIRM"
    assert attempts[0].status == "APPROVED"
    assert attempts[0].provider_payment_key == "toss_payment_key_confirm"
    assert events[0].event_type == "TOSS_PAYMENT_APPROVED"
    assert events[0].provider_payment_key == "toss_payment_key_confirm"
    assert events[0].raw_payload_json["status"] == "DONE"
    assert len(event_logs) == 1
    assert event_logs[0].source == "toss_payment_confirm"
    assert event_logs[0].metadata_json["payment_provider"] == "TOSS"


def test_toss_confirm_rejects_amount_mismatch_before_provider_call(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-amount@example.com",
        nickname="toss-amount",
        quantity=1,
        payment_provider="TOSS",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_payment_key_amount",
            "order_code": pending["order_code"],
            "amount": pending["amount"] + 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYMENT_AMOUNT_MISMATCH"
    assert fake_toss.calls == []
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        started_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "payment_started", EventLog.order_id == order.id)
        ).scalars().all()
        failed_logs = session.execute(
            select(EventLog).where(EventLog.event_name == "payment_failed", EventLog.order_id == order.id)
        ).scalars().all()

    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "READY"
    assert payment.provider_payment_key is None
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1
    assert len(started_logs) == 1
    assert started_logs[0].source == "toss_payment_confirm"
    assert "payment_key" not in started_logs[0].metadata_json
    assert len(failed_logs) == 1
    assert failed_logs[0].source == "toss_payment_confirm"
    assert failed_logs[0].metadata_json["error_code"] == "PAYMENT_AMOUNT_MISMATCH"
    assert "payment_key" not in failed_logs[0].metadata_json


def test_toss_confirm_rejects_mock_payment_before_provider_call(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-provider-mismatch@example.com",
        nickname="toss-provider-mismatch",
        quantity=1,
        payment_provider="MOCK",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_payment_key_provider_mismatch",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYMENT_PROVIDER_MISMATCH"
    assert fake_toss.calls == []
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "READY"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1


@pytest.mark.parametrize(
    ("case", "omitted_fields", "response_overrides", "expected_error_code"),
    [
        ("missing-key", {"paymentKey"}, {}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("missing-order", {"orderId"}, {}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("missing-amount", {"totalAmount"}, {}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("missing-status", {"status"}, {}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("wrong-key", set(), {"paymentKey": "different"}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("wrong-order", set(), {"orderId": "different"}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("wrong-amount", set(), {"totalAmount": -1}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("string-amount", set(), {"totalAmount": "19000"}, "TOSS_CONFIRM_INVALID_RESPONSE"),
        ("not-done", set(), {"status": "IN_PROGRESS"}, "TOSS_CONFIRM_NOT_DONE"),
    ],
)
def test_toss_confirm_rejects_invalid_provider_response(
    client: TestClient,
    db_engine: Engine,
    case: str,
    omitted_fields: set[str],
    response_overrides: dict,
    expected_error_code: str,
) -> None:
    fake_toss = _FakeTossPaymentsClient(
        omitted_fields=omitted_fields,
        response_overrides=response_overrides,
    )
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email=f"toss-response-{case}@example.com",
        nickname=f"toss-response-{case}",
        quantity=1,
        payment_provider="TOSS",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": f"toss_payment_key_{case}",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == expected_error_code
    assert len(fake_toss.calls) == 1
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()
        attempts = session.execute(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment.id)).scalars().all()
    assert order.status == "PENDING_PAYMENT"
    assert payment.status == "FAILED"
    assert payment.provider_payment_key is None
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1
    assert events == []
    assert len(attempts) == 1
    assert attempts[0].operation == "CONFIRM"
    assert attempts[0].status == "FAILED"
    assert attempts[0].provider_error_code == expected_error_code


def test_toss_confirm_rejects_payment_key_over_provider_limit(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-key-too-long@example.com",
        nickname="toss-key-too-long",
        quantity=1,
        payment_provider="TOSS",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "k" * 201,
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert fake_toss.calls == []


def test_toss_confirm_records_unknown_when_provider_request_is_uncertain(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient(error=TossPaymentsClientError(
        "TOSS_CONFIRM_REQUEST_FAILED",
        "provider request failed",
    ))
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-unknown@example.com",
        nickname="toss-unknown",
        quantity=1,
        payment_provider="TOSS",
    )

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_payment_key_unknown",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 502
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        attempt = session.execute(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment.id)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
    assert payment.status == "UNKNOWN"
    assert attempt.status == "UNKNOWN"
    assert attempt.provider_error_code == "TOSS_CONFIRM_REQUEST_FAILED"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 1


def test_reconcile_done_payment_approves_and_deducts_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="reconcile-done@example.com",
        nickname="reconcile-done",
        quantity=1,
        payment_provider="TOSS",
    )
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        payment.status = "UNKNOWN"
        payment.provider_payment_key = "toss_query_key"
        session.add(
            PaymentAttempt(
                payment_id=payment.id,
                attempt_code="toss_confirm:reconcile-done",
                operation="CONFIRM",
                provider="TOSS",
                status="UNKNOWN",
                provider_payment_key="toss_query_key",
                requested_at=payment.created_at,
                created_at=payment.created_at,
                updated_at=payment.created_at,
            )
        )
        session.commit()

        result = reconcile_pending_payments(
            session,
            toss_client=_FakeTossQueryClient(
                {"paymentKey": "toss_query_key", "orderId": pending["order_code"], "totalAmount": pending["amount"], "status": "DONE"}
            ),
        )
        session.commit()

    assert result.approved_count == 1
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        attempt = session.execute(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment.id)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
    assert payment.status == "APPROVED"
    assert order.status == "PAID"
    assert attempt.status == "APPROVED"
    assert inventory.stock_quantity == 9
    assert inventory.reserved_quantity == 0


def test_reconcile_query_error_keeps_payment_unknown(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="reconcile-unknown@example.com",
        nickname="reconcile-unknown",
        quantity=1,
        payment_provider="TOSS",
    )
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        payment.status = "UNKNOWN"
        payment.provider_payment_key = "toss_query_unknown"
        session.add(
            PaymentAttempt(
                payment_id=payment.id,
                attempt_code="toss_confirm:reconcile-unknown",
                operation="CONFIRM",
                provider="TOSS",
                status="UNKNOWN",
                provider_payment_key="toss_query_unknown",
                requested_at=payment.created_at,
                created_at=payment.created_at,
                updated_at=payment.created_at,
            )
        )
        session.commit()
        result = reconcile_pending_payments(
            session,
            toss_client=_FakeTossQueryClient(error=TossPaymentsClientError("QUERY_FAILED", "temporary")),
        )
        session.commit()

    assert result.unknown_count == 1
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
    assert payment.status == "UNKNOWN"


def test_toss_webhook_records_event_and_reconciles_once(
    client: TestClient,
    db_engine: Engine,
) -> None:
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-webhook@example.com",
        nickname="toss-webhook",
        quantity=1,
        payment_provider="TOSS",
    )
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        payment.status = "UNKNOWN"
        payment.provider_payment_key = "toss_webhook_key"
        session.add(
            PaymentAttempt(
                payment_id=payment.id,
                attempt_code="toss_confirm:webhook",
                operation="CONFIRM",
                provider="TOSS",
                status="UNKNOWN",
                provider_payment_key="toss_webhook_key",
                requested_at=payment.created_at,
                created_at=payment.created_at,
                updated_at=payment.created_at,
            )
        )
        session.commit()

    fake_toss = _FakeTossPaymentsClient(
        query_response={
            "paymentKey": "toss_webhook_key",
            "orderId": pending["order_code"],
            "totalAmount": pending["amount"],
            "status": "DONE",
        }
    )
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    payload = {
        "eventType": "PAYMENT_STATUS_CHANGED",
        "paymentKey": "toss_webhook_key",
        "orderId": pending["order_code"],
        "status": "DONE",
    }
    first = client.post("/api/payments/toss/webhook", headers={"X-Toss-Webhook-Id": "webhook-1"}, json=payload)
    second = client.post("/api/payments/toss/webhook", headers={"X-Toss-Webhook-Id": "webhook-1"}, json=payload)

    assert first.status_code == 200
    assert first.json()["reconciled"] == 1
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        webhook_events = session.execute(
            select(PaymentEvent).where(
                PaymentEvent.payment_id == payment.id,
                PaymentEvent.event_type == "TOSS_WEBHOOK_RECEIVED",
            )
        ).scalars().all()
    assert payment.status == "APPROVED"
    assert len(webhook_events) == 1


def test_toss_confirm_hashes_long_payment_key_for_event_id(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-long-key@example.com",
        nickname="toss-long-key",
        quantity=1,
        payment_provider="TOSS",
    )
    payment_key = "k" * 200

    response = client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": payment_key,
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )

    assert response.status_code == 200
    with Session(db_engine) as session:
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        event = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalar_one()
    expected_event_id = f"toss_confirm:{hashlib.sha256(payment_key.encode('utf-8')).hexdigest()}"
    assert event.event_id == expected_event_id
    assert len(event.event_id) <= 128


def test_toss_confirm_is_idempotent_for_same_payment_key(
    client: TestClient,
    db_engine: Engine,
) -> None:
    fake_toss = _FakeTossPaymentsClient()
    app.dependency_overrides[get_toss_payments_client] = lambda: fake_toss
    pending = _create_pending_order(
        client,
        db_engine,
        email="toss-idempotent@example.com",
        nickname="toss-idempotent",
        quantity=1,
        payment_provider="TOSS",
    )
    payload = {
        "payment_key": "toss_payment_key_idempotent",
        "order_code": pending["order_code"],
        "amount": pending["amount"],
    }

    first_response = client.post("/api/payments/toss/confirm", json=payload)
    second_response = client.post("/api/payments/toss/confirm", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(fake_toss.calls) == 1
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        events = session.execute(select(PaymentEvent)).scalars().all()
        event_logs = session.execute(select(EventLog).where(EventLog.event_name == "order_completed")).scalars().all()

    assert inventory.stock_quantity == 9
    assert inventory.reserved_quantity == 0
    assert len(events) == 1
    assert len(event_logs) == 1


def _create_pending_order(
    client: TestClient,
    db_engine: Engine,
    *,
    email: str,
    nickname: str,
    quantity: int,
    payment_provider: str = "MOCK",
) -> dict:
    _signup(client, email=email, nickname=nickname)
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": quantity})
    assert add_response.status_code == 200
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]
    order_response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": f"order-{email}"},
        json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": payment_provider},
    )
    assert order_response.status_code == 200
    data = order_response.json()
    return {
        "order_code": data["order_code"],
        "payment_code": data["payment"]["payment_code"],
        "amount": data["payment"]["amount"],
    }


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


def _create_address(client: TestClient) -> dict:
    response = client.post(
        "/api/me/addresses",
        json={
            "recipient_name": "Kim Wonwoo",
            "phone": "01012345678",
            "postal_code": "12345",
            "address1": "Seoul",
            "address2": "101",
            "delivery_memo": "Leave at door",
            "is_default": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def _set_inventory(
    db_engine: Engine,
    product_code: str,
    *,
    stock_quantity: int,
    reserved_quantity: int = 0,
    safety_stock: int = 0,
    sales_status: str = "ON_SALE",
) -> None:
    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
        inventory = session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one_or_none()
        if inventory is None:
            inventory = Inventory(
                product_id=product.id,
                stock_quantity=stock_quantity,
                reserved_quantity=reserved_quantity,
                safety_stock=safety_stock,
                sales_status=sales_status,
                inventory_source="TEST",
            )
            session.add(inventory)
        else:
            inventory.stock_quantity = stock_quantity
            inventory.reserved_quantity = reserved_quantity
            inventory.safety_stock = safety_stock
            inventory.sales_status = sales_status
        session.commit()


def _load_inventory(session: Session, product_code: str) -> Inventory:
    product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
    return session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    logger.setLevel(logging.INFO)
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler


class _FakeTossPaymentsClient:
    def __init__(
        self,
        *,
        omitted_fields: set[str] | None = None,
        response_overrides: dict | None = None,
        error: TossPaymentsClientError | None = None,
        query_response: dict | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.omitted_fields = omitted_fields or set()
        self.response_overrides = response_overrides or {}
        self.error = error
        self.query_response = query_response

    def confirm_payment(self, *, payment_key: str, order_code: str, amount: int) -> dict:
        self.calls.append(
            {
                "payment_key": payment_key,
                "order_code": order_code,
                "amount": amount,
            }
        )
        if self.error is not None:
            raise self.error
        response = {
            "paymentKey": payment_key,
            "orderId": order_code,
            "totalAmount": amount,
            "status": "DONE",
            "method": "카드",
            "approvedAt": "2026-07-05T12:00:00+09:00",
        }
        response.update(self.response_overrides)
        for field in self.omitted_fields:
            response.pop(field, None)
        return response

    def get_payment(self, *, payment_key: str) -> dict:
        if self.error is not None:
            raise self.error
        return self.query_response or {"paymentKey": payment_key, "status": "UNKNOWN"}


class _FakeTossQueryClient:
    def __init__(self, response: dict | None = None, error: TossPaymentsClientError | None = None) -> None:
        self.response = response or {}
        self.error = error

    def get_payment(self, *, payment_key: str) -> dict:
        if self.error is not None:
            raise self.error
        return self.response
