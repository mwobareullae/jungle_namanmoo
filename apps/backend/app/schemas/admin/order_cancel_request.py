"""관리자 주문 취소 요청 조회·승인·거절 응답 스키마.

취소 요청(order_cancel_requests)은 고객이 결제완료 주문을 취소 신청할 때
order_cancel_service.cancel_order()가 생성하며, 관리자가 승인/거절해
payment_cancel_service.cancel_paid_order()로 실제 취소를 처리한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.admin.order import AdminOrderStatus, AdminPaymentStatus


AdminCancelRequestStatus = Literal["REQUESTED", "APPROVED", "REJECTED"]

AdminCancelRequestAction = Literal["APPROVE", "REJECT"]

# 승인/거절 액션 응답 전용 — 액션이 성공하면 결과는 항상 결정된 상태이므로 REQUESTED는 나올 수 없다.
AdminCancelRequestDecisionStatus = Literal["APPROVED", "REJECTED"]

AdminPaymentProvider = Literal["MOCK", "TOSS", "KAKAO_PAY", "NAVER_PAY"]


class AdminOrderCancelRequestItem(BaseModel):
    request_code: str
    order_code: str
    customer_id: int
    customer_display: str = Field(..., description="User.display_name 또는 user_{id}")
    status: AdminCancelRequestStatus
    reason_code: str | None = Field(..., description="고객이 취소 신청 시 남긴 사유 코드. 없으면 None.")
    reason_detail: str | None = None
    decision_reason: str | None = Field(
        ..., description="관리자가 거절 시 남긴 사유. REQUESTED/APPROVED면 None."
    )
    requested_at: datetime
    processed_at: datetime | None = Field(..., description="승인·거절 처리 시각. REQUESTED면 None.")
    available_actions: list[AdminCancelRequestAction] = Field(
        ...,
        description=(
            "현재 상태 기준으로 관리자가 수행할 수 있는 다음 액션. REJECT는 "
            "request=REQUESTED + order=CANCEL_REQUESTED + payment=APPROVED 일 때만 포함하고, "
            "APPROVE는 REJECT 조건에 더해 payment.provider=MOCK 일 때만 포함한다 "
            "(비MOCK 결제는 cancel_paid_order()가 이미 409로 막으므로 버튼 자체를 노출하지 않는다)."
        ),
    )


class AdminOrderCancelRequestListResponse(BaseModel):
    items: list[AdminOrderCancelRequestItem]
    next_cursor: str | None


class AdminOrderCancelRequestDetailResponse(AdminOrderCancelRequestItem):
    order_status: AdminOrderStatus
    payment_status: AdminPaymentStatus | None = Field(
        ..., description="결제 레코드가 있으면 그 상태, 결제 레코드 자체가 없으면 None."
    )
    payment_provider: AdminPaymentProvider | None = Field(
        ..., description="결제 레코드가 있으면 그 provider, 결제 레코드 자체가 없으면 None."
    )
    product_summary: str = Field(..., description="첫 상품명 + 외 N개")
    total_amount: int
    currency: str


class AdminOrderCancelRequestActionResponse(BaseModel):
    """승인·거절 공통 응답. order_status 를 실제 결과값 2종으로 좁혀 다른 값 유출을 차단한다."""

    request_code: str
    order_code: str
    status: AdminCancelRequestDecisionStatus
    order_status: Literal["CANCELED", "PAID"]
    decision_reason: str | None
    processed_at: datetime
    available_actions: list[AdminCancelRequestAction] = Field(
        ...,
        max_length=0,
        description="승인·거절 직후 요청은 항상 종단 상태이므로 [] 만 허용한다(계약으로 강제).",
    )


class AdminCancelRequestRejectBody(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=2000)
