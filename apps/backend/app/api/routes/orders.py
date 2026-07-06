import logging

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.models.commerce import Order, Payment
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
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
from app.services.event_tracking import (
    anonymous_user_id_from_request,
    record_event_log_best_effort,
    request_id_from_request,
    session_id_from_request,
)


logger = logging.getLogger(__name__)
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
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderCreateResponse:
    response = create_order(session, current_user, request, idempotency_key)
    session.commit()
    _record_order_event(
        session,
        http_request,
        current_user=current_user,
        response=response,
        event_name="order_created",
        source="order_create",
    )
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
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> OrderCancelResponse:
    response = cancel_order(session, current_user, order_code)
    session.commit()
    _record_order_event(
        session,
        http_request,
        current_user=current_user,
        response=response,
        event_name="order_cancelled",
        source="order_cancel",
    )
    return response


def _record_order_event(
    session: Session,
    http_request: Request,
    *,
    current_user: User,
    response: OrderCreateResponse | OrderCancelResponse,
    event_name: str,
    source: str,
) -> None:
    row = session.execute(
        select(Order, Payment)
        .join(Payment, Payment.order_id == Order.id)
        .where(
            Order.order_code == response.order_code,
            Order.user_id == current_user.id,
        )
    ).one_or_none()
    if row is None:
        return

    order, payment = row
    event_id = f"{event_name}:{order.order_code}"
    if event_name == "order_cancelled":
        event_id = f"{event_id}:{order.status}"

    record_event_log_best_effort(
        session,
        EventLogCreateRequest(
            event_id=event_id,
            event_name=event_name,
            order_id=order.id,
            source=source,
            page="order",
            metadata_json={
                "order_code": order.order_code,
                "order_status": order.status,
                "payment_code": payment.payment_code,
                "payment_provider": payment.provider,
                "payment_status": payment.status,
                "subtotal": order.subtotal_amount,
                "shipping_fee": order.shipping_fee,
                "total": order.total_amount,
                "item_count": order.item_count,
                "total_quantity": order.total_quantity,
            },
        ),
        current_user=current_user,
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
        logger=logger,
        failure_message=f"failed_to_record_{event_name}_event",
    )
