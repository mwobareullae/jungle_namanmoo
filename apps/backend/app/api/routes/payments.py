from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.payment import PaymentActionResponse
from app.services.payment_service import confirm_mock_payment, fail_mock_payment


router = APIRouter(tags=["payments"])


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
