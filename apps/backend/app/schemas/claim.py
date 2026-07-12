from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ClaimType = Literal["RETURN", "EXCHANGE", "REFUND"]
ClaimStatus = Literal["REQUESTED", "APPROVED", "REJECTED", "IN_PROGRESS", "COMPLETED", "WITHDRAWN"]


class OrderClaimItemRequest(BaseModel):
    order_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., ge=1)


class OrderClaimCreateRequest(BaseModel):
    order_code: str = Field(..., min_length=1, max_length=40)
    claim_type: ClaimType
    reason_code: str = Field(..., min_length=1, max_length=40)
    reason_detail: str | None = Field(default=None, max_length=2000)
    items: list[OrderClaimItemRequest] = Field(..., min_length=1)


class OrderClaimItemResponse(BaseModel):
    order_item_id: int
    quantity: int
    resolution: Literal["REFUND", "EXCHANGE"]


class OrderClaimResponse(BaseModel):
    claim_code: str
    order_code: str
    claim_type: ClaimType
    status: ClaimStatus
    reason_code: str
    reason_detail: str | None
    refund_amount: int | None
    requested_at: datetime
    processed_at: datetime | None
    completed_at: datetime | None
    items: list[OrderClaimItemResponse]


class OrderClaimListResponse(BaseModel):
    items: list[OrderClaimResponse]

