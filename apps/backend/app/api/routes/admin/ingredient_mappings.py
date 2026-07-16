"""관리자 성분 매핑 검수 조회 라우트 (P1-M2-A Chunk 3, 조회 전용).

인증/인가는 admin_router 공통 가드(get_current_admin)가 적용한다. 판정 액션
(approve/hold/reject/reopen)은 후속 Chunk 에서 추가한다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.admin.ingredient_mapping import (
    IngredientMappingDetail,
    IngredientMappingListResponse,
)
from app.schemas.common import ErrorResponse
from app.services.admin.ingredient_mapping_service import (
    DEFAULT_LIMIT,
    get_ingredient_mapping_detail,
    list_ingredient_mappings,
)


router = APIRouter()


@router.get(
    "/ingredient-mappings",
    response_model=IngredientMappingListResponse,
    responses={400: {"model": ErrorResponse}},
)
def list_mappings(
    status: str | None = Query(
        default=None, description="PENDING/HELD/APPROVED/REJECTED. 잘못된 값은 400."
    ),
    q: str | None = Query(default=None, description="pending code·대표 원문명·정규화명 부분 검색"),
    limit: int = Query(default=DEFAULT_LIMIT),
    cursor: str | None = Query(default=None, description="서버 발급 opaque cursor. 프론트 해석 금지"),
    session: Session = Depends(get_db),
) -> IngredientMappingListResponse:
    """pending 성분 원문 그룹 목록. review 를 붙여 상태를 계산하고 추천을 함께 반환한다."""

    return list_ingredient_mappings(session, status=status, q=q, limit=limit, cursor=cursor)


@router.get(
    "/ingredient-mappings/{pending_code}",
    response_model=IngredientMappingDetail,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_mapping_detail(
    pending_code: str,
    normalized_source_name: str = Query(..., description="검수 대상 원문 그룹. 목록 응답값 재전송"),
    session: Session = Depends(get_db),
) -> IngredientMappingDetail:
    """한 원문 그룹의 상세(원문 변형·대표 상품·결정 이력·추천)를 반환한다."""

    return get_ingredient_mapping_detail(
        session, pending_code=pending_code, normalized_source_name=normalized_source_name
    )
