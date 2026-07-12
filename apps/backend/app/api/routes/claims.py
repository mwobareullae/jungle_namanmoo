from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.models.commerce import Order, OrderClaim, OrderClaimItem
from app.db.session import get_db
from app.schemas.claim import (
    OrderClaimCreateRequest,
    OrderClaimEligibilityResponse,
    OrderClaimItemResponse,
    OrderClaimListResponse,
    OrderClaimResponse,
)
from app.schemas.common import ErrorResponse
from app.services.order_claim_service import (
    create_claim,
    get_claim,
    get_claim_eligibility,
    list_claims,
    withdraw_claim,
)


router = APIRouter(tags=["order-claims"])


@router.get(
    "/orders/{order_code}/claim-eligibility",
    response_model=OrderClaimEligibilityResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_order_claim_eligibility(
    order_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderClaimEligibilityResponse:
    return get_claim_eligibility(session, current_user, order_code)


@router.post(
    "/order-claims",
    response_model=OrderClaimResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def post_order_claim(
    request: OrderClaimCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderClaimResponse:
    claim = create_claim(session, current_user, request)
    session.commit()
    return _to_response(session, claim.id, current_user.id)


@router.get(
    "/order-claims",
    response_model=OrderClaimListResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_order_claims(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderClaimListResponse:
    return OrderClaimListResponse(
        items=[_to_response(session, claim.id, current_user.id) for claim in list_claims(session, current_user)]
    )


@router.get(
    "/order-claims/{claim_code}",
    response_model=OrderClaimResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_order_claim(
    claim_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderClaimResponse:
    claim = get_claim(session, current_user, claim_code)
    return _to_response(session, claim.id, current_user.id)


@router.post(
    "/order-claims/{claim_code}/withdraw",
    response_model=OrderClaimResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def post_order_claim_withdraw(
    claim_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderClaimResponse:
    claim = withdraw_claim(session, current_user, claim_code)
    session.commit()
    return _to_response(session, claim.id, current_user.id)


def _to_response(session: Session, claim_id: int, user_id: int) -> OrderClaimResponse:
    claim_row, order_code = session.execute(
        select(OrderClaim, Order.order_code)
        .join(Order, Order.id == OrderClaim.order_id)
        .where(OrderClaim.id == claim_id, OrderClaim.user_id == user_id)
    ).one()
    items = session.execute(
        select(OrderClaimItem)
        .where(OrderClaimItem.claim_id == claim_row.id)
        .order_by(OrderClaimItem.id.asc())
    ).scalars().all()
    return OrderClaimResponse(
        claim_code=claim_row.claim_code,
        order_code=order_code,
        claim_type=claim_row.claim_type,
        status=claim_row.status,
        reason_code=claim_row.reason_code,
        reason_detail=claim_row.reason_detail,
        refund_amount=claim_row.refund_amount,
        requested_at=claim_row.requested_at,
        processed_at=claim_row.processed_at,
        completed_at=claim_row.completed_at,
        items=[
            OrderClaimItemResponse(
                order_item_id=item.order_item_id,
                quantity=item.quantity,
                resolution=item.resolution,
            )
            for item in items
        ],
    )
