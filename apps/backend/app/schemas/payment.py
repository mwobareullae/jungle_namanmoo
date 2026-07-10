from datetime import datetime

from pydantic import BaseModel, Field


class TossPaymentConfirmRequest(BaseModel):
    payment_key: str = Field(..., min_length=1, max_length=200)
    order_code: str = Field(..., min_length=1, max_length=64)
    amount: int = Field(..., ge=0)


class PaymentActionResponse(BaseModel):
    order_code: str
    payment_code: str
    order_status: str
    payment_status: str
    approved_at: datetime | None = None
    failed_at: datetime | None = None
