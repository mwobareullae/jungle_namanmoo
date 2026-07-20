"""관리자 취소 요청 목록·상세 조회 서비스 테스트 (M1.5-B, 조회 전용)."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderCancelRequest, OrderItem, Payment
from app.schemas.common import ApiError
from app.services.admin.order_cancel_request_service import (
    get_admin_cancel_request,
    list_admin_cancel_requests,
)


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


_seq = 0


def _make_cancel_request(
    session: Session,
    *,
    request_status: str = "REQUESTED",
    order_status: str = "CANCEL_REQUESTED",
    payment_status: str | None = "APPROVED",
    payment_provider: str = "MOCK",
    display_name: str | None = None,  # users.display_name UNIQUE — 기본 NULL(다중 허용)
    reason_code: str | None = "CHANGE_OF_MIND",
    decision_reason: str | None = None,
    requested_at: datetime | None = None,
    processed_at: datetime | None = None,
    item_count: int = 1,
) -> OrderCancelRequest:
    global _seq
    _seq += 1
    now = requested_at or datetime.now(UTC)
    user = User(email=f"cancelreq{_seq}@example.com", display_name=display_name, status="ACTIVE", role="USER")
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_cancelreq_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_cancelreq_{_seq}",
        status=order_status,
        subtotal_amount=10000 * item_count,
        total_amount=10000 * item_count,
        currency="KRW",
        item_count=item_count,
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
                product_id=_seq * 100 + idx,
                seller_id=1,
                product_name_snapshot=f"상품{chr(ord('A') + idx)}",
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
    if payment_status is not None:
        session.add(
            Payment(
                payment_code=f"pay_cancelreq_{_seq}",
                order_id=order.id,
                provider=payment_provider,
                status=payment_status,
                amount=10000 * item_count,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    request = OrderCancelRequest(
        request_code=f"ocr_test_{_seq}",
        order_id=order.id,
        user_id=user.id,
        status=request_status,
        reason_code=reason_code,
        decision_reason=decision_reason,
        requested_at=now,
        processed_at=processed_at,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    session.flush()
    return request


def test_list_returns_requested_with_approve_and_reject_actions(session: Session) -> None:
    _make_cancel_request(session, request_status="REQUESTED", payment_provider="MOCK", display_name="닉네임")
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert len(response.items) == 1
    item = response.items[0]
    assert item.status == "REQUESTED"
    assert item.available_actions == ["APPROVE", "REJECT"]
    assert item.customer_display == "닉네임"


def test_list_toss_payment_offers_simulated_approve_and_reject(session: Session) -> None:
    _make_cancel_request(session, request_status="REQUESTED", payment_provider="TOSS")
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert response.items[0].available_actions == ["APPROVE", "REJECT"]


def test_list_missing_payment_offers_no_actions(session: Session) -> None:
    _make_cancel_request(session, request_status="REQUESTED", payment_status=None)
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert response.items[0].available_actions == []


def test_list_decided_request_offers_no_actions(session: Session) -> None:
    _make_cancel_request(
        session,
        request_status="APPROVED",
        order_status="CANCELED",
        payment_status="CANCELED",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert response.items[0].available_actions == []


def test_list_filters_by_status(session: Session) -> None:
    _make_cancel_request(session, request_status="REQUESTED")
    _make_cancel_request(
        session,
        request_status="REJECTED",
        order_status="PAID",
        decision_reason="고객 재요청",
        processed_at=datetime.now(UTC),
    )
    session.commit()

    response = list_admin_cancel_requests(session, status="REJECTED", page_size=20)

    assert len(response.items) == 1
    assert response.items[0].status == "REJECTED"
    assert response.items[0].decision_reason == "고객 재요청"


def test_list_rejects_invalid_status(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        list_admin_cancel_requests(session, status="NOT_A_STATUS", page_size=20)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_CANCEL_REQUEST_STATUS"


def test_list_paginates_by_page_newest_first(session: Session) -> None:
    base_time = datetime.now(UTC)
    codes = [
        _make_cancel_request(session, requested_at=base_time + timedelta(minutes=idx)).request_code
        for idx in range(3)
    ]
    session.commit()

    first_page = list_admin_cancel_requests(session, status=None, page=1, page_size=2)
    assert len(first_page.items) == 2
    assert first_page.pagination.total_items == 3
    assert first_page.pagination.total_pages == 2
    assert first_page.pagination.has_next is True
    assert first_page.pagination.has_prev is False
    assert [item.request_code for item in first_page.items] == [codes[2], codes[1]]

    second_page = list_admin_cancel_requests(session, status=None, page=2, page_size=2)
    assert [item.request_code for item in second_page.items] == [codes[0]]
    assert second_page.pagination.has_next is False
    assert second_page.pagination.has_prev is True


def test_get_detail_returns_order_and_payment_fields(session: Session) -> None:
    request = _make_cancel_request(session, payment_provider="MOCK")
    session.commit()

    detail = get_admin_cancel_request(session, request.request_code)

    assert detail.request_code == request.request_code
    assert detail.order_status == "CANCEL_REQUESTED"
    assert detail.payment_status == "APPROVED"
    assert detail.payment_provider == "MOCK"
    assert detail.product_summary == "상품A"
    assert detail.total_amount == 10000
    assert detail.currency == "KRW"


def test_get_detail_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        get_admin_cancel_request(session, "ocr_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CANCEL_REQUEST_NOT_FOUND"


def test_list_ties_on_requested_at_break_by_id_descending(session: Session) -> None:
    same_time = datetime.now(UTC)
    codes = [_make_cancel_request(session, requested_at=same_time).request_code for _ in range(3)]
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert [item.request_code for item in response.items] == list(reversed(codes))


def test_list_falls_back_to_user_id_display_when_nickname_missing(session: Session) -> None:
    request = _make_cancel_request(session, display_name=None)
    session.commit()

    response = list_admin_cancel_requests(session, status=None, page_size=20)

    assert response.items[0].customer_display == f"user_{request.user_id}"


def test_get_detail_with_missing_payment_has_null_fields_and_no_actions(session: Session) -> None:
    request = _make_cancel_request(session, payment_status=None)
    session.commit()

    detail = get_admin_cancel_request(session, request.request_code)

    assert detail.payment_status is None
    assert detail.payment_provider is None
    assert detail.available_actions == []


def test_get_detail_multiple_products_summarizes_with_count(session: Session) -> None:
    request = _make_cancel_request(session, item_count=3)
    session.commit()

    detail = get_admin_cancel_request(session, request.request_code)

    assert detail.product_summary == "상품A 외 2개"
