from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderItem, Payment
from app.schemas.common import ApiError
from app.services.admin.order_service import list_admin_orders


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine: Engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


_order_seq = 0
_user_seq = 0


def _make_user(session: Session, *, display_name: str | None) -> User:
    global _user_seq
    _user_seq += 1
    user = User(
        email=f"u{_user_seq}@example.com",
        display_name=display_name,
        status="ACTIVE",
        role="USER",
    )
    session.add(user)
    session.flush()
    return user


def _make_order(
    session: Session,
    *,
    order_status: str = "PAID",
    payment_status: str | None = "APPROVED",
    total_quantity: int = 1,
    item_count: int = 1,
    recommendation_ids: list[str | None] | None = None,
    display_name: str | None = None,  # users.display_name UNIQUE — 기본 NULL(다중 허용)
    ordered_at: datetime | None = None,
) -> Order:
    global _order_seq
    _order_seq += 1
    now = ordered_at or datetime.now(UTC)
    user = _make_user(session, display_name=display_name)
    order = Order(
        order_code=f"ord_{_order_seq}",
        user_id=user.id,
        idempotency_key=f"key_{_order_seq}",
        status=order_status,
        subtotal_amount=1000,
        total_amount=1000,
        currency="KRW",
        item_count=item_count,
        total_quantity=total_quantity,
        ordered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    rec_ids = recommendation_ids if recommendation_ids is not None else [None] * item_count
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
                status="ORDERED",
                recommendation_id=rec_ids[idx] if idx < len(rec_ids) else None,
                created_at=now,
                updated_at=now,
            )
        )
    if payment_status is not None:
        session.add(
            Payment(
                payment_code=f"pay_{_order_seq}",
                order_id=order.id,
                provider="MOCK",
                status=payment_status,
                amount=1000,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    return order


def test_order_status_filter(session: Session) -> None:
    _make_order(session, order_status="PAID")
    _make_order(session, order_status="SHIPPED")
    session.commit()

    resp = list_admin_orders(session, order_status="PAID", payment_status=None, limit=20, cursor=None)
    assert [it.order_status for it in resp.items] == ["PAID"]


def test_payment_status_filter_excludes_missing_payment(session: Session) -> None:
    _make_order(session, payment_status="UNKNOWN")   # 실제 결제 상태 UNKNOWN
    _make_order(session, payment_status=None)          # 결제 레코드 없음
    session.commit()

    resp = list_admin_orders(session, order_status=None, payment_status="UNKNOWN", limit=20, cursor=None)
    # UNKNOWN 필터는 실제 결제 레코드가 UNKNOWN인 것만 — 누락 주문은 제외
    assert len(resp.items) == 1
    assert resp.items[0].payment_status == "UNKNOWN"
    assert resp.items[0].payment_issue is None


def test_missing_payment_reports_issue_and_included_without_filter(session: Session) -> None:
    _make_order(session, payment_status=None)
    session.commit()

    resp = list_admin_orders(session, order_status=None, payment_status=None, limit=20, cursor=None)
    assert len(resp.items) == 1
    assert resp.items[0].payment_status is None
    assert resp.items[0].payment_issue == "PAYMENT_NOT_FOUND"


def test_cursor_pagination(session: Session) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        _make_order(session, ordered_at=base + timedelta(minutes=i))
    session.commit()

    first = list_admin_orders(session, order_status=None, payment_status=None, limit=2, cursor=None)
    assert len(first.items) == 2
    assert first.next_cursor is not None

    second = list_admin_orders(
        session, order_status=None, payment_status=None, limit=2, cursor=first.next_cursor
    )
    assert len(second.items) == 1
    assert second.next_cursor is None
    # 페이지 간 중복 없음
    first_ids = {it.id for it in first.items}
    assert second.items[0].id not in first_ids


def test_reserved_quantity_only_for_pending_payment(session: Session) -> None:
    _make_order(session, order_status="PENDING_PAYMENT", payment_status="READY", total_quantity=3)
    _make_order(session, order_status="CANCEL_REQUESTED", total_quantity=5)
    _make_order(session, order_status="PAID", total_quantity=7)
    session.commit()

    resp = list_admin_orders(session, order_status=None, payment_status=None, limit=20, cursor=None)
    by_status = {it.order_status: it.reserved_quantity for it in resp.items}
    assert by_status["PENDING_PAYMENT"] == 3
    assert by_status["CANCEL_REQUESTED"] == 0
    assert by_status["PAID"] == 0


def test_customer_display_fallback(session: Session) -> None:
    _make_order(session, display_name="지현")
    _make_order(session, display_name=None)
    session.commit()

    resp = list_admin_orders(session, order_status=None, payment_status=None, limit=20, cursor=None)
    displays = {it.customer_display for it in resp.items}
    assert "지현" in displays
    assert any(d.startswith("user_") for d in displays)


def test_recommendation_ids_deduplicated(session: Session) -> None:
    _make_order(
        session,
        item_count=3,
        recommendation_ids=["rec_a", "rec_a", "rec_b"],
    )
    session.commit()

    resp = list_admin_orders(session, order_status=None, payment_status=None, limit=20, cursor=None)
    assert resp.items[0].recommendation_ids == ["rec_a", "rec_b"]


def test_summary_independent_of_page_and_filter(session: Session) -> None:
    _make_order(session, order_status="PENDING_PAYMENT", payment_status="READY", total_quantity=2)
    _make_order(session, order_status="PENDING_PAYMENT", payment_status="READY", total_quantity=4)
    _make_order(session, order_status="PREPARING_SHIPMENT")
    _make_order(session, order_status="CANCEL_REQUESTED")
    session.commit()

    # 페이지 1개(limit=1) + 필터 걸어도 summary는 전체 기준
    resp = list_admin_orders(session, order_status="PAID", payment_status=None, limit=1, cursor=None)
    assert resp.summary.pending_payment_count == 2
    assert resp.summary.preparing_shipment_count == 1
    assert resp.summary.cancel_requested_count == 1
    assert resp.summary.reserved_quantity_total == 6  # 2 + 4


def test_invalid_status_rejected(session: Session) -> None:
    with pytest.raises(ApiError):
        list_admin_orders(session, order_status="NOPE", payment_status=None, limit=20, cursor=None)
    with pytest.raises(ApiError):
        list_admin_orders(session, order_status=None, payment_status="NOPE", limit=20, cursor=None)
