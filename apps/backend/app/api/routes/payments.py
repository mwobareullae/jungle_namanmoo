import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.models.commerce import Order, Payment
from app.db.session import get_db
from app.schemas.common import ApiError, ErrorResponse
from app.schemas.event import EventLogCreateRequest
from app.schemas.payment import PaymentActionResponse, TossPaymentConfirmRequest
from app.services.event_service import create_event_log
from app.services.event_tracking import anonymous_user_id_from_request, request_id_from_request, session_id_from_request
from app.services.payment_service import confirm_mock_payment, confirm_toss_payment, fail_mock_payment
from app.services.toss_payments_client import TossPaymentsClient, TossPaymentsClientError


router = APIRouter(tags=["payments"])
logger = logging.getLogger(__name__)


def get_toss_payments_client() -> TossPaymentsClient:
    try:
        return TossPaymentsClient.from_settings()
    except TossPaymentsClientError as exc:
        raise ApiError(500, exc.code, exc.message) from exc


@router.post(
    "/payments/{payment_code}/mock/confirm",
    response_model=PaymentActionResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_mock_payment_confirm(
    payment_code: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> PaymentActionResponse:
    _record_payment_started_event_log(
        session,
        current_user=current_user,
        source="mock_payment_confirm",
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
        payment_code=payment_code,
    )
    response = confirm_mock_payment(session, current_user, payment_code)
    session.commit()
    _record_payment_event_log(
        session,
        current_user=current_user,
        response=response,
        event_name="order_completed",
        source="mock_payment_confirm",
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
    )
    return response


@router.post(
    "/payments/{payment_code}/mock/fail",
    response_model=PaymentActionResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_mock_payment_fail(
    payment_code: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> PaymentActionResponse:
    response = fail_mock_payment(session, current_user, payment_code)
    session.commit()
    _record_payment_event_log(
        session,
        current_user=current_user,
        response=response,
        event_name="payment_failed",
        source="mock_payment_fail",
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
    )
    return response


@router.post(
    "/payments/toss/confirm",
    response_model=PaymentActionResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
def post_toss_payment_confirm(
    request: TossPaymentConfirmRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    toss_client: TossPaymentsClient = Depends(get_toss_payments_client),
) -> PaymentActionResponse:
    fallback_request_id = request_id_from_request(http_request)
    fallback_anonymous_user_id = anonymous_user_id_from_request(http_request)
    fallback_session_id = session_id_from_request(http_request)
    _record_payment_started_event_log(
        session,
        current_user=current_user,
        source="toss_payment_confirm",
        fallback_request_id=fallback_request_id,
        fallback_anonymous_user_id=fallback_anonymous_user_id,
        fallback_session_id=fallback_session_id,
        order_code=request.order_code,
        amount=request.amount,
    )
    try:
        response = confirm_toss_payment(session, current_user, request, toss_client)
    except ApiError as exc:
        session.rollback()
        _record_toss_payment_failed_event_log(
            session,
            current_user=current_user,
            request=request,
            error=exc,
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
        )
        raise
    session.commit()
    _record_payment_event_log(
        session,
        current_user=current_user,
        response=response,
        event_name="order_completed",
        source="toss_payment_confirm",
        fallback_request_id=fallback_request_id,
        fallback_anonymous_user_id=fallback_anonymous_user_id,
        fallback_session_id=fallback_session_id,
    )
    return response


def _record_payment_started_event_log(
    session: Session,
    *,
    current_user: User,
    source: str,
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
    payment_code: str | None = None,
    order_code: str | None = None,
    amount: int | None = None,
) -> None:
    try:
        context = _load_payment_event_context(
            session,
            user_id=current_user.id,
            payment_code=payment_code,
            order_code=order_code,
        )
        metadata_json = {
            "source": source,
            "amount": amount,
        }
        order_id = None
        if context is not None:
            payment, order = context
            order_id = order.id
            metadata_json.update(
                {
                    "order_code": order.order_code,
                    "payment_code": payment.payment_code,
                    "payment_provider": payment.provider,
                    "order_status": order.status,
                    "payment_status": payment.status,
                    "amount": payment.amount,
                    "currency": payment.currency,
                }
            )

        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="payment_started",
                source=source,
                page="payment",
                order_id=order_id,
                metadata_json=metadata_json,
            ),
            current_user=current_user,
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_payment_started_event_log")


def _record_toss_payment_failed_event_log(
    session: Session,
    *,
    current_user: User,
    request: TossPaymentConfirmRequest,
    error: ApiError,
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
) -> None:
    try:
        context = _load_payment_event_context(
            session,
            user_id=current_user.id,
            order_code=request.order_code,
        )
        order_id = None
        metadata_json = {
            "order_code": request.order_code,
            "amount": request.amount,
            "error_code": error.code,
            "error_status_code": error.status_code,
        }
        if context is not None:
            payment, order = context
            order_id = order.id
            metadata_json.update(
                {
                    "payment_code": payment.payment_code,
                    "payment_provider": payment.provider,
                    "order_status": order.status,
                    "payment_status": payment.status,
                    "currency": payment.currency,
                }
            )

        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="payment_failed",
                source="toss_payment_confirm",
                page="payment",
                order_id=order_id,
                metadata_json=metadata_json,
            ),
            current_user=current_user,
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_toss_payment_failed_event_log")


def _record_payment_event_log(
    session: Session,
    *,
    current_user: User,
    response: PaymentActionResponse,
    event_name: str,
    source: str,
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
) -> None:
    try:
        row = session.execute(
            select(Payment, Order)
            .join(Order, Payment.order_id == Order.id)
            .where(
                Payment.payment_code == response.payment_code,
                Order.order_code == response.order_code,
                Order.user_id == current_user.id,
            )
        ).one_or_none()
        if row is None:
            return

        payment, order = row
        create_event_log(
            session,
            EventLogCreateRequest(
                event_id=f"{event_name}:{order.order_code}:{payment.payment_code}",
                event_name=event_name,
                source=source,
                page="payment",
                order_id=order.id,
                metadata_json={
                    "order_code": order.order_code,
                    "payment_code": payment.payment_code,
                    "payment_provider": payment.provider,
                    "order_status": response.order_status,
                    "payment_status": response.payment_status,
                    "amount": payment.amount,
                    "currency": payment.currency,
                },
            ),
            current_user=current_user,
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_payment_event_log", extra={"event_name": event_name})


def _load_payment_event_context(
    session: Session,
    *,
    user_id: int,
    payment_code: str | None = None,
    order_code: str | None = None,
) -> tuple[Payment, Order] | None:
    conditions = [Order.user_id == user_id]
    if payment_code:
        conditions.append(Payment.payment_code == payment_code.strip())
    if order_code:
        conditions.append(Order.order_code == order_code.strip())
    if len(conditions) == 1:
        return None

    return session.execute(
        select(Payment, Order)
        .join(Order, Payment.order_id == Order.id)
        .where(*conditions)
    ).one_or_none()
