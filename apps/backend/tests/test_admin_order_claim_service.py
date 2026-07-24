"""관리자 클레임 목록·상세 조회 서비스 테스트 (M1.5-B, 조회 전용)."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderClaim, OrderClaimEvent, OrderClaimItem, OrderItem, Payment
from app.schemas.common import ApiError
from app.services.admin.order_claim_service import get_admin_claim, list_admin_claims


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


def _make_claim(
    session: Session,
    *,
    claim_type: str = "REFUND",
    status: str = "REQUESTED",
    reason_code: str = "DAMAGED",
    refund_amount: int | None = 10000,
    display_name: str | None = None,  # users.display_name UNIQUE — 기본 NULL(다중 허용)
    requested_at: datetime | None = None,
    processed_at: datetime | None = None,
    completed_at: datetime | None = None,
    item_count: int = 1,
    with_events: bool = True,
    provider: str | None = "MOCK",
) -> OrderClaim:
    global _seq
    _seq += 1
    now = requested_at or datetime.now(UTC)
    user = User(email=f"claimadmin{_seq}@example.com", display_name=display_name, status="ACTIVE", role="USER")
    session.add(user)
    session.flush()
    order = Order(
        order_code=f"ord_claimadmin_{_seq}",
        user_id=user.id,
        idempotency_key=f"key_claimadmin_{_seq}",
        status="DELIVERED",
        subtotal_amount=10000 * item_count,
        total_amount=10000 * item_count,
        currency="KRW",
        item_count=item_count,
        total_quantity=item_count,
        ordered_at=now,
        delivered_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    order_items = []
    for idx in range(item_count):
        order_item = OrderItem(
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
            status="DELIVERED",
            created_at=now,
            updated_at=now,
        )
        session.add(order_item)
        order_items.append(order_item)
    if provider is not None:
        session.add(
            Payment(
                payment_code=f"pay_claimadmin_{_seq}",
                order_id=order.id,
                provider=provider,
                status="APPROVED",
                amount=10000 * item_count,
                currency="KRW",
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()

    claim = OrderClaim(
        claim_code=f"clm_test_{_seq}",
        order_id=order.id,
        user_id=user.id,
        claim_type=claim_type,
        status=status,
        reason_code=reason_code,
        refund_amount=refund_amount,
        requested_at=now,
        processed_at=processed_at,
        completed_at=completed_at,
        created_at=now,
        updated_at=now,
    )
    session.add(claim)
    session.flush()
    resolution = "EXCHANGE" if claim_type == "EXCHANGE" else "REFUND"
    for order_item in order_items:
        session.add(
            OrderClaimItem(
                claim_id=claim.id,
                order_item_id=order_item.id,
                quantity=1,
                resolution=resolution,
                created_at=now,
            )
        )
    if with_events:
        session.add(
            OrderClaimEvent(
                claim_id=claim.id,
                from_status=None,
                to_status="REQUESTED",
                actor_type="USER",
                actor_id=user.id,
                reason=reason_code,
                created_at=now,
            )
        )
    session.flush()
    return claim


def test_list_returns_requested_with_approve_and_reject_actions(session: Session) -> None:
    _make_claim(session, status="REQUESTED", display_name="닉네임")
    session.commit()

    response = list_admin_claims(session, status=None, claim_type=None, page=1, page_size=20)

    assert len(response.items) == 1
    item = response.items[0]
    assert item.status == "REQUESTED"
    assert item.available_actions == ["APPROVE", "REJECT"]
    assert item.customer_display == "닉네임"
    assert response.total_count == 1
    assert response.page == 1


@pytest.mark.parametrize(
    ("status", "expected_actions"),
    [
        ("REQUESTED", ["APPROVE", "REJECT"]),
        ("APPROVED", ["START"]),
        ("IN_PROGRESS", ["COMPLETE"]),
        ("REJECTED", []),
        ("COMPLETED", []),
        ("WITHDRAWN", []),
    ],
)
def test_list_computes_available_actions_per_status(
    session: Session, status: str, expected_actions: list[str]
) -> None:
    _make_claim(session, status=status)
    session.commit()

    response = list_admin_claims(session, status=None, claim_type=None, page=1, page_size=20)

    assert response.items[0].available_actions == expected_actions


def test_list_filters_by_status_and_claim_type(session: Session) -> None:
    _make_claim(session, status="REQUESTED", claim_type="REFUND")
    _make_claim(session, status="REQUESTED", claim_type="EXCHANGE")
    _make_claim(session, status="APPROVED", claim_type="REFUND")
    session.commit()

    response = list_admin_claims(session, status="REQUESTED", claim_type="EXCHANGE", page=1, page_size=20)

    assert len(response.items) == 1
    assert response.items[0].claim_type == "EXCHANGE"
    assert response.items[0].status == "REQUESTED"


def test_list_rejects_invalid_status(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        list_admin_claims(session, status="NOT_A_STATUS", claim_type=None, page=1, page_size=20)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_CLAIM_STATUS"


def test_list_rejects_invalid_claim_type(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        list_admin_claims(session, status=None, claim_type="NOT_A_TYPE", page=1, page_size=20)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_CLAIM_TYPE"


def test_list_rejects_invalid_page(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        list_admin_claims(session, status=None, claim_type=None, page=0, page_size=20)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_PAGE"


def test_list_rejects_invalid_page_size(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        list_admin_claims(session, status=None, claim_type=None, page=1, page_size=0)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_PAGE_SIZE"


def test_list_paginates_newest_first(session: Session) -> None:
    base_time = datetime.now(UTC)
    codes = [
        _make_claim(session, requested_at=base_time + timedelta(minutes=idx)).claim_code for idx in range(3)
    ]
    session.commit()

    first_page = list_admin_claims(session, status=None, claim_type=None, page=1, page_size=2)
    assert [item.claim_code for item in first_page.items] == [codes[2], codes[1]]
    assert first_page.total_count == 3

    second_page = list_admin_claims(session, status=None, claim_type=None, page=2, page_size=2)
    assert [item.claim_code for item in second_page.items] == [codes[0]]
    assert second_page.total_count == 3


def test_get_detail_returns_items_and_events(session: Session) -> None:
    claim = _make_claim(session, item_count=2)
    session.commit()

    detail = get_admin_claim(session, claim.claim_code)

    assert detail.claim_code == claim.claim_code
    assert detail.order_status == "DELIVERED"
    assert detail.payment_provider == "MOCK"
    assert detail.product_summary == "상품A 외 1개"
    assert len(detail.items) == 2
    assert detail.items[0].resolution == "REFUND"
    assert len(detail.events) == 1
    assert detail.events[0].to_status == "REQUESTED"
    assert detail.events[0].actor_type == "USER"


def test_get_detail_returns_toss_payment_provider(session: Session) -> None:
    claim = _make_claim(session, provider="TOSS")
    session.commit()

    detail = get_admin_claim(session, claim.claim_code)

    assert detail.payment_provider == "TOSS"


def test_get_detail_payment_provider_is_none_when_payment_missing(session: Session) -> None:
    claim = _make_claim(session, provider=None)
    session.commit()

    detail = get_admin_claim(session, claim.claim_code)

    assert detail.payment_provider is None


def test_get_detail_not_found_raises_404(session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        get_admin_claim(session, "clm_does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "CLAIM_NOT_FOUND"


def test_list_falls_back_to_user_id_display_when_nickname_missing(session: Session) -> None:
    claim = _make_claim(session, display_name=None)
    session.commit()

    response = list_admin_claims(session, status=None, claim_type=None, page=1, page_size=20)

    assert response.items[0].customer_display == f"user_{claim.user_id}"


def test_get_detail_exchange_claim_has_no_refund_amount(session: Session) -> None:
    claim = _make_claim(session, claim_type="EXCHANGE", refund_amount=None)
    session.commit()

    detail = get_admin_claim(session, claim.claim_code)

    assert detail.refund_amount is None
    assert detail.items[0].resolution == "EXCHANGE"
