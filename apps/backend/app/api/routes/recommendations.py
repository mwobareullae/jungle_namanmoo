from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ErrorResponse
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


router = APIRouter(tags=["recommendations"])


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_recommendation(
    request: RecommendationRequest,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    return create_recommendation_response(session, request, page=page, page_size=page_size)


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    responses={
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def get_recommendation_by_id(
    recommendation_id: str,
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    return get_recommendation_response(
        session,
        recommendation_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/recommendations/{recommendation_id}/narrative",
    response_model=RecommendationNarrativeResponse,
    responses={
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
