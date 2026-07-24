import hashlib
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.models.commerce import Inventory, InventoryMovement, Order, OrderItem, Payment, PaymentAttempt, PaymentEvent
from app.schemas.common import ApiError
from app.schemas.payment import PaymentActionResponse, TossPaymentConfirmRequest
from app.services.pending_payment_terminal_service import (
    PendingPaymentTerminationSpec,
    terminate_pending_payment,
)
from app.services.toss_payments_client import TossPaymentsClientError


ORDER_STATUS_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_STATUS_PAID = "PAID"
ORDER_STATUS_PAYMENT_FAILED = "PAYMENT_FAILED"
PAYMENT_STATUS_READY = "READY"
PAYMENT_STATUS_CONFIRMING = "CONFIRMING"
PAYMENT_STATUS_UNKNOWN = "UNKNOWN"
PAYMENT_STATUS_APPROVED = "APPROVED"
PAYMENT_STATUS_FAILED = "FAILED"
PAYMENT_PROVIDER_MOCK = "MOCK"
PAYMENT_PROVIDER_TOSS = "TOSS"


class TossConfirmClient(Protocol):
    def confirm_payment(self, *, payment_key: str, order_code: str, amount: int) -> dict[str, Any]:
        pass


def confirm_mock_payment(
    session: Session,
    user: User,
    payment_code: str,
) -> PaymentActionResponse:
    started_at = current_time()
    try:
        payment, order = _load_user_payment(session, user.id, payment_code)
        _require_payment_provider(payment, PAYMENT_PROVIDER_MOCK)
        if payment.status == PAYMENT_STATUS_APPROVED and order.status == ORDER_STATUS_PAID:
            response = _to_response(order, payment)
            _log_payment_confirm_completed(
                started_at,
                payment=payment,
                order=order,
                confirmed_quantity_total=0,
                idempotent_replay=True,
            )
            return response

        _require_status(
            order.status == ORDER_STATUS_PENDING_PAYMENT,
            "ORDER_NOT_PENDING_PAYMENT",
            "Order is not pending payment.",
        )
        _require_status(
            payment.status == PAYMENT_STATUS_READY,
            "PAYMENT_NOT_READY",
            "Payment is not ready.",
        )

        now = datetime.now(UTC)
        if order.payment_expires_at is not None and _as_utc(order.payment_expires_at) <= now:
            raise ApiError(409, "PAYMENT_EXPIRED", "Payment window has expired.")

        response = _approve_payment(
            session,
            payment=payment,
            order=order,
            event_type="MOCK_PAYMENT_APPROVED",
            event_id=f"mock_confirm:{payment.payment_code}",
            payload={"source": "mock_confirm"},
            now=now,
            started_at=started_at,
        )
        return response
    except ApiError as exc:
        _log_payment_confirm_failed(
            started_at,
            provider="MOCK",
            amount=None,
            error_code=exc.code,
        )
        raise


def confirm_toss_payment(
    session: Session,
    user: User,
    request: TossPaymentConfirmRequest,
    toss_client: TossConfirmClient,
) -> PaymentActionResponse:
    started_at = current_time()
    try:
        payment_key = request.payment_key.strip()
        order_code = request.order_code.strip()
        if not payment_key or not order_code:
            raise ApiError(400, "INVALID_TOSS_CONFIRM_REQUEST", "payment_key and order_code are required.")

        payment, order = _load_user_payment_by_order_code(session, user.id, order_code, for_update=False)
        now = datetime.now(UTC)
        if _is_approved_payment(payment, order):
            _require_same_provider_payment_key(payment, payment_key)
            response = _to_response(order, payment)
            _log_payment_confirm_completed(
                started_at,
                payment=payment,
                order=order,
                confirmed_quantity_total=0,
                idempotent_replay=True,
            )
            return response
        _require_toss_confirmable(payment, order, request.amount, now)

        attempt = _start_toss_confirm_attempt(session, payment, request, now)
        session.commit()

        try:
            toss_response = toss_client.confirm_payment(
                payment_key=payment_key,
                order_code=order_code,
                amount=request.amount,
            )
        except TossPaymentsClientError as exc:
            _finish_toss_confirm_attempt(
                session,
                attempt_code=attempt.attempt_code,
                payment_id=payment.id,
                status=PAYMENT_STATUS_UNKNOWN if exc.code == "TOSS_CONFIRM_REQUEST_FAILED" else PAYMENT_STATUS_FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            raise ApiError(502, "TOSS_CONFIRM_FAILED", exc.message) from exc
        try:
            _validate_toss_confirm_response(toss_response, payment_key, order_code, request.amount)
        except ApiError as exc:
            _finish_toss_confirm_attempt(
                session,
                attempt_code=attempt.attempt_code,
                payment_id=payment.id,
                status=PAYMENT_STATUS_FAILED,
                error_code=exc.code,
                error_message=exc.message,
                response_summary=_build_toss_event_payload(toss_response),
            )
            raise

        session.expire_all()
        payment, order = _load_user_payment_by_order_code(session, user.id, order_code, for_update=True)
        now = datetime.now(UTC)
        if _is_approved_payment(payment, order):
            _require_same_provider_payment_key(payment, payment_key)
            response = _to_response(order, payment)
            _log_payment_confirm_completed(
                started_at,
                payment=payment,
                order=order,
                confirmed_quantity_total=0,
                idempotent_replay=True,
            )
            return response
        _require_toss_confirmable(payment, order, request.amount, now, allow_confirming=True)

        payment.provider_payment_key = payment_key
        payment.provider_order_id = order_code
        response = _approve_payment(
            session,
            payment=payment,
            order=order,
            event_type="TOSS_PAYMENT_APPROVED",
            event_id=_build_provider_event_id("toss_confirm", payment_key),
            payload=_build_toss_event_payload(toss_response),
            now=now,
            started_at=started_at,
        )
        _finish_toss_confirm_attempt(
            session,
            attempt_code=attempt.attempt_code,
            payment_id=payment.id,
            status=PAYMENT_STATUS_APPROVED,
            response_summary=_build_toss_event_payload(toss_response),
        )
        return response
    except ApiError as exc:
        _log_payment_confirm_failed(
            started_at,
            provider=PAYMENT_PROVIDER_TOSS,
            amount=request.amount,
            error_code=exc.code,
        )
        raise


def fail_mock_payment(
    session: Session,
    user: User,
    payment_code: str,
) -> PaymentActionResponse:
    started_at = current_time()
    try:
        payment, order = _load_user_payment(session, user.id, payment_code)
        _require_payment_provider(payment, PAYMENT_PROVIDER_MOCK)
        if payment.status == PAYMENT_STATUS_FAILED and order.status == ORDER_STATUS_PAYMENT_FAILED:
            response = _to_response(order, payment)
            _log_payment_fail_completed(
                started_at,
                payment=payment,
                order=order,
                released_quantity_total=0,
                restored_quantity_total=0,
                restore_overflow_quantity_total=0,
                idempotent_replay=True,
            )
            return response

        _require_status(
            order.status == ORDER_STATUS_PENDING_PAYMENT,
            "ORDER_NOT_PENDING_PAYMENT",
            "Order is not pending payment.",
        )
        _require_status(
            payment.status == PAYMENT_STATUS_READY,
            "PAYMENT_NOT_READY",
            "Payment is not ready.",
        )

        now = datetime.now(UTC)
        termination = terminate_pending_payment(
            session,
            payment=payment,
            order=order,
            spec=PendingPaymentTerminationSpec(
                order_status=ORDER_STATUS_PAYMENT_FAILED,
                payment_status=PAYMENT_STATUS_FAILED,
                payment_timestamp_field="failed_at",
                order_timestamp_field=None,
                event_type="MOCK_PAYMENT_FAILED",
                event_id=f"mock_fail:{payment.payment_code}",
                event_source="mock_fail",
                event_reason="payment_failed",
                inventory_reason="payment failed reservation release",
            ),
            now=now,
        )
        session.flush()
        response = _to_response(order, payment)
        _log_payment_fail_completed(
            started_at,
            payment=payment,
            order=order,
            released_quantity_total=termination.released_quantity_total,
            restored_quantity_total=termination.restored_quantity_total,
            restore_overflow_quantity_total=termination.restore_overflow_quantity_total,
            idempotent_replay=False,
        )
        return response
    except ApiError as exc:
        _log_payment_fail_failed(started_at, provider="MOCK", error_code=exc.code)
        raise


def _load_user_payment(session: Session, user_id: int, payment_code: str) -> tuple[Payment, Order]:
    normalized_code = payment_code.strip()
    if not normalized_code:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Payment was not found.")
    row = session.execute(
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(
            Payment.payment_code == normalized_code,
            Order.user_id == user_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Payment was not found.")
    return row


def _load_user_payment_by_order_code(
    session: Session,
    user_id: int,
    order_code: str,
    *,
    for_update: bool,
) -> tuple[Payment, Order]:
    normalized_code = order_code.strip()
    if not normalized_code:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    statement = (
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(
            Order.order_code == normalized_code,
            Order.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).one_or_none()
    if row is None:
        raise ApiError(404, "ORDER_NOT_FOUND", "Order was not found.")
    return row


def _require_status(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ApiError(409, code, message)


def _require_payment_provider(payment: Payment, expected_provider: str) -> None:
    _require_status(
        payment.provider == expected_provider,
        "PAYMENT_PROVIDER_MISMATCH",
        f"Payment provider is not {expected_provider}.",
    )


def _is_approved_payment(payment: Payment, order: Order) -> bool:
    return payment.status == PAYMENT_STATUS_APPROVED and order.status == ORDER_STATUS_PAID


def _require_same_provider_payment_key(payment: Payment, payment_key: str) -> None:
    if payment.provider_payment_key is not None and payment.provider_payment_key != payment_key:
        raise ApiError(409, "PAYMENT_KEY_CONFLICT", "Payment was already approved with another payment key.")


def _require_toss_confirmable(
    payment: Payment,
    order: Order,
    amount: int,
    now: datetime,
    *,
    allow_confirming: bool = False,
) -> None:
    _require_status(
        payment.provider == PAYMENT_PROVIDER_TOSS,
        "PAYMENT_PROVIDER_MISMATCH",
        "Payment provider is not TOSS.",
    )
    _require_status(
        order.status == ORDER_STATUS_PENDING_PAYMENT,
        "ORDER_NOT_PENDING_PAYMENT",
        "Order is not pending payment.",
    )
    _require_status(
        payment.status == PAYMENT_STATUS_READY or (allow_confirming and payment.status == PAYMENT_STATUS_CONFIRMING),
        "PAYMENT_NOT_READY",
        "Payment is not ready.",
    )
    _require_status(
        amount == order.total_amount and amount == payment.amount,
        "PAYMENT_AMOUNT_MISMATCH",
        "Payment amount does not match order total.",
    )
    if order.payment_expires_at is not None and _as_utc(order.payment_expires_at) <= now:
        raise ApiError(409, "PAYMENT_EXPIRED", "Payment window has expired.")


def _start_toss_confirm_attempt(
    session: Session,
    payment: Payment,
    request: TossPaymentConfirmRequest,
    now: datetime,
) -> PaymentAttempt:
    attempt_code = _build_toss_attempt_code(request)
    existing = session.execute(
        select(PaymentAttempt).where(
            PaymentAttempt.payment_id == payment.id,
            PaymentAttempt.attempt_code == attempt_code,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "PAYMENT_CONFIRMATION_REPLAY", "This payment confirmation request was already processed.")

    payment.status = PAYMENT_STATUS_CONFIRMING
    payment.updated_at = now
    attempt = PaymentAttempt(
        payment_id=payment.id,
        attempt_code=attempt_code,
        operation="CONFIRM",
        provider=PAYMENT_PROVIDER_TOSS,
        status=PAYMENT_STATUS_CONFIRMING,
        provider_payment_key=request.payment_key.strip(),
        provider_idempotency_key=attempt_code,
        request_summary_json={
            "order_code": request.order_code.strip(),
            "amount": request.amount,
        },
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(attempt)
    session.flush()
    return attempt


def _finish_toss_confirm_attempt(
    session: Session,
    *,
    attempt_code: str,
    payment_id: int,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    response_summary: dict[str, Any] | None = None,
) -> None:
    attempt = session.execute(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.payment_id == payment_id,
            PaymentAttempt.attempt_code == attempt_code,
        )
        .with_for_update()
    ).scalar_one()
    payment = session.execute(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    ).scalar_one()
    now = datetime.now(UTC)
    attempt.status = status
    attempt.provider_error_code = error_code
    attempt.provider_error_message = error_message
    attempt.response_summary_json = response_summary
    attempt.completed_at = now
    attempt.updated_at = now
    if status in {PAYMENT_STATUS_FAILED, PAYMENT_STATUS_UNKNOWN}:
        payment.status = status
        payment.updated_at = now
        payment.failed_at = now if status == PAYMENT_STATUS_FAILED else payment.failed_at
    session.commit()


def _build_toss_attempt_code(request: TossPaymentConfirmRequest) -> str:
    raw = f"{request.order_code.strip()}:{request.payment_key.strip()}:{request.amount}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"toss_confirm:{digest}"


def _validate_toss_confirm_response(
    payload: dict[str, Any],
    payment_key: str,
    order_code: str,
    amount: int,
) -> None:
    if not isinstance(payload, dict):
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss confirm response is invalid.")
    required_fields = {"paymentKey", "orderId", "totalAmount", "status"}
    if not required_fields.issubset(payload):
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss confirm response is incomplete.")
    if payload["paymentKey"] != payment_key:
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss payment key mismatch.")
    if payload["orderId"] != order_code:
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss order id mismatch.")
    provider_amount = payload["totalAmount"]
    if type(provider_amount) is not int:
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss amount is invalid.")
    if provider_amount != amount:
        raise ApiError(502, "TOSS_CONFIRM_INVALID_RESPONSE", "Toss amount mismatch.")
    if payload["status"] != "DONE":
        raise ApiError(502, "TOSS_CONFIRM_NOT_DONE", "Toss payment was not completed.")


def _build_provider_event_id(event_type: str, provider_identifier: str) -> str:
    identifier_hash = hashlib.sha256(provider_identifier.encode("utf-8")).hexdigest()
    return f"{event_type}:{identifier_hash}"


def _build_toss_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "toss_confirm",
        "payment_key": payload.get("paymentKey"),
        "order_id": payload.get("orderId"),
        "status": payload.get("status"),
        "total_amount": payload.get("totalAmount"),
        "method": payload.get("method"),
        "approved_at": payload.get("approvedAt"),
        "requested_at": payload.get("requestedAt"),
    }


def _approve_payment(
    session: Session,
    *,
    payment: Payment,
    order: Order,
    event_type: str,
    event_id: str,
    payload: dict[str, Any],
    now: datetime,
    started_at: float,
) -> PaymentActionResponse:
    order_items = _load_order_items(session, order.id)
    inventories = _load_inventories_for_update(session, [item.product_id for item in order_items])
    confirmed_quantity_total = _quantity_total(order_items)
    _confirm_reserved_inventory(session, order, order_items, inventories, now)

    old_payment_status = payment.status
    payment.status = PAYMENT_STATUS_APPROVED
    payment.approved_at = now
    payment.updated_at = now
    order.status = ORDER_STATUS_PAID
    order.paid_at = now
    order.updated_at = now
    _record_payment_event(
        session,
        payment=payment,
        order=order,
        event_type=event_type,
        event_id=event_id,
        status_before=old_payment_status,
        status_after=payment.status,
        payload=payload,
        now=now,
    )
    session.flush()
    response = _to_response(order, payment)
    _log_payment_confirm_completed(
        started_at,
        payment=payment,
        order=order,
        confirmed_quantity_total=confirmed_quantity_total,
        idempotent_replay=False,
    )
    return response


def _load_order_items(session: Session, order_id: int) -> list[OrderItem]:
    items = session.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.id.asc())
    ).scalars().all()
    if not items:
        raise ApiError(409, "ORDER_ITEMS_NOT_FOUND", "Order items were not found.")
    return list(items)


def _load_inventories_for_update(session: Session, product_ids: list[int]) -> dict[int, Inventory]:
    rows = session.execute(
        select(Inventory)
        .where(Inventory.product_id.in_(product_ids))
        .with_for_update()
    ).scalars()
    inventories = {int(row.product_id): row for row in rows}
    if len(inventories) != len(set(product_ids)):
        raise ApiError(409, "STOCK_UNKNOWN", "Product stock is unavailable.")
    return inventories


def _confirm_reserved_inventory(
    session: Session,
    order: Order,
    order_items: list[OrderItem],
    inventories: dict[int, Inventory],
    now: datetime,
) -> None:
    for item in order_items:
        inventory = inventories[int(item.product_id)]
        _require_inventory_can_release(inventory, item.quantity)
        if inventory.stock_quantity < item.quantity:
            raise ApiError(409, "INVENTORY_STATE_INVALID", "Inventory stock is lower than order quantity.")
        inventory.stock_quantity -= item.quantity
        inventory.reserved_quantity -= item.quantity
        inventory.updated_at = now
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=item.product_id,
                movement_type="SALE_CONFIRM",
                quantity_delta=-item.quantity,
                stock_after=inventory.stock_quantity,
                reason="payment approved stock deduction",
                reference_type="order",
                reference_id=order.order_code,
                created_at=now,
            )
        )


def _require_inventory_can_release(inventory: Inventory, quantity: int) -> None:
    if inventory.reserved_quantity < quantity:
        raise ApiError(409, "INVENTORY_RESERVATION_INVALID", "Reserved inventory is lower than order quantity.")


def _record_payment_event(
    session: Session,
    *,
    payment: Payment,
    order: Order,
    event_type: str,
    event_id: str,
    status_before: str,
    status_after: str,
    payload: dict,
    now: datetime,
) -> None:
    session.add(
        PaymentEvent(
            payment_id=payment.id,
            order_id=order.id,
            event_type=event_type,
            event_id=event_id,
            provider=payment.provider,
            provider_payment_key=payment.provider_payment_key,
            provider_order_id=payment.provider_order_id,
            amount=payment.amount,
            currency=payment.currency,
            status_before=status_before,
            status_after=status_after,
            raw_payload_json=payload,
            created_at=now,
        )
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_response(order: Order, payment: Payment) -> PaymentActionResponse:
    return PaymentActionResponse(
        order_code=order.order_code,
        payment_code=payment.payment_code,
        order_status=order.status,
        payment_status=payment.status,
        approved_at=payment.approved_at,
        failed_at=payment.failed_at,
    )


def _quantity_total(order_items: list[OrderItem]) -> int:
    return sum(item.quantity for item in order_items)


def _log_payment_confirm_completed(
    started_at: float,
    *,
    payment: Payment,
    order: Order,
    confirmed_quantity_total: int,
    idempotent_replay: bool,
) -> None:
    log_performance_event(
        "payment_confirm_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "provider": payment.provider,
            "amount": payment.amount,
            "order_status": order.status,
            "payment_status": payment.status,
            "confirmed_quantity_total": confirmed_quantity_total,
            "idempotent_replay": idempotent_replay,
        },
    )


def _log_payment_confirm_failed(
    started_at: float,
    *,
    provider: str,
    amount: int | None,
    error_code: str,
) -> None:
    log_performance_event(
        "payment_confirm_failed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "provider": provider,
            "amount": amount,
            "error_code": error_code,
        },
    )


def _log_payment_fail_completed(
    started_at: float,
    *,
    payment: Payment,
    order: Order,
    released_quantity_total: int,
    restored_quantity_total: int,
    restore_overflow_quantity_total: int,
    idempotent_replay: bool,
) -> None:
    log_performance_event(
        "payment_fail_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "provider": payment.provider,
            "payment_status": payment.status,
            "order_status": order.status,
            "released_quantity_total": released_quantity_total,
            "restored_quantity_total": restored_quantity_total,
            "restore_overflow_quantity_total": restore_overflow_quantity_total,
            "idempotent_replay": idempotent_replay,
        },
    )


def _log_payment_fail_failed(started_at: float, *, provider: str, error_code: str) -> None:
    log_performance_event(
        "payment_fail_failed",
        duration_ms=elapsed_ms(started_at),
        metadata={
            "provider": provider,
            "error_code": error_code,
        },
    )
