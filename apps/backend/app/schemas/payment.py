from datetime import datetime

from pydantic import BaseModel


class PaymentActionResponse(BaseModel):
    order_code: str
    payment_code: str
    order_status: str
    payment_status: str
    approved_at: datetime | None = None
    failed_at: datetime | None = None
