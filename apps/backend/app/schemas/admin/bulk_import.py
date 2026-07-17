"""M3-B bulk import의 구조용 요청·검증 결과 스키마.

행별 business validation은 validation service가 담당한다. Pydantic field에
정규식·범위 제약을 두면 잘못된 한 행이 전체 요청을 거절해 부분 성공 계약을
깨므로, 이 파일은 JSON 구조만 확인한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AdminBulkImportRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_sku: Any | None = None
    product_name: Any | None = None
    brand_name: Any | None = None
    category_name: Any | None = None
    price: Any | None = None
    stock_quantity: Any | None = None
    ingredients_raw: Any | None = None


class AdminBulkImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AdminBulkImportRowRequest]


class AdminBulkImportValidationSummary(BaseModel):
    total: int
    valid: int
    failed: int


class AdminBulkImportValidationRowResult(BaseModel):
    row_number: int
    import_sku: str | None
    status: Literal["VALID", "FAILED"]
    field: str | None = None
    error_code: str | None = None
    message: str | None = None


class AdminBulkImportValidationResponse(BaseModel):
    summary: AdminBulkImportValidationSummary
    rows: list[AdminBulkImportValidationRowResult]
