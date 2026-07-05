from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ApiError, ErrorResponse
from app.schemas.payment import PaymentActionResponse, TossPaymentConfirmRequest
from app.services.payment_service import confirm_mock_payment, confirm_toss_payment, fail_mock_payment
from app.services.toss_payments_client import TossPaymentsClient, TossPaymentsClientError


router = APIRouter(tags=["payments"])


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
    return response
