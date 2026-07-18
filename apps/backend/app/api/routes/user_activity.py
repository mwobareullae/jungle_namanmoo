import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
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
from app.services.event_tracking import (
    anonymous_user_id_from_request,
    record_event_log_best_effort,
    request_id_from_request,
    session_id_from_request,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["user-activity"])


@router.get("/me/wishlist", response_model=WishlistResponse)
def get_my_wishlist(
    limit: int = Query(default=DEFAULT_ACTIVITY_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT),
    cursor: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> WishlistResponse:
    return get_wishlist_response(session, current_user, limit=limit, cursor=cursor)


@router.post(
    "/me/wishlist",
    response_model=WishlistItem,
    responses={404: {"model": ErrorResponse}},
)
def post_my_wishlist(
    request: WishlistRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> WishlistItem:
    item = add_wishlist_item(session, current_user, request.product_id)
    session.commit()
    _record_user_activity_event(
        session,
        http_request,
        current_user=current_user,
        event_name="wishlist_added",
        product_id=request.product_id,
        source="wishlist",
    )
    return item


@router.delete("/me/wishlist/{product_id}", response_model=DeleteUserActivityResponse)
def delete_my_wishlist(
    product_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DeleteUserActivityResponse:
    success = remove_wishlist_item(session, current_user, product_id)
    session.commit()
    if success:
        _record_user_activity_event(
            session,
            http_request,
            current_user=current_user,
            event_name="wishlist_removed",
            product_id=product_id,
            source="wishlist",
        )
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
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RecentViewItem:
    item = upsert_recent_view(session, current_user, request.product_id)
    session.commit()
    _record_user_activity_event(
        session,
        http_request,
        current_user=current_user,
        event_name="recent_product_viewed",
        product_id=request.product_id,
        source="recent_view",
        page="product_detail",
    )
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


def _record_user_activity_event(
    session: Session,
    http_request: Request,
    *,
    current_user: User,
    event_name: str,
    product_id: str,
    source: str,
    page: str | None = None,
) -> None:
    record_event_log_best_effort(
        session,
        EventLogCreateRequest(
            event_name=event_name,
            product_id=product_id,
            source=source,
            page=page,
        ),
        current_user=current_user,
        fallback_request_id=request_id_from_request(http_request),
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
        logger=logger,
        failure_message=f"failed_to_record_{event_name}",
    )
