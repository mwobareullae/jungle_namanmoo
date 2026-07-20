"""관리자 성분 매핑 검수 라우트 (P1-M2-A, 조회 + 판정).

인증/인가는 admin_router 공통 가드(get_current_admin)가 적용한다. 판정 액션은
서비스가 `flush()` 까지만 하고, 여기서 commit/rollback 과 성공·실패 성능 로그를
담당한다(§8). 기존 `product_ingredients`·전역 alias 는 변경하지 않는다.
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.performance_logging import current_time, elapsed_ms, log_error_event, log_performance_event
from app.db.models.auth import User
from app.db.session import get_db
from app.schemas.admin.ingredient_mapping import (
    CanonicalIngredientSearchResponse,
    IngredientMappingActionResponse,
    IngredientMappingApproveRequest,
    IngredientMappingBulkApprovalPreviewResponse,
    IngredientMappingBulkApprovalRequest,
    IngredientMappingBulkApprovalResponse,
    IngredientMappingDetail,
    IngredientMappingListResponse,
    IngredientMappingReasonRequest,
    IngredientMappingRejectRequest,
)
from app.schemas.common import ApiError, ErrorResponse
from app.services.admin.ingredient_mapping_mutation_service import (
    approve_ingredient_mapping,
    hold_ingredient_mapping,
    reject_ingredient_mapping,
    reopen_ingredient_mapping,
)
from app.services.admin.ingredient_mapping_bulk_approval_service import (
    approve_kcia_alias_exact_batch,
    get_kcia_alias_exact_bulk_preview,
)
from app.services.admin.ingredient_mapping_service import (
    CANONICAL_SEARCH_DEFAULT_LIMIT,
    DEFAULT_LIMIT,
    get_ingredient_mapping_detail,
    list_ingredient_mappings,
    search_canonical_ingredients,
)


router = APIRouter()

_ACTION_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.get(
    "/ingredient-mappings",
    response_model=IngredientMappingListResponse,
    responses={400: {"model": ErrorResponse}},
)
def list_mappings(
    status: str | None = Query(
        default=None, description="PENDING/HELD/NEEDS_REVIEW/APPROVED/REJECTED. 잘못된 값은 400."
    ),
    final_disposition: str | None = Query(
        default=None,
        description="MAPPED/NON_INGREDIENT/COMPOUND_MATERIAL/SOURCE_ERROR/UNRESOLVABLE. 잘못된 값은 400.",
    ),
    q: str | None = Query(default=None, description="pending code·대표 원문명·정규화명 부분 검색"),
    sort: str | None = Query(default=None, description="CODE_ASC/CONNECTION_DESC. Invalid values return 400."),
    candidate_type: str | None = Query(
        default=None,
        description="CANONICAL_EXACT_MATCH/ALIAS_EXACT_MATCH/EXACT_MATCH_CONFLICT/NO_EXACT_MATCH.",
    ),
    limit: int = Query(default=DEFAULT_LIMIT),
    cursor: str | None = Query(default=None, description="서버 발급 opaque cursor. 프론트 해석 금지"),
    session: Session = Depends(get_db),
) -> IngredientMappingListResponse:
    """pending 성분 원문 그룹 목록. review 를 붙여 상태를 계산하고 추천을 함께 반환한다."""

    return list_ingredient_mappings(
        session,
        status=status,
        final_disposition=final_disposition,
        sort=sort,
        candidate_type=candidate_type,
        q=q,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/ingredient-mappings/bulk-approve/preview",
    response_model=IngredientMappingBulkApprovalPreviewResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_bulk_approval_preview(
    session: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> IngredientMappingBulkApprovalPreviewResponse:
    """KCIA 근거 별칭 정확 일치 일괄 승인 전용 미리보기."""

    return get_kcia_alias_exact_bulk_preview(session)


@router.post(
    "/ingredient-mappings/bulk-approve",
    response_model=IngredientMappingBulkApprovalResponse,
    responses=_ACTION_RESPONSES,
)
def post_bulk_approval(
    body: IngredientMappingBulkApprovalRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> IngredientMappingBulkApprovalResponse:
    """선택된 KCIA 근거 후보를 전부 재검증해 원자적으로 승인한다."""

    started_at = current_time()
    try:
        response = approve_kcia_alias_exact_batch(
            session,
            items=body.items,
            confirmed_count=body.confirmed_count,
            actor_user_id=int(current_user.id),
        )
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_ingredient_mapping_bulk_approval_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"error_code": exc.code, "selected_count": len(body.items)},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_ingredient_mapping_bulk_approval_failed",
            started_at=started_at,
            metadata={"selected_count": len(body.items), "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise
    log_performance_event(
        "admin_ingredient_mapping_bulk_approval_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={"approved_count": response.approved_count, "batch_reference": response.batch_reference},
    )
    return response


@router.get(
    "/ingredients/search",
    response_model=CanonicalIngredientSearchResponse,
    responses={400: {"model": ErrorResponse}},
)
def search_canonicals(
    q: str = Query(..., description="canonical 성분 검색어(1~100자)"),
    limit: int = Query(default=CANONICAL_SEARCH_DEFAULT_LIMIT),
    cursor: str | None = Query(default=None, description="서버 발급 opaque cursor"),
    session: Session = Depends(get_db),
) -> CanonicalIngredientSearchResponse:
    """승인 대상 canonical 후보 검색(활성·비pending만)."""

    return search_canonical_ingredients(session, q=q, limit=limit, cursor=cursor)


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


@router.post(
    "/ingredient-mappings/{pending_code}/approve",
    response_model=IngredientMappingActionResponse,
    responses=_ACTION_RESPONSES,
)
def approve_mapping(
    pending_code: str,
    body: IngredientMappingApproveRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> IngredientMappingActionResponse:
    return _run_decision(
        session,
        lambda: approve_ingredient_mapping(
            session,
            pending_code=pending_code,
            normalized_source_name=body.normalized_source_name,
            target_ingredient_code=body.target_ingredient_code,
            decision_reason=body.decision_reason,
            actor_user_id=int(current_user.id),
        ),
        action="APPROVE",
        pending_code=pending_code,
    )


@router.post(
    "/ingredient-mappings/{pending_code}/hold",
    response_model=IngredientMappingActionResponse,
    responses=_ACTION_RESPONSES,
)
def hold_mapping(
    pending_code: str,
    body: IngredientMappingReasonRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> IngredientMappingActionResponse:
    return _run_decision(
        session,
        lambda: hold_ingredient_mapping(
            session,
            pending_code=pending_code,
            normalized_source_name=body.normalized_source_name,
            decision_reason=body.decision_reason,
            actor_user_id=int(current_user.id),
        ),
        action="HOLD",
        pending_code=pending_code,
    )


@router.post(
    "/ingredient-mappings/{pending_code}/reject",
    response_model=IngredientMappingActionResponse,
    responses=_ACTION_RESPONSES,
)
def reject_mapping(
    pending_code: str,
    body: IngredientMappingRejectRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> IngredientMappingActionResponse:
    return _run_decision(
        session,
        lambda: reject_ingredient_mapping(
            session,
            pending_code=pending_code,
            normalized_source_name=body.normalized_source_name,
            decision_reason=body.decision_reason,
            final_disposition=body.final_disposition,
            evidence_source_url=body.evidence_source_url,
            source_reference=body.source_reference,
            actor_user_id=int(current_user.id),
        ),
        action="REJECT",
        pending_code=pending_code,
    )


@router.post(
    "/ingredient-mappings/{pending_code}/reopen",
    response_model=IngredientMappingActionResponse,
    responses=_ACTION_RESPONSES,
)
def reopen_mapping(
    pending_code: str,
    body: IngredientMappingReasonRequest,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> IngredientMappingActionResponse:
    return _run_decision(
        session,
        lambda: reopen_ingredient_mapping(
            session,
            pending_code=pending_code,
            normalized_source_name=body.normalized_source_name,
            decision_reason=body.decision_reason,
            actor_user_id=int(current_user.id),
        ),
        action="REOPEN",
        pending_code=pending_code,
    )


def _run_decision(
    session: Session,
    decision_fn: Callable[[], IngredientMappingActionResponse],
    *,
    action: str,
    pending_code: str,
) -> IngredientMappingActionResponse:
    """판정 공통 commit/rollback/성능 로그(§8). 클레임 결정 라우터와 동일 패턴."""

    started_at = current_time()
    try:
        response = decision_fn()
        session.commit()
    except ApiError as exc:
        session.rollback()
        log_performance_event(
            "admin_ingredient_mapping_decision_failed",
            duration_ms=elapsed_ms(started_at),
            metadata={"pending_code": pending_code, "action": action, "error_code": exc.code},
        )
        raise
    except Exception as exc:
        session.rollback()
        log_error_event(
            "admin_ingredient_mapping_decision_failed",
            started_at=started_at,
            metadata={"pending_code": pending_code, "action": action, "error_code": "UNEXPECTED_ERROR"},
            exc=exc,
        )
        raise

    log_performance_event(
        "admin_ingredient_mapping_decision_completed",
        duration_ms=elapsed_ms(started_at),
        metadata={"pending_code": pending_code, "action": action, "status": response.status},
    )
    return response
