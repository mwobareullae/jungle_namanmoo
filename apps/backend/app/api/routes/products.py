from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.product import ProductDetailResponse
from app.services.product_detail_service import get_product_detail_response


router = APIRouter(tags=["products"])


@router.get(
    "/products/{product_id}",
    response_model=ProductDetailResponse,
    responses={
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
    },
)
def get_product_by_id(
    product_id: str,
    recommendation_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ProductDetailResponse:
    return get_product_detail_response(session, product_id, recommendation_id)
