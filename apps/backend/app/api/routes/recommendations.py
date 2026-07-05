import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.event import EventLogCreateRequest
from app.schemas.recommendation import (
    RecommendationNarrativeRequest,
    RecommendationNarrativeResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.recommendation_narrative import create_recommendation_narrative_response
from app.services.recommendation_pipeline import (
    create_recommendation_response,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_recommendation_response,
)
from app.services.event_tracking import record_event_log_best_effort, request_id_from_request


router = APIRouter(tags=["recommendations"])
logger = logging.getLogger(__name__)


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_recommendation(
    http_request: Request,
    request: RecommendationRequest,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    response = create_recommendation_response(session, request, page=page, page_size=page_size)
    _record_recommendation_event(
        session,
        http_request=http_request,
        response=response,
        current_user=current_user,
        event_name="recommendation_requested",
        source="recommendation_create",
    )
    _record_recommendation_event(
        session,
        http_request=http_request,
        response=response,
        current_user=current_user,
        event_name="recommendation_analyzed",
        source="recommendation_create",
    )
    return response


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    responses={
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def get_recommendation_by_id(
    http_request: Request,
    recommendation_id: str,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    response = get_recommendation_response(
        session,
        recommendation_id,
        page=page,
        page_size=page_size,
    )
    _record_recommendation_event(
        session,
        http_request=http_request,
        response=response,
        current_user=current_user,
        event_name="recommendation_viewed",
        source="recommendation_get",
    )
    return response


@router.post(
    "/recommendations/{recommendation_id}/narrative",
    response_model=RecommendationNarrativeResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def post_recommendation_narrative(
    recommendation_id: str,
    request: RecommendationNarrativeRequest | None = None,
    session: Session = Depends(get_db),
) -> RecommendationNarrativeResponse:
    return create_recommendation_narrative_response(
        session,
        recommendation_id,
        request,
    )


def _record_recommendation_event(
    session: Session,
    *,
    http_request: Request,
    response: RecommendationResponse,
    current_user: User | None,
    event_name: str,
    source: str,
) -> None:
    summary = response.summary
    constraints = summary.purchase_constraints
    record_event_log_best_effort(
        session,
        EventLogCreateRequest(
            event_name=event_name,
            recommendation_id=response.recommendation_id,
            source=source,
            page="recommendation",
            metadata_json={
                "product_count": len(response.products),
                "total_items": response.pagination.total_items,
                "page": response.pagination.page,
                "page_size": response.pagination.page_size,
                "has_next": response.pagination.has_next,
                "skin_type": summary.skin_type,
                "sensitivity": summary.sensitivity,
                "matched_concern_count": len(summary.matched_concerns),
                "expected_effect_count": len(summary.expected_effects),
                "unmatched_term_count": len(response.unmatched_terms),
                "avoid_ingredient_count": len(summary.avoid_ingredients),
                "purchase_category_count": len(constraints.categories),
                "purchase_brand_count": len(constraints.brands),
                "has_price_constraint": constraints.price_min is not None or constraints.price_max is not None,
            },
        ),
        current_user=current_user,
        fallback_request_id=request_id_from_request(http_request),
        logger=logger,
        failure_message="failed_to_record_recommendation_event",
    )
