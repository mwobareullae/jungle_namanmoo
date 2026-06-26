from fastapi import APIRouter, Query

from app.schemas.common import ErrorResponse
from app.schemas.product import ProductDetailResponse
from app.services.mock_store import get_product_detail


router = APIRouter(tags=["products"])


@router.get(
    "/products/{product_id}",
    response_model=ProductDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_product_by_id(
    product_id: str,
    recommendation_id: str | None = Query(default=None),
) -> ProductDetailResponse:
    return get_product_detail(product_id, recommendation_id)
