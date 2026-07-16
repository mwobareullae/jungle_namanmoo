from datetime import UTC, datetime, timedelta
import logging

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_optional_current_user
from app.core.config import settings
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Cart, CartItem
from app.db.session import get_db
from app.schemas.cart import (
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartMergeResponse,
    CartResponse,
    CheckoutPreviewRequest,
    CheckoutPreviewResponse,
    DeleteCartItemResponse,
    DeleteCartItemsRequest,
    DeleteCartItemsResponse,
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
    remove_cart_items,
    update_cart_item_quantity,
)
from app.services.event_service import create_event_log
from app.services.event_tracking import anonymous_user_id_from_request, request_id_from_request, session_id_from_request


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
    http_request: Request,
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
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
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
    http_request: Request,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> CartResponse:
    event_context = _load_cart_item_event_context(
        session,
        current_user=current_user,
        anonymous_cart_id=anonymous_cart_id,
        item_id=item_id,
    )
    cart = update_cart_item_quantity(
        session,
        current_user,
        anonymous_cart_id,
        item_id=item_id,
        quantity=request.quantity,
    )
    session.commit()
    if event_context is not None:
        _record_cart_item_event(
            session,
            current_user=current_user,
            anonymous_cart_id=anonymous_cart_id,
            cart_id=event_context["cart_id"],
            product_id=event_context["product_id"],
            event_name="cart_removed" if request.quantity == 0 else "cart_quantity_changed",
            previous_quantity=event_context["quantity"],
            quantity=request.quantity,
            fallback_request_id=request_id_from_request(http_request),
            fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
            fallback_session_id=session_id_from_request(http_request),
        )
    return cart


@router.delete("/cart/items/bulk", response_model=DeleteCartItemsResponse)
def delete_cart_items(
    request: DeleteCartItemsRequest,
    http_request: Request,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> DeleteCartItemsResponse:
    event_contexts = [
        context
        for item_id in dict.fromkeys(request.cart_item_ids)
        if (context := _load_cart_item_event_context(
            session,
            current_user=current_user,
            anonymous_cart_id=anonymous_cart_id,
            item_id=item_id,
        )) is not None
    ]
    result = remove_cart_items(
        session,
        current_user,
        anonymous_cart_id,
        item_ids=request.cart_item_ids,
    )
    session.commit()
    for context in event_contexts:
        _record_cart_item_event(
            session,
            current_user=current_user,
            anonymous_cart_id=anonymous_cart_id,
            cart_id=context["cart_id"],
            product_id=context["product_id"],
            event_name="cart_removed",
            previous_quantity=context["quantity"],
            quantity=0,
            fallback_request_id=request_id_from_request(http_request),
            fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
            fallback_session_id=session_id_from_request(http_request),
        )
    return DeleteCartItemsResponse(
        success=True,
        deleted_item_ids=result.deleted_item_ids,
        cart=result.cart,
    )


@router.delete("/cart/items/{item_id}", response_model=DeleteCartItemResponse)
def delete_cart_item(
    item_id: int,
    http_request: Request,
    anonymous_cart_id: str | None = Cookie(default=None, alias=ANONYMOUS_CART_COOKIE_NAME),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> DeleteCartItemResponse:
    event_context = _load_cart_item_event_context(
        session,
        current_user=current_user,
        anonymous_cart_id=anonymous_cart_id,
        item_id=item_id,
    )
    cart = remove_cart_item(
        session,
        current_user,
        anonymous_cart_id,
        item_id=item_id,
    )
    session.commit()
    if event_context is not None:
        _record_cart_item_event(
            session,
            current_user=current_user,
            anonymous_cart_id=anonymous_cart_id,
            cart_id=event_context["cart_id"],
            product_id=event_context["product_id"],
            event_name="cart_removed",
            previous_quantity=event_context["quantity"],
            quantity=0,
            fallback_request_id=request_id_from_request(http_request),
            fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
            fallback_session_id=session_id_from_request(http_request),
        )
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
    http_request: Request,
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
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
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
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
) -> None:
    try:
        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="cart_added",
                anonymous_user_id=fallback_anonymous_user_id or (None if current_user is not None else anonymous_cart_id),
                session_id=fallback_session_id,
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
            fallback_request_id=fallback_request_id,
            fallback_anonymous_user_id=fallback_anonymous_user_id,
            fallback_session_id=fallback_session_id,
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
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
) -> None:
    try:
        create_event_log(
            session,
            EventLogCreateRequest(
                event_name="checkout_started",
                anonymous_user_id=fallback_anonymous_user_id or (None if current_user is not None else anonymous_cart_id),
                session_id=fallback_session_id,
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
                    "product_ids": [item.product.product_id for item in preview.items],
                    "warning_codes": [warning.code for warning in preview.warnings],
                    "address_id_provided": request.address_id is not None,
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
        logger.exception("failed_to_record_checkout_started_event")


def _load_cart_item_event_context(
    session: Session,
    *,
    current_user: User | None,
    anonymous_cart_id: str | None,
    item_id: int,
) -> dict | None:
    if current_user is None and not anonymous_cart_id:
        return None

    conditions = [
        CartItem.id == item_id,
        Cart.status == "ACTIVE",
    ]
    if current_user is not None:
        conditions.append(Cart.user_id == current_user.id)
    else:
        conditions.append(Cart.anonymous_cart_id == anonymous_cart_id)

    row = session.execute(
        select(CartItem, Cart, Product.product_code)
        .join(Cart, CartItem.cart_id == Cart.id)
        .join(Product, CartItem.product_id == Product.id)
        .where(*conditions)
    ).one_or_none()
    if row is None:
        return None

    item, cart, product_id = row
    return {
        "cart_id": cart.id,
        "product_id": product_id,
        "quantity": item.quantity,
    }


def _record_cart_item_event(
    session: Session,
    *,
    current_user: User | None,
    anonymous_cart_id: str | None,
    cart_id: int | None,
    product_id: str,
    event_name: str,
    previous_quantity: int,
    quantity: int,
    fallback_request_id: str | None,
    fallback_anonymous_user_id: str | None,
    fallback_session_id: str | None,
) -> None:
    try:
        create_event_log(
            session,
            EventLogCreateRequest(
                event_name=event_name,
                anonymous_user_id=fallback_anonymous_user_id or (None if current_user is not None else anonymous_cart_id),
                session_id=fallback_session_id,
                cart_id=cart_id,
                product_id=product_id,
                source="cart",
                page="cart",
                metadata={
                    "previous_quantity": previous_quantity,
                    "quantity": quantity,
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
        logger.exception("failed_to_record_cart_item_event", extra={"event_name": event_name})
