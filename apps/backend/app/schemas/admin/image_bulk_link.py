"""M3-C 이미지 대량 연결의 요청·검증 결과 스키마.

검증 서비스는 DB를 변경하지 않는다. 실제 저장 결과 스키마는 Chunk 3에서
별도로 확장한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AdminImageBulkLinkRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_sku: Any | None = None
    image_type: Any | None = None
    display_order: Any | None = None
    storage_key: Any | None = None


class AdminImageBulkLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AdminImageBulkLinkRowRequest]


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
