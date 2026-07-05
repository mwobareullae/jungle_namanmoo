from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderDetailResponse,
    OrderListResponse,
)
from app.services.order_cancel_service import cancel_order
from app.services.order_query_service import get_order_detail, list_orders
from app.services.order_service import create_order


router = APIRouter(tags=["orders"])


@router.post(
    "/orders",
    response_model=OrderCreateResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_order(
    request: OrderCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderCreateResponse:
    response = create_order(session, current_user, request, idempotency_key)
    session.commit()
    return response


@router.get(
    "/orders",
    response_model=OrderListResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
    },
)
def get_orders(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderListResponse:
    return list_orders(session, current_user, status=status, limit=limit, cursor=cursor)


@router.get(
    "/orders/{order_code}",
    response_model=OrderDetailResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def get_order(
    order_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderDetailResponse:
    return get_order_detail(session, current_user, order_code)


@router.post(
    "/orders/{order_code}/cancel",
    response_model=OrderCancelResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_order_cancel(
    order_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderCancelResponse:
    response = cancel_order(session, current_user, order_code)
    session.commit()
    return response
