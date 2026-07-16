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

from pydantic import BaseModel


# 저장 상태(HELD/APPROVED/REJECTED)는 review 행, PENDING 은 행 없이 파생.
IngredientMappingStatus = Literal["PENDING", "HELD", "APPROVED", "REJECTED"]

# 추천 근거. 그룹 정규화명이 alias/canonical 이름과 정확 일치할 때만 채운다.
IngredientMappingMatchSource = Literal["ALIAS_EXACT", "CANONICAL_NAME_EXACT"]

IngredientMappingAction = Literal["APPROVE", "HOLD", "REJECT", "REOPEN"]


class IngredientMappingSuggestion(BaseModel):
    """읽기 전용 추천 후보. DB 정확 일치만 사용하며, 없으면 상위 필드가 None."""

    target_ingredient_id: int
    target_ingredient_code: str
    target_ingredient_name: str
    match_source: IngredientMappingMatchSource


class IngredientMappingDecision(BaseModel):
    """저장된 관리자 판정 스냅샷. 판정 행이 없으면 상위 필드가 None."""

    status: Literal["HELD", "APPROVED", "REJECTED"]
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
    suggestion: IngredientMappingSuggestion | None
    decision: IngredientMappingDecision | None
    available_actions: list[IngredientMappingAction]


class IngredientMappingSummary(BaseModel):
    """페이지·필터와 독립적인 전체 유효 상태 집계."""

    pending_count: int
    held_count: int
    approved_count: int
    rejected_count: int


class IngredientMappingListResponse(BaseModel):
    items: list[IngredientMappingListItem]
    summary: IngredientMappingSummary
    next_cursor: str | None


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
    from_status: Literal["HELD", "APPROVED", "REJECTED"] | None
    to_status: Literal["HELD", "APPROVED", "REJECTED"]
    from_target_ingredient_code: str | None
    to_target_ingredient_code: str | None
    actor_id: int
    reason: str | None
    created_at: datetime


class IngredientMappingDetail(IngredientMappingListItem):
    pending_ingredient_name: str
    raw_name_variants: list[IngredientMappingRawNameVariant]
    sample_products: list[IngredientMappingSampleProduct]
    events: list[IngredientMappingEvent]
