"""관리자 성분 매핑 검수 조회 응답 스키마 (P1-M2-A, 조회 전용).

DB에는 관리자 판정(`ingredient_mapping_reviews`)만 저장한다. 추천(`suggestion`)은
DB 판정 행이 아니라 조회 시점의 읽기 전용 정보이며, DB 정확 일치
(`ALIAS_EXACT`/`CANONICAL_NAME_EXACT`)만 소스로 쓴다. 상세 계약은
`docs/admin/admin-m2a-ingredient-mapping-api-contract.md` 참조.

검수 단위(외부 식별자)는 `(pending_code, normalized_source_name)` 복합키다.
`normalized_source_name`은 서버가 응답한 값을 프론트가 그대로 재전송한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# 저장 상태(HELD/APPROVED/REJECTED)는 review 행, PENDING 은 행 없이 파생.
IngredientMappingStatus = Literal["PENDING", "HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"]
IngredientMappingFinalDisposition = Literal[
    "MAPPED",
    "NON_INGREDIENT",
    "COMPOUND_MATERIAL",
    "SOURCE_ERROR",
    "UNRESOLVABLE",
]
IngredientMappingNonMappingFinalDisposition = Literal[
    "NON_INGREDIENT",
    "COMPOUND_MATERIAL",
    "SOURCE_ERROR",
    "UNRESOLVABLE",
]

# 추천 근거. 그룹 정규화명이 alias/canonical 이름과 정확 일치할 때만 채운다.
IngredientMappingMatchSource = Literal["ALIAS_EXACT", "CANONICAL_NAME_EXACT"]
IngredientMappingCandidateType = Literal[
    "CANONICAL_EXACT_MATCH",
    "ALIAS_EXACT_MATCH",
    "EXACT_MATCH_CONFLICT",
    "NO_EXACT_MATCH",
]

IngredientMappingAction = Literal["APPROVE", "HOLD", "REJECT", "REOPEN"]


class IngredientMappingSuggestion(BaseModel):
    """읽기 전용 추천 후보. DB 정확 일치만 사용하며, 없으면 상위 필드가 None."""

    target_ingredient_id: int
    target_ingredient_code: str
    target_ingredient_name: str
    match_source: IngredientMappingMatchSource


class IngredientMappingCandidate(BaseModel):
    """관리자 검수용 읽기 전용 처리 후보.

    후보는 등록된 canonical/alias의 정확 일치 여부만 표현한다. 최종 분류나
    상품 성분 연결을 자동으로 변경하지 않는다.
    """

    candidate_type: IngredientMappingCandidateType
    evidence: str


class IngredientMappingDecision(BaseModel):
    """저장된 관리자 판정 스냅샷. 판정 행이 없으면 상위 필드가 None."""

    status: Literal["HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"]
    final_disposition: IngredientMappingFinalDisposition | None
    target_ingredient_code: str | None
    target_ingredient_name: str | None
    decision_reason: str | None
    reviewed_by_user_id: int
    reviewed_at: datetime


class IngredientMappingListItem(BaseModel):
    pending_code: str
    raw_name: str
    normalized_source_name: str
    # product_ingredients (product_id, ingredient_id) UNIQUE 구조상 두 값은 항상 같다.
    # API 호환을 위해 둘 다 반환한다.
    product_count: int
    connection_count: int
    status: IngredientMappingStatus
    candidate: IngredientMappingCandidate
    suggestion: IngredientMappingSuggestion | None
    decision: IngredientMappingDecision | None
    available_actions: list[IngredientMappingAction]


class IngredientMappingSummary(BaseModel):
    """페이지·필터와 독립적인 전체 유효 상태 집계."""

    pending_count: int
    held_count: int
    needs_review_count: int
    unclassified_count: int
    approved_count: int
    rejected_count: int


class IngredientMappingPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class IngredientMappingListResponse(BaseModel):
    items: list[IngredientMappingListItem]
    summary: IngredientMappingSummary
    pagination: IngredientMappingPagination


class IngredientMappingRawNameVariant(BaseModel):
    raw_name: str
    product_count: int
    connection_count: int


class IngredientMappingSampleProduct(BaseModel):
    product_code: str
    product_name: str
    raw_name: str
    display_order: int | None
    concentration_text: str | None


class IngredientMappingEvent(BaseModel):
    from_status: Literal["HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"] | None
    to_status: Literal["HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"]
    from_final_disposition: IngredientMappingFinalDisposition | None
    to_final_disposition: IngredientMappingFinalDisposition | None
    from_target_ingredient_code: str | None
    to_target_ingredient_code: str | None
    actor_id: int
    reason: str | None
    evidence_source_url: str | None
    source_reference: str | None
    created_at: datetime


class IngredientMappingDetail(IngredientMappingListItem):
    pending_ingredient_name: str
    raw_name_variants: list[IngredientMappingRawNameVariant]
    sample_products: list[IngredientMappingSampleProduct]
    events: list[IngredientMappingEvent]


# --- 판정 액션 (쓰기) -------------------------------------------------------


class IngredientMappingApproveRequest(BaseModel):
    normalized_source_name: str
    target_ingredient_code: str
    # 승인 사유는 선택. 전달 시 trim 후 1~1,000자(서비스에서 검증).
    decision_reason: str | None = Field(default=None, max_length=1000)


class IngredientMappingReasonRequest(BaseModel):
    """보류·반려·재검토 공통 body. 사유 필수(서비스에서 공백 검증)."""

    normalized_source_name: str
    decision_reason: str = Field(min_length=1, max_length=1000)


class IngredientMappingRejectRequest(IngredientMappingReasonRequest):
    """canonical로 연결하지 않는 최종 분류 확정 요청."""

    final_disposition: IngredientMappingNonMappingFinalDisposition
    evidence_source_url: str | None = Field(default=None, max_length=2000)
    source_reference: str | None = Field(default=None, max_length=255)


class IngredientMappingActionResponse(BaseModel):
    pending_code: str
    normalized_source_name: str
    status: Literal["HELD", "NEEDS_REVIEW", "APPROVED", "REJECTED"]
    final_disposition: IngredientMappingFinalDisposition | None
    target_ingredient_code: str | None
    target_ingredient_name: str | None
    decision_reason: str | None
    reviewed_at: datetime
    available_actions: list[IngredientMappingAction]


class IngredientMappingBulkApprovalPreviewItem(BaseModel):
    pending_code: str
    normalized_source_name: str
    raw_name: str
    product_count: int
    connection_count: int
    target_ingredient_code: str
    target_ingredient_name: str
    alias_source: str
    canonical_source_url: str


class IngredientMappingBulkApprovalPreviewResponse(BaseModel):
    criteria: Literal["KCIA_ALIAS_EXACT"]
    maximum_count: int
    eligible_count: int
    items: list[IngredientMappingBulkApprovalPreviewItem]


class IngredientMappingBulkApprovalItem(BaseModel):
    pending_code: str = Field(min_length=1, max_length=64)
    normalized_source_name: str = Field(min_length=1, max_length=255)
    target_ingredient_code: str = Field(min_length=1, max_length=64)


class IngredientMappingBulkApprovalRequest(BaseModel):
    items: list[IngredientMappingBulkApprovalItem] = Field(min_length=1, max_length=100)
    confirmed_count: int = Field(ge=1, le=100)


class IngredientMappingBulkApprovalResponse(BaseModel):
    batch_reference: str
    approved_count: int
    items: list[IngredientMappingActionResponse]


# --- canonical 검색 (승인 target 선택용, §6) --------------------------------


class CanonicalIngredientSearchItem(BaseModel):
    ingredient_code: str
    name_ko: str
    name_en: str | None
    normalized_name: str | None
    source_url: str | None


class CanonicalIngredientSearchResponse(BaseModel):
    items: list[CanonicalIngredientSearchItem]
    next_cursor: str | None
