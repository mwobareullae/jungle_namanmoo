from fastapi import APIRouter, Depends, Request, status
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
)
from app.services.event_tracking import request_id_from_request
from app.services.review_mutation_service import (
    create_purchase_review,
    delete_purchase_review,
    update_purchase_review,
)


router = APIRouter(tags=["reviews"])


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
