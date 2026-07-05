from datetime import UTC, datetime, timedelta
import logging

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_optional_current_user
from app.core.config import settings
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.cart import (
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartMergeResponse,
    CartResponse,
    CheckoutPreviewRequest,
    CheckoutPreviewResponse,
    DeleteCartItemResponse,
)
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
from app.services.cart_service import (
    ANONYMOUS_CART_COOKIE_NAME,
    ANONYMOUS_CART_TTL_DAYS,
    add_cart_item,
    get_cart_response,
    get_checkout_preview,
    merge_anonymous_cart,
    remove_cart_item,
    update_cart_item_quantity,
)
from app.services.event_service import create_event_log


router = APIRouter(tags=["cart"])
logger = logging.getLogger(__name__)


@router.get("/cart", response_model=CartResponse)
def get_cart(
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CartResponse:
    return get_cart_response(session, current_user, anonymous_cart_id)


@router.post(
    "/cart/items",
    response_model=CartResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def post_cart_item(
    request: CartItemAddRequest,
    response: Response,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CartResponse:
    result = add_cart_item(
        session,
        current_user,
        anonymous_cart_id,
        product_code=request.product_id,
        quantity=request.quantity,
        source=request.source,
        recommendation_id=request.recommendation_id,
        recommendation_rank=request.recommendation_rank,
    )
    session.commit()
    _record_cart_added_event(
        session,
        current_user=current_user,
        anonymous_cart_id=result.anonymous_cart_id or anonymous_cart_id,
        cart_id=result.cart.cart_id,
        request=request,
    )
    if result.anonymous_cart_id:
        _set_anonymous_cart_cookie(response, result.anonymous_cart_id)
    return result.cart


@router.patch(
    "/cart/items/{item_id}",
    response_model=CartResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def patch_cart_item(
    item_id: int,
    request: CartItemUpdateRequest,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CartResponse:
    cart = update_cart_item_quantity(
        session,
        current_user,
        anonymous_cart_id,
        item_id=item_id,
        quantity=request.quantity,
    )
    session.commit()
    return cart


@router.delete("/cart/items/{item_id}", response_model=DeleteCartItemResponse)
def delete_cart_item(
    item_id: int,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> DeleteCartItemResponse:
    cart = remove_cart_item(
        session,
        current_user,
        anonymous_cart_id,
        item_id=item_id,
    )
    session.commit()
    return DeleteCartItemResponse(success=True, cart=cart)


@router.post("/cart/merge", response_model=CartMergeResponse)
def post_cart_merge(
    response: Response,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> CartMergeResponse:
    result = merge_anonymous_cart(session, current_user, anonymous_cart_id)
    session.commit()
    if anonymous_cart_id:
        _delete_anonymous_cart_cookie(response)
    return result


@router.post(
    "/checkout/preview",
    response_model=CheckoutPreviewResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def post_checkout_preview(
    request: CheckoutPreviewRequest,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CheckoutPreviewResponse:
    preview = get_checkout_preview(
        session,
        current_user,
        anonymous_cart_id,
        cart_item_ids=request.cart_item_ids,
        address_id=request.address_id,
    )
    _record_checkout_started_event(
        session,
        current_user=current_user,
        anonymous_cart_id=anonymous_cart_id,
        request=request,
        preview=preview,
    )
    return preview


def _set_anonymous_cart_cookie(response: Response, anonymous_cart_id: str) -> None:
    expires_at = datetime.now(UTC) + timedelta(days=ANONYMOUS_CART_TTL_DAYS)
    response.set_cookie(
        key=ANONYMOUS_CART_COOKIE_NAME,
        value=anonymous_cart_id,
        max_age=ANONYMOUS_CART_TTL_DAYS * 24 * 60 * 60,
        expires=expires_at,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _delete_anonymous_cart_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ANONYMOUS_CART_COOKIE_NAME,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _record_cart_added_event(
    session: Session,
    *,
    current_user: User | None,
    anonymous_cart_id: str | None,
    cart_id: int | None,
    request: CartItemAddRequest,
) -> None:
    try:
        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="cart_added",
                anonymous_user_id=None if current_user is not None else anonymous_cart_id,
                cart_id=cart_id,
                product_id=request.product_id,
                rank=request.recommendation_rank,
                source=request.source,
                recommendation_id=request.recommendation_id,
                metadata={
                    "quantity": request.quantity,
                },
            ),
            current_user=current_user,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_cart_added_event")


def _record_checkout_started_event(
    session: Session,
    *,
    current_user: User | None,
    anonymous_cart_id: str | None,
    request: CheckoutPreviewRequest,
    preview: CheckoutPreviewResponse,
) -> None:
    try:
        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="checkout_started",
                anonymous_user_id=None if current_user is not None else anonymous_cart_id,
                cart_id=preview.cart_id,
                source="checkout_preview",
                page="checkout",
                metadata={
                    "item_count": len(preview.items),
                    "total_quantity": sum(item.quantity for item in preview.items),
                    "subtotal": preview.subtotal,
                    "shipping_fee": preview.shipping_fee,
                    "total": preview.total,
                    "can_checkout": preview.can_checkout,
                    "warning_codes": [warning.code for warning in preview.warnings],
                    "address_id_provided": request.address_id is not None,
                },
            ),
            current_user=current_user,
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed_to_record_checkout_started_event")
