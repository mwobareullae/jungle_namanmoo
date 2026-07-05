import logging

from fastapi import APIRouter, Depends
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
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> PaymentActionResponse:
    response = confirm_mock_payment(session, current_user, payment_code)
    session.commit()
    _record_payment_event_log(
        session,
        current_user=current_user,
        response=response,
        event_name="order_completed",
        source="mock_payment_confirm",
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
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    toss_client: TossPaymentsClient = Depends(get_toss_payments_client),
) -> PaymentActionResponse:
    response = confirm_toss_payment(session, current_user, request, toss_client)
    session.commit()
    _record_payment_event_log(
        session,
        current_user=current_user,
        response=response,
        event_name="order_completed",
        source="toss_payment_confirm",
    )
    return response


def _record_payment_event_log(
    session: Session,
    *,
    current_user: User,
    response: PaymentActionResponse,
    event_name: str,
    source: str,
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
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_payment_event_log", extra={"event_name": event_name})
