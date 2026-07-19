"""M3-C 이미지 대량 연결의 요청·검증·저장 결과 스키마."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminImageBulkLinkRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_sku: Any | None = None
    image_type: Any | None = None
    display_order: Any | None = None
    storage_key: Any | None = None


class AdminImageBulkLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AdminImageBulkLinkRowRequest] = Field(min_length=1, max_length=1000)


class AdminImageBulkLinkValidationSummary(BaseModel):
    total: int
    valid: int
    failed: int


class AdminImageBulkLinkValidationRowResult(BaseModel):
    row_number: int
    import_sku: str | None
    status: Literal["VALID", "FAILED"]
    field: str | None = None
    error_code: str | None = None
    message: str | None = None


class AdminImageBulkLinkValidationResponse(BaseModel):
    summary: AdminImageBulkLinkValidationSummary
    rows: list[AdminImageBulkLinkValidationRowResult]


class AdminImageBulkLinkSummary(BaseModel):
    total: int
    updated: int
    skipped: int
    failed: int


class AdminImageBulkLinkRowResult(BaseModel):
    row_number: int
    import_sku: str | None
    status: Literal["UPDATED", "SKIPPED", "FAILED"]
    product_code: str | None = None
    field: str | None = None
    error_code: str | None = None
    message: str | None = None


class AdminImageBulkLinkResponse(BaseModel):
    summary: AdminImageBulkLinkSummary
    rows: list[AdminImageBulkLinkRowResult]
