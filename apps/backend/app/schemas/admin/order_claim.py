"""관리자 클레임(반품·교환·환불) 목록·상세 조회 응답 스키마 (P1-M1.5-B).

OrderClaim 은 배송완료 주문에 대해 고객이 order_claim_service.create_claim() 으로
생성한다. 승인·거절·처리시작·완료는 이후 청크에서 관리자 액션 API로 추가한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AdminClaimStatus = Literal["REQUESTED", "APPROVED", "REJECTED", "IN_PROGRESS", "COMPLETED", "WITHDRAWN"]

AdminClaimType = Literal["RETURN", "EXCHANGE", "REFUND"]

AdminClaimItemResolution = Literal["REFUND", "EXCHANGE"]

# 목표 상태(성공)/유효 이전 상태(실행) 규칙: 승인 REQUESTED→APPROVED, 거절 REQUESTED→REJECTED,
# 처리시작 APPROVED→IN_PROGRESS, 완료 IN_PROGRESS→COMPLETED. REJECTED/COMPLETED/WITHDRAWN 은 종단 상태.
AdminClaimAction = Literal["APPROVE", "REJECT", "START", "COMPLETE"]


class AdminOrderClaimListItem(BaseModel):
    claim_code: str
    order_code: str
    customer_id: int
    customer_display: str = Field(..., description="User.display_name 또는 user_{id}")
    product_summary: str = Field(..., description="클레임 대상 첫 상품명 + 외 N개")
    claim_type: AdminClaimType
    status: AdminClaimStatus
    reason_code: str
    reason_detail: str | None = None
    refund_amount: int | None = Field(..., description="RETURN/REFUND 타입만 값 존재, EXCHANGE 는 None.")
    requested_at: datetime
    processed_at: datetime | None = Field(..., description="승인·거절 처리 시각. REQUESTED면 None.")
    completed_at: datetime | None = Field(..., description="완료 처리 시각. COMPLETED 전이면 None.")
    available_actions: list[AdminClaimAction] = Field(
        ...,
        description="현재 status 기준 관리자가 수행할 수 있는 다음 액션. 프론트는 이 값을 그대로 사용한다.",
    )


class AdminOrderClaimListResponse(BaseModel):
    items: list[AdminOrderClaimListItem]
    page: int
    page_size: int
    total_count: int


class AdminOrderClaimItemDetail(BaseModel):
    order_item_id: int
    product_name_snapshot: str
    quantity: int
    resolution: AdminClaimItemResolution


class AdminOrderClaimEventDetail(BaseModel):
    from_status: AdminClaimStatus | None
    to_status: AdminClaimStatus
    actor_type: str
    actor_id: int | None
    reason: str | None
    created_at: datetime


class AdminOrderClaimDetailResponse(AdminOrderClaimListItem):
    order_status: str
    items: list[AdminOrderClaimItemDetail]
    events: list[AdminOrderClaimEventDetail]


class AdminOrderClaimActionResponse(BaseModel):
    """승인·거절·처리시작·완료 공통 응답. 승인은 APPROVED(종단 아님, available_actions=[START]),

    거절은 REJECTED(종단, []), 처리시작은 IN_PROGRESS([COMPLETE]), 완료는 COMPLETED(종단, [])로
    서로 다른 available_actions 을 가진다. processed_at 은 승인·거절 시각, completed_at 은 완료
    시각이라 완료 액션의 응답에서는 completed_at 을 봐야 한다(processed_at 은 승인 시점 그대로).
    """

    claim_code: str
    order_code: str
    status: AdminClaimStatus
    processed_at: datetime | None
    completed_at: datetime | None
    available_actions: list[AdminClaimAction]


class AdminClaimCompleteBody(BaseModel):
    restock: bool = Field(..., description="RETURN 완료 시 재고 복구 여부. REFUND/EXCHANGE 에서는 사용 안 함.")


class AdminClaimRejectBody(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=2000)
