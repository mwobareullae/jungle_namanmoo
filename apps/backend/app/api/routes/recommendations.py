import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_optional_current_user
from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
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
from app.services.agent_product_tools import get_refined_recommendation_response
from app.services.recommendation_pipeline import (
    create_recommendation_response,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_recommendation_response,
)
from app.services.event_tracking import (
    anonymous_user_id_from_request,
    record_event_log_best_effort,
    request_id_from_request,
    session_id_from_request,
)


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
    started_at = current_time()
    response = create_recommendation_response(
        session,
        request,
        page=page,
        page_size=page_size,
        current_user=current_user,
    )
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
    log_performance_event(
        "recommendation_create_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "recommendation_id": response.recommendation_id,
            "returned_product_count": len(response.products),
            "total_items": response.pagination.total_items,
            "page": response.pagination.page,
            "page_size": response.pagination.page_size,
            "matched_concern_count": len(response.summary.matched_concerns),
            "expected_effect_count": len(response.summary.expected_effects),
            "unmatched_term_count": len(response.unmatched_terms),
        },
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
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    category_code: str | None = Query(default=None, max_length=80),
    skin_type: str | None = Query(default=None, max_length=40),
    sensitivity: str | None = Query(default=None, max_length=40),
    effect_keyword: list[str] = Query(default=[]),
    current_user: User | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    started_at = current_time()
    has_refinement = any(
        value is not None
        for value in (min_price, max_price, category_code, skin_type, sensitivity)
    ) or bool(effect_keyword)
    response = (
        get_refined_recommendation_response(
            session,
            recommendation_id,
            page=page,
            page_size=page_size,
            min_price=min_price,
            max_price=max_price,
            category_code=category_code,
            skin_type=skin_type,
            sensitivity=sensitivity,
            effect_keywords=effect_keyword,
        )
        if has_refinement
        else get_recommendation_response(
            session,
            recommendation_id,
            page=page,
            page_size=page_size,
        )
    )
    _record_recommendation_event(
        session,
        http_request=http_request,
        response=response,
        current_user=current_user,
        event_name="recommendation_viewed",
        source="recommendation_get",
    )
    log_performance_event(
        "recommendation_get_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "recommendation_id": response.recommendation_id,
            "returned_product_count": len(response.products),
            "total_items": response.pagination.total_items,
            "page": response.pagination.page,
            "page_size": response.pagination.page_size,
            "refined": has_refinement,
        },
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
    http_request: Request,
    recommendation_id: str,
    request: RecommendationNarrativeRequest | None = None,
    session: Session = Depends(get_db),
) -> RecommendationNarrativeResponse:
    started_at = current_time()
    response = create_recommendation_narrative_response(
        session,
        recommendation_id,
        request,
    )
    log_performance_event(
        "recommendation_narrative_completed",
        request_id=request_id_from_request(http_request),
        duration_ms=elapsed_ms(started_at),
        metadata={
            "recommendation_id": response.recommendation_id,
            "generation_source": response.narrative.generation_source,
            "fallback_reason": response.narrative.fallback_reason,
            "product_explanation_count": len(response.narrative.product_explanations),
        },
    )
    return response


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
        fallback_anonymous_user_id=anonymous_user_id_from_request(http_request),
        fallback_session_id=session_id_from_request(http_request),
        logger=logger,
        failure_message="failed_to_record_recommendation_event",
    )
