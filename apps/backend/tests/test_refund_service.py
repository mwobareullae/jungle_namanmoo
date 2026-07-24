from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.commerce import (
    Inventory,
    InventoryMovement,
    Order,
    OrderClaim,
    OrderClaimEvent,
    OrderClaimItem,
    OrderItem,
    Payment,
    PaymentEvent,
    PaymentRefund,
)
from app.schemas.claim import OrderClaimCreateRequest, OrderClaimItemRequest
from app.schemas.common import ApiError
from app.services.order_claim_service import create_claim
from app.services.refund_service import process_claim_refund, recompute_order_item_status


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


def test_mock_refund_updates_payment_restock_and_is_idempotent(db_engine: Engine) -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        user = User(email="refund@example.com", display_name="refund-user")
        session.add(user)
        session.flush()
        order = Order(
            order_code="ord_refund_test",
            user_id=user.id,
            idempotency_key="refund-test-key",
            status="DELIVERED",
            subtotal_amount=1000,
            shipping_fee=0,
            discount_amount=0,
            total_amount=1000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
            delivered_at=now,
        )
        session.add(order)
        session.flush()
        item = OrderItem(
            order_id=order.id,
            product_id=1,
            seller_id=1,
            product_name_snapshot="Test product",
            brand_name_snapshot="Test brand",
            seller_name_snapshot="Test seller",
            unit_price=1000,
            quantity=1,
            line_subtotal=1000,
            line_discount_amount=0,
            line_total=1000,
            currency="KRW",
            status="DELIVERED",
        )
        session.add(item)
        payment = Payment(
            payment_code="pay_refund_test",
            order_id=order.id,
            provider="MOCK",
            status="APPROVED",
            amount=1000,
            currency="KRW",
            approved_at=now,
        )
        session.add(payment)
        inventory = Inventory(
            product_id=1,
            stock_quantity=4,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="ON_SALE",
            inventory_source="TEST",
        )
        session.add(inventory)
        session.flush()
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        first = process_claim_refund(session, claim.claim_code, restock=True, now=now)
        session.commit()
        second = process_claim_refund(session, claim.claim_code, restock=True, now=now)
        session.commit()

        saved_payment = session.execute(select(Payment)).scalar_one()
        saved_inventory = session.execute(select(Inventory)).scalar_one()
        saved_item = session.execute(select(OrderItem).where(OrderItem.id == item.id)).scalar_one()
        movements = session.execute(
            select(InventoryMovement).where(InventoryMovement.reference_id == claim.claim_code)
        ).scalars().all()
        refunds = session.execute(select(PaymentRefund)).scalars().all()
        events = session.execute(
            select(OrderClaimEvent).where(OrderClaimEvent.claim_id == claim.id).order_by(OrderClaimEvent.id.asc())
        ).scalars().all()

    assert first.id == second.id
    assert saved_payment.status == "REFUNDED"
    assert saved_inventory.stock_quantity == 5
    assert len(movements) == 1
    assert movements[0].movement_type == "RETURN_RESTOCK"
    assert len(refunds) == 1
    assert saved_item.status == "RETURNED"  # 전체 수량이 단일 유형(RETURN)으로 완료됨
    # 승인(REQUESTED->APPROVED 수동 설정은 이벤트 없음) + 완료 이벤트만 존재, 재호출로 중복 안 됨
    completed_events = [event for event in events if event.to_status == "COMPLETED"]
    assert len(completed_events) == 1
    assert completed_events[0].actor_type == "ADMIN"
    assert completed_events[0].actor_id is None


_seq = 0


def _seed_order_with_item(
    session: Session,
    *,
    item_quantity: int = 1,
    unit_price: int = 1000,
    payment_amount: int | None = None,
    provider: str = "MOCK",
) -> tuple[datetime, User, Order, OrderItem, Payment]:
    global _seq
    _seq += 1
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    user = User(email=f"refundseed{_seq}@example.com", display_name=None)
    session.add(user)
    session.flush()
    order_amount = unit_price * item_quantity
    order = Order(
        order_code=f"ord_refundseed_{_seq}",
        user_id=user.id,
        idempotency_key=f"refundseed-{_seq}-key",
        status="DELIVERED",
        subtotal_amount=order_amount,
        shipping_fee=0,
        discount_amount=0,
        total_amount=order_amount,
        currency="KRW",
        item_count=1,
        total_quantity=item_quantity,
        delivered_at=now,
    )
    session.add(order)
    session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=_seq,
        seller_id=1,
        product_name_snapshot="Test product",
        brand_name_snapshot="Test brand",
        seller_name_snapshot="Test seller",
        unit_price=unit_price,
        quantity=item_quantity,
        line_subtotal=order_amount,
        line_discount_amount=0,
        line_total=order_amount,
        currency="KRW",
        status="DELIVERED",
    )
    session.add(item)
    payment = Payment(
        payment_code=f"pay_refundseed_{_seq}",
        order_id=order.id,
        provider=provider,
        status="APPROVED",
        amount=payment_amount if payment_amount is not None else order_amount,
        currency="KRW",
        approved_at=now,
    )
    session.add(payment)
    session.add(
        Inventory(
            product_id=_seq,
            stock_quantity=10,
            reserved_quantity=0,
            safety_stock=0,
            sales_status="ON_SALE",
            inventory_source="TEST",
        )
    )
    session.flush()
    return now, user, order, item, payment


def test_toss_payment_refund_succeeds_via_admin_simulation_and_logs_event(db_engine: Engine) -> None:
    # TOSS 로 결제된 배송완료 주문도 관리자 완료 처리(반품/환불)가 가능해야 한다 — 실제 PG 호출
    # 없이 내부 상태만 정리하고, 그 사실을 PaymentEvent 로 남긴다(취소 승인의 TOSS 시뮬레이션과 동일 패턴).
    with Session(db_engine) as session:
        now, user, order, item, payment = _seed_order_with_item(session, provider="TOSS")
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        refund = process_claim_refund(session, claim.claim_code, restock=False, simulate_toss_refund=True, now=now)
        session.commit()
        refund_provider = refund.provider

        saved_payment = session.execute(select(Payment).where(Payment.id == payment.id)).scalar_one()
        events = session.execute(
            select(PaymentEvent).where(PaymentEvent.payment_id == payment.id)
        ).scalars().all()

    assert refund_provider == "TOSS"
    assert saved_payment.status == "REFUNDED"
    assert len(events) == 1
    assert events[0].event_type == "ADMIN_TOSS_REFUND_SIMULATED"
    assert events[0].raw_payload_json["external_provider_called"] is False


def test_toss_payment_refund_rejected_without_simulation_flag(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, provider="TOSS")
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        with pytest.raises(ApiError) as exc_info:
            process_claim_refund(session, claim.claim_code, restock=False, now=now)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "REFUND_PROVIDER_UNSUPPORTED"


def test_unsupported_provider_refund_rejected_even_with_simulation_flag(db_engine: Engine) -> None:
    # simulate_toss_refund 는 이름 그대로 TOSS 전용 예외다 — KAKAO_PAY 같은 다른 PG 는
    # 플래그를 켜도 여전히 지원되지 않아야 한다(무분별하게 모든 PG 를 우회하지 않도록).
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, provider="KAKAO_PAY")
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        with pytest.raises(ApiError) as exc_info:
            process_claim_refund(session, claim.claim_code, restock=False, simulate_toss_refund=True, now=now)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "REFUND_PROVIDER_UNSUPPORTED"


def test_partial_quantity_claim_keeps_order_item_delivered(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=2, unit_price=1000)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        process_claim_refund(session, claim.claim_code, restock=False, now=now)
        session.commit()

        saved_item = session.execute(select(OrderItem).where(OrderItem.id == item.id)).scalar_one()

    assert saved_item.status == "DELIVERED"  # 주문 수량 2개 중 1개만 완료 — 아직 확정 상태 아님


def test_full_quantity_via_split_claims_marks_order_item_returned(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=2, unit_price=1000)
        first_claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        first_claim.status = "IN_PROGRESS"
        session.commit()
        process_claim_refund(session, first_claim.claim_code, restock=False, now=now)
        session.commit()

        second_claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="SIZE",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        second_claim.status = "IN_PROGRESS"
        session.commit()
        process_claim_refund(session, second_claim.claim_code, restock=False, now=now)
        session.commit()

        saved_item = session.execute(select(OrderItem).where(OrderItem.id == item.id)).scalar_one()

    assert saved_item.status == "RETURNED"  # 두 클레임 합쳐 전체 수량 완료 + 동일 유형(RETURN)


def test_mixed_claim_types_keep_order_item_delivered(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=2, unit_price=1000)
        # EXCHANGE 클레임 완료는 이 서비스가 처리하지 않으므로(관리자 서비스가 별도 분기로 처리),
        # 여기서는 이미 COMPLETED 된 EXCHANGE 클레임이 있는 상태를 직접 만들어 혼합 시나리오를 검증한다.
        exchange_claim = OrderClaim(
            claim_code=f"clm_refund_exchange_{item.id}",
            order_id=order.id,
            user_id=user.id,
            claim_type="EXCHANGE",
            status="COMPLETED",
            reason_code="SIZE",
            requested_at=now,
            processed_at=now,
            completed_at=now,
        )
        session.add(exchange_claim)
        session.flush()
        session.add(
            OrderClaimItem(claim_id=exchange_claim.id, order_item_id=item.id, quantity=1, resolution="EXCHANGE")
        )
        session.flush()

        return_claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="RETURN",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        return_claim.status = "IN_PROGRESS"
        session.commit()
        process_claim_refund(session, return_claim.claim_code, restock=False, now=now)
        session.commit()

        saved_item = session.execute(select(OrderItem).where(OrderItem.id == item.id)).scalar_one()

    # 전체 수량(2)은 소진됐지만 RETURN + EXCHANGE 로 결과가 섞여 있어 확정 상태로 바꾸지 않는다.
    assert saved_item.status == "DELIVERED"


def test_cumulative_refund_exceeding_payment_amount_returns_409(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        now, user, order, item, payment = _seed_order_with_item(
            session, item_quantity=2, unit_price=1000, payment_amount=1500
        )
        first_claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        first_claim.status = "IN_PROGRESS"
        session.commit()
        process_claim_refund(session, first_claim.claim_code, restock=False, now=now)
        session.commit()

        second_claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="SIZE",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        second_claim.status = "IN_PROGRESS"
        session.commit()

        with pytest.raises(ApiError) as exc_info:
            process_claim_refund(session, second_claim.claim_code, restock=False, now=now)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "INVALID_REFUND_AMOUNT"


def test_refund_claim_type_rejects_restock(db_engine: Engine) -> None:
    # restock 은 RETURN 에만 의미가 있다 — REFUND 요청이 restock=True 를 보내면
    # 실제로 재고가 복구되면 안 되므로 요청 자체를 거부해야 한다.
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=1, unit_price=1000)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "IN_PROGRESS"
        session.commit()

        with pytest.raises(ApiError) as exc_info:
            process_claim_refund(session, claim.claim_code, restock=True, now=now)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "RESTOCK_NOT_APPLICABLE"


def test_process_claim_refund_rejects_approved_claim_not_yet_in_progress(db_engine: Engine) -> None:
    # 확정 계약은 APPROVED->IN_PROGRESS->COMPLETED 순서를 강제한다 — APPROVED 에서
    # 바로 완료 처리를 시도하면 거부해야 한다(이전에는 APPROVED 도 허용했던 버그).
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=1, unit_price=1000)
        claim = create_claim(
            session,
            user,
            OrderClaimCreateRequest(
                order_code=order.order_code,
                claim_type="REFUND",
                reason_code="DAMAGED",
                items=[OrderClaimItemRequest(order_item_id=item.id, quantity=1)],
            ),
            now=now,
        )
        claim.status = "APPROVED"
        session.commit()

        with pytest.raises(ApiError) as exc_info:
            process_claim_refund(session, claim.claim_code, restock=False, now=now)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CLAIM_NOT_IN_PROGRESS"


def test_recompute_order_item_status_keeps_delivered_when_completed_quantity_exceeds_ordered(
    db_engine: Engine,
) -> None:
    # 완료 수량 합계가 주문 수량을 "초과"하는 것은 정상 흐름에서는 나오면 안 되는 데이터 불일치다.
    # 이럴 때도 확정 상태로 넘기면 오류를 숨기게 되므로, 정확히 같을 때만 확정하고
    # 그 외(부족·초과 모두)에는 DELIVERED 를 유지해야 한다.
    with Session(db_engine) as session:
        now, user, order, item, _payment = _seed_order_with_item(session, item_quantity=1, unit_price=1000)
        claim = OrderClaim(
            claim_code="clm_overcount_test",
            order_id=order.id,
            user_id=user.id,
            claim_type="RETURN",
            status="COMPLETED",
            reason_code="DAMAGED",
            refund_amount=1000,
            requested_at=now,
            processed_at=now,
            completed_at=now,
        )
        session.add(claim)
        session.flush()
        # item.quantity 는 1인데 완료된 클레임 수량 합은 2 — 데이터 불일치 상황을 직접 구성한다.
        session.add(OrderClaimItem(claim_id=claim.id, order_item_id=item.id, quantity=2, resolution="REFUND"))
        session.commit()

        recompute_order_item_status(session, item, now)
        session.commit()

        saved_item = session.execute(select(OrderItem).where(OrderItem.id == item.id)).scalar_one()

    assert saved_item.status == "DELIVERED"
