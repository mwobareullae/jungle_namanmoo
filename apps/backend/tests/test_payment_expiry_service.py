from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Cart, CartItem, Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentEvent
from app.db.session import get_db
from app.api.routes.payments import get_toss_payments_client
from app.main import app
from app.services.db_seed import seed_database
from app.services.payment_expiry_service import expire_pending_orders
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


def test_expire_pending_orders_marks_expired_and_releases_reserved_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    pending = _create_pending_order(
        client,
        db_engine,
        email="expiry-target@example.com",
        nickname="expiry-target",
        quantity=2,
    )
    _set_payment_expires_at(db_engine, pending["order_code"], now - timedelta(minutes=1))

    logs = _capture_performance_logs()
    try:
        with Session(db_engine) as session:
            result = expire_pending_orders(session, now=now, limit=100)
            session.commit()
    finally:
        logs.close()

    assert result.expired_count == 1
    assert result.order_codes == [pending["order_code"]]
    log_payload = next(line for line in logs.json_lines if line["event"] == "payment_expiry_sweep_completed")
    assert log_payload["limit"] == 100
    assert log_payload["scanned_count"] == 1
    assert log_payload["expired_count"] == 1
    assert log_payload["released_quantity_total"] == 2
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == pending["order_code"])).scalar_one()
        payment = session.execute(select(Payment).where(Payment.payment_code == pending["payment_code"])).scalar_one()
        order_item = session.execute(select(OrderItem).where(OrderItem.order_id == order.id)).scalar_one()
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == order.order_code)
        ).scalars().all()
        events = session.execute(select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)).scalars().all()

    assert order.status == "EXPIRED"
    assert _as_utc(order.expired_at) == now
    assert payment.status == "EXPIRED"
    assert _as_utc(payment.expired_at) == now
    assert order_item.status == "CANCELED"
    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert movements[1].quantity_delta == -2
    assert movements[1].stock_after == 10
    assert len(events) == 1
    assert events[0].event_type == "ORDER_PAYMENT_EXPIRED"
    assert events[0].status_before == "READY"
    assert events[0].status_after == "EXPIRED"


def test_expire_pending_orders_is_idempotent(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    pending = _create_pending_order(
        client,
        db_engine,
        email="expiry-idempotent@example.com",
        nickname="expiry-idempotent",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, pending["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        first_result = expire_pending_orders(session, now=now, limit=100)
        second_result = expire_pending_orders(session, now=now, limit=100)
        session.commit()

    assert first_result.expired_count == 1
    assert second_result.expired_count == 0
    with Session(db_engine) as session:
        inventory = _load_inventory(session, "prod_001")
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == pending["order_code"])
        ).scalars().all()
        events = session.execute(select(PaymentEvent)).scalars().all()

    assert inventory.stock_quantity == 10
    assert inventory.reserved_quantity == 0
    assert [movement.movement_type for movement in movements] == ["RESERVE", "RELEASE_RESERVATION"]
    assert len(events) == 1


def test_expire_pending_orders_skips_unexpired_and_already_paid_orders(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    unexpired = _create_pending_order(
        client,
        db_engine,
        email="expiry-unexpired@example.com",
        nickname="expiry-unexpired",
        product_code="prod_001",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, unexpired["order_code"], now + timedelta(minutes=5))
    paid = _create_pending_order(
        client,
        db_engine,
        email="expiry-paid@example.com",
        nickname="expiry-paid",
        product_code="prod_002",
        quantity=1,
    )
    confirm_response = _confirm_toss_payment(client, paid)
    assert confirm_response.status_code == 200
    _set_payment_expires_at(db_engine, paid["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        result = expire_pending_orders(session, now=now, limit=100)
        session.commit()

    assert result.expired_count == 0
    assert result.order_codes == []
    with Session(db_engine) as session:
        unexpired_order = session.execute(select(Order).where(Order.order_code == unexpired["order_code"])).scalar_one()
        paid_order = session.execute(select(Order).where(Order.order_code == paid["order_code"])).scalar_one()
        unexpired_inventory = _load_inventory(session, "prod_001")
        paid_inventory = _load_inventory(session, "prod_002")

    assert unexpired_order.status == "PENDING_PAYMENT"
    assert paid_order.status == "PAID"
    assert unexpired_inventory.stock_quantity == 10
    assert unexpired_inventory.reserved_quantity == 1
    assert paid_inventory.stock_quantity == 9
    assert paid_inventory.reserved_quantity == 0


def test_expire_pending_orders_respects_limit(
    client: TestClient,
    db_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    first = _create_pending_order(
        client,
        db_engine,
        email="expiry-limit-first@example.com",
        nickname="expiry-limit-first",
        product_code="prod_001",
        quantity=1,
    )
    second = _create_pending_order(
        client,
        db_engine,
        email="expiry-limit-second@example.com",
        nickname="expiry-limit-second",
        product_code="prod_002",
        quantity=1,
    )
    _set_payment_expires_at(db_engine, first["order_code"], now - timedelta(minutes=2))
    _set_payment_expires_at(db_engine, second["order_code"], now - timedelta(minutes=1))

    with Session(db_engine) as session:
        result = expire_pending_orders(session, now=now, limit=1)
        session.commit()

    assert result.expired_count == 1
    assert result.order_codes == [first["order_code"]]


def test_expire_pending_orders_restores_shared_product_across_carts_without_conflict(
    client: TestClient,
    db_engine: Engine,
) -> None:
    """카트 복원 (cart_id, product_id) 유니크 제약 위반 회귀 테스트(2026-07-14).

    같은 유저가 만료 대상 PENDING_PAYMENT 주문을 여러 개 갖고 있고, 각 주문이 서로 다른(비활성)
    카트에 남아있는 같은 상품의 cart_item 을 가리킬 때, `expire_pending_orders` 가 배치 루프
    안에서 명시적으로 flush 하지 않으면 뒤 주문 처리가 앞 주문에서 이미 활성 카트로 옮긴 카트
    아이템을 보지 못해 같은 상품을 또 옮기려다 (cart_id, product_id) 유니크 제약을 위반했다.

    이 테스트는 반드시 SessionLocal 과 동일하게 autoflush=False 인 세션으로 실행해야 한다 —
    autoflush=True 인 기본 Session(engine) 으로는 각 SELECT 쿼리 전에 자동으로 flush 가 일어나
    버그가 재현되지 않아, 이 회귀를 놓치고 통과해버린다.
    """
    now = datetime.now(UTC)
    email = "expiry-shared-product@example.com"
    nickname = "expiry-shared-product"

    first = _create_pending_order(client, db_engine, email=email, nickname=nickname, quantity=1)

    # 첫 주문의 cart_item 이 남아있는 카트를 비활성화해, 같은 상품을 다시 담으면 새 활성 카트가
    # 생기도록 만든다(실제로는 여러 세션에 걸쳐 재주문을 시도할 때 자연히 생길 수 있는 상태).
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        first_cart = session.execute(
            select(Cart).where(Cart.user_id == user.id, Cart.status == "ACTIVE")
        ).scalar_one()
        first_cart.status = "ORDERED"
        session.commit()

    second = _create_pending_order(
        client,
        db_engine,
        email=email,
        nickname=nickname,
        quantity=1,
        skip_signup=True,
        skip_inventory_setup=True,
        idempotency_suffix="-2",
    )
    _set_payment_expires_at(db_engine, first["order_code"], now - timedelta(minutes=2))
    _set_payment_expires_at(db_engine, second["order_code"], now - timedelta(minutes=1))

    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        result = expire_pending_orders(session, now=now, limit=100)
        session.commit()

    assert result.expired_count == 2
    assert set(result.order_codes) == {first["order_code"], second["order_code"]}

    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one()
        product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
        active_cart_items = session.execute(
            select(CartItem)
            .join(Cart, Cart.id == CartItem.cart_id)
            .where(Cart.user_id == user.id, Cart.status == "ACTIVE", CartItem.product_id == product.id)
        ).scalars().all()
        orders = session.execute(
            select(Order).where(Order.order_code.in_([first["order_code"], second["order_code"]]))
        ).scalars().all()
        payments = session.execute(
            select(Payment).where(Payment.payment_code.in_([first["payment_code"], second["payment_code"]]))
        ).scalars().all()

    # 활성 카트에 이 상품이 정확히 한 행으로만 있어야 한다(유니크 제약 위반 없이 병합됐다는 뜻).
    assert len(active_cart_items) == 1
    assert active_cart_items[0].quantity == 2  # 두 주문 수량(1+1)의 합
    assert {order.status for order in orders} == {"EXPIRED"}
    assert {payment.status for payment in payments} == {"EXPIRED"}


def test_expire_pending_orders_isolates_failed_order_and_processes_rest_of_batch(
    client: TestClient,
    db_engine: Engine,
) -> None:
    """배치 내 한 주문 처리 실패가 나머지 주문 처리를 막지 않는지 확인하는 회귀 테스트(2026-07-14).

    Option A(주문별 savepoint 격리) 도입 전에는 배치 전체가 하나의 트랜잭션이라, 한 주문에서
    예외(재고 정합성 오류 등)가 나면 세션이 손상되어 배치의 나머지 주문도 함께 처리되지 못했다.
    이 테스트는 첫 번째 주문의 재고 예약 수량을 의도적으로 깨서 그 주문만 실패시키고, 뒤이어
    처리되는 두 번째(정상) 주문은 계속 만료 처리되는지 검증한다.
    """
    now = datetime.now(UTC)
    failing = _create_pending_order(
        client,
        db_engine,
        email="expiry-batch-fail-a@example.com",
        nickname="expiry-batch-fail-a",
        product_code="prod_001",
        quantity=1,
    )
    succeeding = _create_pending_order(
        client,
        db_engine,
        email="expiry-batch-fail-b@example.com",
        nickname="expiry-batch-fail-b",
        product_code="prod_002",
        quantity=1,
    )
    # failing 이 succeeding 보다 먼저 처리되도록 만료 시각을 더 과거로 둔다(정렬 기준:
    # payment_expires_at asc). 배치 앞쪽 주문이 실패해도 뒤쪽 주문이 처리되는지 확인하기 위함.
    _set_payment_expires_at(db_engine, failing["order_code"], now - timedelta(minutes=2))
    _set_payment_expires_at(db_engine, succeeding["order_code"], now - timedelta(minutes=1))
    # failing 주문의 재고 예약 수량을 주문 수량보다 낮게 깨서, 만료 처리 중 재고 반환 단계에서
    # ApiError(INVENTORY_RESERVATION_INVALID) 가 발생하도록 만든다.
    _set_inventory(db_engine, "prod_001", stock_quantity=10, reserved_quantity=0)

    session_factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    logs = _capture_performance_logs()
    try:
        with session_factory() as session:
            result = expire_pending_orders(session, now=now, limit=100)
            session.commit()
    finally:
        logs.close()

    assert result.expired_count == 1
    assert result.order_codes == [succeeding["order_code"]]
    assert result.failed_count == 1
    assert result.failed_order_codes == [failing["order_code"]]

    failed_log = next(line for line in logs.json_lines if line["event"] == "payment_expiry_order_failed")
    assert failed_log["order_code"] == failing["order_code"]
    assert failed_log["error_type"] == "ApiError"
    completed_log = next(line for line in logs.json_lines if line["event"] == "payment_expiry_sweep_completed")
    assert completed_log["expired_count"] == 1
    assert completed_log["failed_count"] == 1

    with Session(db_engine) as session:
        failed_order = session.execute(
            select(Order).where(Order.order_code == failing["order_code"])
        ).scalar_one()
        failed_payment = session.execute(
            select(Payment).where(Payment.payment_code == failing["payment_code"])
        ).scalar_one()
        succeeded_order = session.execute(
            select(Order).where(Order.order_code == succeeding["order_code"])
        ).scalar_one()
        succeeded_payment = session.execute(
            select(Payment).where(Payment.payment_code == succeeding["payment_code"])
        ).scalar_one()

    # 실패한 주문은 savepoint 롤백으로 아무 것도 바뀌지 않은 채 남아 다음 스윕에서 재시도될 수 있다.
    assert failed_order.status == "PENDING_PAYMENT"
    assert failed_payment.status == "READY"
    # 실패 주문 뒤에 오는 정상 주문은 배치가 중단되지 않고 그대로 만료 처리된다.
    assert succeeded_order.status == "EXPIRED"
    assert succeeded_payment.status == "EXPIRED"


def _create_pending_order(
    client: TestClient,
    db_engine: Engine,
    *,
    email: str,
    nickname: str,
    product_code: str = "prod_001",
    quantity: int,
    skip_signup: bool = False,
    skip_inventory_setup: bool = False,
    idempotency_suffix: str = "",
) -> dict:
    if not skip_signup:
        _signup(client, email=email, nickname=nickname)
    if not skip_inventory_setup:
        _set_inventory(db_engine, product_code, stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": product_code, "quantity": quantity})
    assert add_response.status_code == 200
    item_id = add_response.json()["items"][0]["id"]
    address_id = _create_address(client)["id"]
    order_response = client.post(
        "/api/orders",
        headers={"Idempotency-Key": f"order-{email}{idempotency_suffix}"},
        json={"cart_item_ids": [item_id], "address_id": address_id, "payment_provider": "TOSS"},
    )
    assert order_response.status_code == 200
    data = order_response.json()
    return {
        "order_code": data["order_code"],
        "payment_code": data["payment"]["payment_code"],
        "amount": data["total"],
    }


def _confirm_toss_payment(client: TestClient, pending: dict):
    app.dependency_overrides[get_toss_payments_client] = lambda: _FakeTossConfirmClient()
    return client.post(
        "/api/payments/toss/confirm",
        json={
            "payment_key": "toss_expiry_key",
            "order_code": pending["order_code"],
            "amount": pending["amount"],
        },
    )


class _FakeTossConfirmClient:
    def confirm_payment(self, *, payment_key: str, order_code: str, amount: int) -> dict:
        return {
            "paymentKey": payment_key,
            "orderId": order_code,
            "totalAmount": amount,
            "status": "DONE",
            "method": "카드",
            "approvedAt": "2026-07-05T12:00:00+09:00",
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


def _set_payment_expires_at(
    db_engine: Engine,
    order_code: str,
    expires_at: datetime,
) -> None:
    with Session(db_engine) as session:
        order = session.execute(select(Order).where(Order.order_code == order_code)).scalar_one()
        order.payment_expires_at = expires_at
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
