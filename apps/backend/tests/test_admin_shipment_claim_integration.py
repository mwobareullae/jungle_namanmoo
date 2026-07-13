"""관리자 배송완료 처리 → 고객 반품 가능 여부 통합 테스트.

admin.order_service.complete_delivery() 가 Order.delivered_at 을 채우지 않으면
order_claim_service.get_claim_eligibility() 가 항상 반품 불가로 응답한다
(get_claim_eligibility 는 delivered_at is None 이면 무조건 eligible=False).
이 테스트는 관리자 쪽 배송완료 처리 이후 고객 쪽 반품 가능 판정이 실제로
정상 동작하는지 두 서비스를 이어서 확인한다.
"""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderItem, Payment
from app.services.admin.order_service import complete_delivery
from app.services.order_claim_service import get_claim_eligibility


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


def test_admin_complete_delivery_makes_order_claim_eligible(session: Session) -> None:
    now = datetime.now(UTC)
    user = User(email="claim-integration@example.com", display_name=None, status="ACTIVE", role="USER")
    session.add(user)
    session.flush()
    order = Order(
        order_code="ord_claim_integration",
        user_id=user.id,
        idempotency_key="key_claim_integration",
        status="SHIPPED",
        subtotal_amount=1000,
        total_amount=1000,
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
            product_name_snapshot="상품",
            brand_name_snapshot="브랜드",
            seller_name_snapshot="자사",
            unit_price=1000,
            quantity=1,
            line_subtotal=1000,
            line_discount_amount=0,
            line_total=1000,
            currency="KRW",
            status="SHIPPED",
            created_at=now,
            updated_at=now,
        )
    )
    session.add(
        Payment(
            payment_code="pay_claim_integration",
            order_id=order.id,
            provider="MOCK",
            status="APPROVED",
            amount=1000,
            currency="KRW",
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    # 배송완료 처리 전에는 delivered_at 이 없어 반품 신청 자체가 불가하다.
    before = get_claim_eligibility(session, user, order.order_code)
    assert before.eligible is False
    assert before.reason_code == "CLAIM_NOT_ELIGIBLE"

    complete_delivery(session, order_code=order.order_code)
    session.commit()

    after = get_claim_eligibility(session, user, order.order_code)
    assert after.eligible is True
    assert after.reason_code is None
    assert after.claim_window_ends_at is not None
