from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.review import (
    ProductReviewCreateRequest,
    ProductReviewMutationResponse,
    ProductReviewUpdateRequest,
    MyProductReviewsResponse,
    ReviewableOrderItemsResponse,
)
from app.services.event_tracking import request_id_from_request
from app.services.review_mutation_service import (
    create_purchase_review,
    delete_purchase_review,
    update_purchase_review,
)
from app.services.review_user_query_service import (
    DEFAULT_MY_REVIEW_PAGE_SIZE,
    MAX_MY_REVIEW_PAGE_SIZE,
    get_my_product_reviews,
    get_reviewable_order_items,
)


router = APIRouter(tags=["reviews"])


@router.get(
    "/me/reviews",
    response_model=MyProductReviewsResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_my_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=DEFAULT_MY_REVIEW_PAGE_SIZE,
        ge=1,
        le=MAX_MY_REVIEW_PAGE_SIZE,
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> MyProductReviewsResponse:
    return get_my_product_reviews(
        session,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/me/reviewable-order-items",
    response_model=ReviewableOrderItemsResponse,
    responses={401: {"model": ErrorResponse}},
)
def get_my_reviewable_order_items(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=DEFAULT_MY_REVIEW_PAGE_SIZE,
        ge=1,
        le=MAX_MY_REVIEW_PAGE_SIZE,
    ),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ReviewableOrderItemsResponse:
    return get_reviewable_order_items(
        session,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/products/{product_id}/reviews",
    response_model=ProductReviewMutationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def post_product_review(
    http_request: Request,
    product_id: str,
    request: ProductReviewCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProductReviewMutationResponse:
    started_at = current_time()
    response = create_purchase_review(
        session,
        product_code=product_id,
        current_user=current_user,
        request=request,
    )
    log_performance_event(
        "product_review_create_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_id": product_id,
            "review_id": response.review_id,
            "review_count": response.review_summary.review_count,
        },
    )
    return response


@router.patch(
    "/reviews/{review_id}",
    response_model=ProductReviewMutationResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def patch_review(
    http_request: Request,
    review_id: str,
    request: ProductReviewUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProductReviewMutationResponse:
    started_at = current_time()
    response = update_purchase_review(
        session,
        review_code=review_id,
        current_user=current_user,
        request=request,
    )
    log_performance_event(
        "product_review_update_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_id": response.product_id,
            "review_id": response.review_id,
            "review_count": response.review_summary.review_count,
        },
    )
    return response


@router.delete(
    "/reviews/{review_id}",
    response_model=ProductReviewMutationResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def delete_review(
    http_request: Request,
    review_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ProductReviewMutationResponse:
    started_at = current_time()
    response = delete_purchase_review(
        session,
        review_code=review_id,
        current_user=current_user,
    )
    log_performance_event(
        "product_review_delete_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "product_id": response.product_id,
            "review_id": response.review_id,
            "review_count": response.review_summary.review_count,
        },
    )
    return response
