from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


OFFICIAL_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "recommendation_requested",
        "recommendation_analyzed",
        "recommendation_viewed",
        "recommendation_product_impression",
        "recommendation_product_click",
        "product_viewed",
        "cart_added",
        "checkout_started",
        "order_completed",
        "search_performed",
        "search_no_result",
        "payment_failed",
        "llm_call",
        "api_request_logged",
    }
)

MAX_EVENT_BATCH_SIZE = 50


class EventLogCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: str | None = Field(default=None, max_length=128)
    event_name: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.:-]{0,79}$")
    occurred_at: datetime | None = None
    anonymous_user_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    recommendation_id: str | None = Field(default=None, max_length=128)
    product_id: str | None = Field(default=None, max_length=128)
    rank: int | None = Field(default=None, ge=1)
    source: str | None = Field(default=None, max_length=64)
    page: str | None = Field(default=None, max_length=255)
    cart_id: int | None = Field(default=None, ge=1)
    order_id: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")


class EventLogResponse(BaseModel):
    id: int
    event_id: str
    event_name: str
    occurred_at: datetime
    created_at: datetime
    official_event: bool
    duplicate: bool = False


class EventLogBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventLogCreateRequest] = Field(..., min_length=1, max_length=MAX_EVENT_BATCH_SIZE)


class EventLogBatchResponse(BaseModel):
    accepted_count: int
    duplicate_count: int
    events: list[EventLogResponse]
