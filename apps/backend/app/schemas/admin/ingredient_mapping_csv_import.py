"""관리자 성분 매핑 CSV dry-run·적용 계약."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


IngredientMappingCsvAction = Literal["MAP_EXISTING", "CREATE_AND_MAP"]
IngredientMappingCsvRowStatus = Literal["VALID", "INVALID", "ALREADY_APPLIED"]


class IngredientMappingCsvRowInput(BaseModel):
    row_number: int = Field(ge=1)
    action: IngredientMappingCsvAction
    pending_code: str = Field(min_length=1, max_length=64)
    normalized_source_name: str = Field(min_length=1, max_length=255)
    expected_connection_count: int = Field(ge=1)
    target_ingredient_code: str = Field(min_length=1, max_length=64)
    target_name_ko: str | None = Field(default=None, max_length=255)
    target_name_en: str | None = Field(default=None, max_length=255)
    decision_reason: str | None = Field(default=None, max_length=1000)
    source_reference: str | None = Field(default=None, max_length=255)

    @field_validator(
        "pending_code",
        "normalized_source_name",
        "target_ingredient_code",
        mode="before",
    )
    @classmethod
    def strip_required_identifiers(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class IngredientMappingCsvPreviewRequest(BaseModel):
    rows: list[IngredientMappingCsvRowInput] = Field(min_length=1, max_length=1000)


class IngredientMappingCsvPreviewRow(BaseModel):
    row_number: int
    status: IngredientMappingCsvRowStatus
    action: IngredientMappingCsvAction
    pending_code: str
    normalized_source_name: str
    target_ingredient_code: str
    target_ingredient_name: str | None
    expected_connection_count: int
    current_connection_count: int
    error_code: str | None = None
    message: str | None = None


class IngredientMappingCsvPreviewSummary(BaseModel):
    total: int
    valid: int
    invalid: int
    already_applied: int
    connection_count: int


class IngredientMappingCsvPreviewResponse(BaseModel):
    preview_digest: str
    summary: IngredientMappingCsvPreviewSummary
    rows: list[IngredientMappingCsvPreviewRow]


class IngredientMappingCsvApplyRequest(IngredientMappingCsvPreviewRequest):
    preview_digest: str = Field(min_length=64, max_length=64)
    confirmed_count: int = Field(ge=1, le=1000)
    refresh_pending_groups: bool = True


class IngredientMappingCsvApplyResponse(BaseModel):
    batch_reference: str
    total: int
    applied: int
    already_applied: int
    moved_connections: int
    collapsed_duplicates: int
    created_canonicals: int
    affected_products: int
    review_refresh: Literal["OK", "FAILED", "NOT_REQUIRED"]
    search_reindex_required: bool
