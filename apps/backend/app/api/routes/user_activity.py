from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.user_activity import (
    DeleteUserActivityResponse,
    RecentViewItem,
    RecentViewRequest,
    RecentViewsResponse,
    WishlistItem,
    WishlistRequest,
    WishlistResponse,
)
from app.services.user_activity_service import (
    DEFAULT_ACTIVITY_LIMIT,
    MAX_ACTIVITY_LIMIT,
    add_wishlist_item,
    get_recent_views_response,
    get_wishlist_response,
    remove_recent_view,
    remove_wishlist_item,
    upsert_recent_view,
)


router = APIRouter(tags=["user-activity"])


@router.get("/me/wishlist", response_model=WishlistResponse)
def get_my_wishlist(
    limit: int = Query(default=DEFAULT_ACTIVITY_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> WishlistResponse:
    return get_wishlist_response(session, current_user, limit=limit)


@router.post(
    "/me/wishlist",
    response_model=WishlistItem,
    responses={404: {"model": ErrorResponse}},
)
def post_my_wishlist(
    request: WishlistRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> WishlistItem:
    item = add_wishlist_item(session, current_user, request.product_id)
    session.commit()
    return item


@router.delete("/me/wishlist/{product_id}", response_model=DeleteUserActivityResponse)
def delete_my_wishlist(
    product_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DeleteUserActivityResponse:
    success = remove_wishlist_item(session, current_user, product_id)
    session.commit()
    return DeleteUserActivityResponse(success=success)


@router.get("/me/recent", response_model=RecentViewsResponse)
def get_my_recent_views(
    limit: int = Query(default=DEFAULT_ACTIVITY_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RecentViewsResponse:
    return get_recent_views_response(session, current_user, limit=limit)


@router.post(
    "/me/recent",
    response_model=RecentViewItem,
    responses={404: {"model": ErrorResponse}},
)
def post_my_recent_view(
    request: RecentViewRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RecentViewItem:
    item = upsert_recent_view(session, current_user, request.product_id)
    session.commit()
    return item


@router.delete("/me/recent/{product_id}", response_model=DeleteUserActivityResponse)
def delete_my_recent_view(
    product_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DeleteUserActivityResponse:
    success = remove_recent_view(session, current_user, product_id)
    session.commit()
    return DeleteUserActivityResponse(success=success)
