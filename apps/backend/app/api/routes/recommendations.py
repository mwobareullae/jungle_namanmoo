from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.services.recommendation_pipeline import (
    create_recommendation_response,
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
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    return create_recommendation_response(session, request)


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
    session: Session = Depends(get_db),
) -> RecommendationResponse:
    return get_recommendation_response(session, recommendation_id)
