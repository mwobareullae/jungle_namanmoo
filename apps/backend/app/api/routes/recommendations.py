from fastapi import APIRouter

from app.schemas.common import ErrorResponse
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.services.mock_store import create_recommendation, get_recommendation


router = APIRouter(tags=["recommendations"])


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={400: {"model": ErrorResponse}},
)
def post_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    return create_recommendation(request)


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_recommendation_by_id(recommendation_id: str) -> RecommendationResponse:
    return get_recommendation(recommendation_id)
