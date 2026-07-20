"""관리자 주문·결제 상태 조회 응답 스키마.

주문·결제 상태(order_status/payment_status)는 DB의 영문 enum을 그대로 응답하며,
한글 라벨 변환은 프론트가 담당한다. 신규 테이블 없이 기존 Order/OrderItem/Payment
모델에서 파생하며, 파생 규칙은 각 필드의 description 을 참조한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# 주문 상태 15종 (db/models/commerce.py ORDER_STATUS_VALUES 와 정합)
AdminOrderStatus = Literal[
    "PENDING_PAYMENT",
    "PAID",
    "PAYMENT_FAILED",
    "EXPIRED",
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
    "CANCEL_REQUESTED",
    "CANCELED",
    "RETURN_REQUESTED",
    "RETURNED",
    "REFUND_REQUESTED",
    "REFUNDED",
    "EXCHANGE_REQUESTED",
    "EXCHANGED",
]

# 결제 상태 10종 (db/models/commerce.py PAYMENT_STATUS_VALUES 와 정합)
AdminPaymentStatus = Literal[
    "READY",
    "CONFIRMING",
    "UNKNOWN",
    "APPROVED",
    "FAILED",
    "CANCELED",
    "EXPIRED",
    "REFUND_REQUESTED",
    "REFUNDED",
    "PARTIALLY_REFUNDED",
]

# 관리자가 주문에 취할 수 있는 다음 액션. 현재는 배송 액션만 존재하며(M1.5-A),
# 취소·반품·환불·교환 액션은 M1.5-B에서 백엔드가 공유하는 API 계약에 맞춰 추가한다.
AdminOrderAction = Literal[
    "START_PREPARATION",
    "START_SHIPMENT",
    "COMPLETE_DELIVERY",
]

# 배송 액션(prepare/dispatch/deliver) 성공 응답에서 실제로 나올 수 있는 상태 3종만 허용.
# 서비스가 실수로 CANCELED/PENDING_PAYMENT 등을 성공 응답으로 반환하는 걸 스키마가 막는다.
AdminShipmentResultStatus = Literal[
    "PREPARING_SHIPMENT",
    "SHIPPED",
    "DELIVERED",
]

# 배송 전이 응답에서 실제로 나올 수 있는 다음 액션만 허용(START_PREPARATION 제외).
# 전이가 성공한 시점엔 주문이 이미 PREPARING_SHIPMENT 이상이라 START_PREPARATION 은
# 나올 수 없다 — order_status 를 좁힌 것과 같은 이유로, M1.5-B가 취소·반품·환불·교환
# 액션을 AdminOrderAction 에 추가해도 배송 응답에 섞여 나오는 걸 타입이 막아준다.
AdminShipmentNextAction = Literal[
    "START_SHIPMENT",
    "COMPLETE_DELIVERY",
]


class AdminOrderListItem(BaseModel):
    id: int
    order_code: str
    customer_id: int
    customer_display: str = Field(..., description="User.display_name 또는 user_{id}")
    product_summary: str = Field(..., description="첫 상품명 + 외 N개")
    item_count: int
    total_quantity: int
    total_amount: int
    currency: str
    order_status: AdminOrderStatus
    payment_status: AdminPaymentStatus | None = Field(
        ...,
        description="결제 레코드가 있으면 그 상태, 결제 레코드 자체가 없으면 None(=payment_issue 확인).",
    )
    payment_issue: Literal["PAYMENT_NOT_FOUND"] | None = Field(
        ...,
        description="결제 레코드가 없는 이상 데이터일 때 PAYMENT_NOT_FOUND, 정상이면 None.",
    )
    reserved_quantity: int = Field(
        ...,
        description="예약 재고 수량. PENDING_PAYMENT 일 때만 total_quantity, 그 외 0.",
    )
    recommendation_ids: list[str] = Field(
        ...,
        description="주문 내 OrderItem 들의 recommendation_id 중복 제거 목록. 추천 주문이 아니면 서비스가 명시적으로 [] 전달.",
    )
    ordered_at: datetime = Field(
        ...,
        description="Order creation timestamp used for newest-first sorting and display.",
    )
    paid_at: datetime | None = Field(
        ...,
        description="Order.paid_at 그대로. 결제 미완료·정보 누락 주문은 None.",
    )
    shipped_at: datetime | None = Field(
        ...,
        description="Order.shipped_at 그대로. 배송 시작(SHIPPED) 전이 시 최초 1회만 기록되며, 그 전이면 None.",
    )
    delivered_at: datetime | None = Field(
        ...,
        description="Order.delivered_at 그대로. 배송완료(DELIVERED) 전이 시 최초 1회만 기록되며, 그 전이면 None.",
    )
    available_actions: list[AdminOrderAction] = Field(
        ...,
        description="현재 주문·결제 상태를 기준으로 관리자가 수행할 수 있는 다음 액션. 프론트는 이 값을 직접 계산하지 않고 그대로 사용한다.",
    )
    updated_at: datetime


class AdminOrderSummary(BaseModel):
    pending_payment_count: int
    preparing_shipment_count: int
    cancel_requested_count: int
    reserved_quantity_total: int


class AdminOrderPagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class AdminOrderListResponse(BaseModel):
    items: list[AdminOrderListItem]
    summary: AdminOrderSummary
    pagination: AdminOrderPagination


class AdminOrderShipmentActionResponse(BaseModel):
    """배송 액션(prepare/dispatch/deliver) 공통 응답.

    멱등 재요청(이미 목표 상태)이면 기존 값을 그대로 반환하고 updated_at 을 갱신하지
    않는다. 그 외 상태에서 호출되면 서비스가 ApiError(409)를 던진다(응답에 도달하지 않음).
    """

    order_code: str
    order_status: AdminShipmentResultStatus
    shipped_at: datetime | None = Field(
        ...,
        description="Order.shipped_at 그대로. SHIPPED 전이 최초 1회만 기록, 그 전이면 None.",
    )
    delivered_at: datetime | None = Field(
        ...,
        description="Order.delivered_at 그대로. DELIVERED 전이 최초 1회만 기록, 그 전이면 None.",
    )
    available_actions: list[AdminShipmentNextAction] = Field(
        ...,
        description="전이 후 상태 기준으로 이어서 할 수 있는 다음 액션. 목록 조회와 동일 규칙(결제 승인 확인 포함).",
    )
    updated_at: datetime
