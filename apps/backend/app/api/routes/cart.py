from datetime import UTC, datetime, timedelta

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
    CheckoutPreviewResponse,
    DeleteCartItemResponse,
)
from app.schemas.common import ErrorResponse
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


router = APIRouter(tags=["cart"])


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
    responses={400: {"model": ErrorResponse}},
)
def post_checkout_preview(
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CheckoutPreviewResponse:
    return get_checkout_preview(session, current_user, anonymous_cart_id)


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
