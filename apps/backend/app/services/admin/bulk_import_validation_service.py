"""M3-B bulk import의 저장 전 행별 검증.

상품·재고·성분을 저장하거나 resolve_many를 호출하지 않는다. pending 생성은 상품
단위 트랜잭션이 필요한 Chunk 3의 책임이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas.admin.bulk_import import (
    AdminBulkImportRequest,
    AdminBulkImportRowRequest,
    AdminBulkImportValidationResponse,
    AdminBulkImportValidationRowResult,
    AdminBulkImportValidationSummary,
)
from app.schemas.common import ApiError
from app.services.admin.brand_category_resolution_service import (
    AMBIGUOUS,
    FOUND,
    INACTIVE,
    BrandResolution,
    CategoryResolution,
    resolve_brands,
    resolve_categories,
)
from app.services.ingredient_resolution_service import (
    MAX_INGREDIENTS_PER_PRODUCT,
    MAX_RAW_NAME_LENGTH,
    normalize_for_resolution,
)


MAX_BULK_IMPORT_ROWS = 200
MAX_PRODUCT_NAME_LENGTH = 512
MAX_BRAND_NAME_LENGTH = 120
MAX_CATEGORY_NAME_LENGTH = 80
IMPORT_SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")


@dataclass(frozen=True)
class VerifiedBulkImportRow:
    row_number: int
    import_sku: str
    product_name: str
    brand_id: int
    category_id: int
    price: int
    stock_quantity: int
    ingredient_tokens: tuple[str, ...]


@dataclass(frozen=True)
class FailedBulkImportRow:
    row_number: int
    import_sku: str | None
    field: str
    error_code: str
    message: str


@dataclass(frozen=True)
class BulkImportValidationOutcome:
    verified_rows: list[VerifiedBulkImportRow]
    failed_rows: list[FailedBulkImportRow]

    def to_response(self) -> AdminBulkImportValidationResponse:
        rows = [
            AdminBulkImportValidationRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="VALID",
            )
            for row in self.verified_rows
        ]
        rows.extend(
            AdminBulkImportValidationRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="FAILED",
                field=row.field,
                error_code=row.error_code,
                message=row.message,
            )
            for row in self.failed_rows
        )
        rows.sort(key=lambda row: row.row_number)
        return AdminBulkImportValidationResponse(
            summary=AdminBulkImportValidationSummary(
                total=len(rows),
                valid=len(self.verified_rows),
                failed=len(self.failed_rows),
            ),
            rows=rows,
        )


@dataclass(frozen=True)
class _ParsedBulkImportRow:
    row_number: int
    import_sku: str
    product_name: str
    brand_name: str
    category_name: str
    price: int
    stock_quantity: int
    ingredient_tokens: tuple[str, ...]


def validate_bulk_import(
    session: Session, request: AdminBulkImportRequest
) -> BulkImportValidationOutcome:
    """행별 오류를 모아 반환하고, 200행 초과만 요청 전체 오류로 처리한다."""
    if len(request.rows) > MAX_BULK_IMPORT_ROWS:
        raise ApiError(
            400,
            "INVALID_INPUT",
            f"한 번에 최대 {MAX_BULK_IMPORT_ROWS}행까지 검증할 수 있습니다.",
        )

    parsed_rows: list[_ParsedBulkImportRow] = []
    failed_rows: list[FailedBulkImportRow] = []
    seen_import_skus: set[str] = set()

    for row_number, row in enumerate(request.rows, start=1):
        import_sku, sku_error = _parse_import_sku(row.import_sku, row_number)
        if sku_error is not None:
            failed_rows.append(sku_error)
            continue
        if import_sku in seen_import_skus:
            failed_rows.append(
                _failure(
                    row_number,
                    import_sku,
                    "import_sku",
                    "DUPLICATE_IMPORT_SKU_IN_REQUEST",
                    "같은 요청에 import_sku가 중복되어 있습니다.",
                )
            )
            continue
        seen_import_skus.add(import_sku)

        parsed, failure = _parse_row(row_number, import_sku, row)
        if failure is not None:
            failed_rows.append(failure)
        else:
            parsed_rows.append(parsed)

    brand_resolutions = resolve_brands(session, [row.brand_name for row in parsed_rows])
    category_resolutions = resolve_categories(
        session, [row.category_name for row in parsed_rows]
    )

    verified_rows: list[VerifiedBulkImportRow] = []
    for row in parsed_rows:
        brand = brand_resolutions[normalize_for_resolution(row.brand_name)]
        brand_failure = _brand_failure(row, brand)
        if brand_failure is not None:
            failed_rows.append(brand_failure)
            continue

        category = category_resolutions[normalize_for_resolution(row.category_name)]
        category_failure = _category_failure(row, category)
        if category_failure is not None:
            failed_rows.append(category_failure)
            continue

        verified_rows.append(
            VerifiedBulkImportRow(
                row_number=row.row_number,
                import_sku=row.import_sku,
                product_name=row.product_name,
                brand_id=_require_found_brand_id(brand),
                category_id=_require_found_category_id(category),
                price=row.price,
                stock_quantity=row.stock_quantity,
                ingredient_tokens=row.ingredient_tokens,
            )
        )

    return BulkImportValidationOutcome(
        verified_rows=verified_rows,
        failed_rows=failed_rows,
    )


def _parse_import_sku(
    value: object, row_number: int
) -> tuple[str | None, FailedBulkImportRow | None]:
    if not isinstance(value, str) or not IMPORT_SKU_PATTERN.fullmatch(value):
        return None, _failure(
            row_number,
            value if isinstance(value, str) else None,
            "import_sku",
            "INVALID_INPUT",
            "import_sku는 1~64자의 대문자 영문·숫자·._- 형식이어야 합니다.",
        )
    return value, None


def _parse_row(
    row_number: int, import_sku: str, row: AdminBulkImportRowRequest
) -> tuple[_ParsedBulkImportRow | None, FailedBulkImportRow | None]:
    product_name, failure = _required_text(
        row.product_name, row_number, import_sku, "product_name", MAX_PRODUCT_NAME_LENGTH
    )
    if failure is not None:
        return None, failure
    brand_name, failure = _required_text(
        row.brand_name, row_number, import_sku, "brand_name", MAX_BRAND_NAME_LENGTH
    )
    if failure is not None:
        return None, failure
    category_name, failure = _required_text(
        row.category_name, row_number, import_sku, "category_name", MAX_CATEGORY_NAME_LENGTH
    )
    if failure is not None:
        return None, failure
    price, failure = _positive_int(row.price, row_number, import_sku, "price")
    if failure is not None:
        return None, failure
    stock_quantity, failure = _non_negative_int(
        row.stock_quantity, row_number, import_sku, "stock_quantity"
    )
    if failure is not None:
        return None, failure
    ingredient_tokens, failure = _parse_ingredients(
        row.ingredients_raw, row_number, import_sku
    )
    if failure is not None:
        return None, failure
    return (
        _ParsedBulkImportRow(
            row_number=row_number,
            import_sku=import_sku,
            product_name=product_name,
            brand_name=brand_name,
            category_name=category_name,
            price=price,
            stock_quantity=stock_quantity,
            ingredient_tokens=ingredient_tokens,
        ),
        None,
    )


def _required_text(
    value: object,
    row_number: int,
    import_sku: str,
    field: str,
    max_length: int,
) -> tuple[str | None, FailedBulkImportRow | None]:
    if not isinstance(value, str):
        return None, _failure(
            row_number, import_sku, field, "INVALID_PRODUCT_FIELD", f"{field}은 문자열이어야 합니다."
        )
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        return None, _failure(
            row_number,
            import_sku,
            field,
            "INVALID_PRODUCT_FIELD",
            f"{field}은 1~{max_length}자여야 합니다.",
        )
    return normalized, None


def _positive_int(
    value: object, row_number: int, import_sku: str, field: str
) -> tuple[int | None, FailedBulkImportRow | None]:
    parsed = _parse_integer(value)
    if parsed is None or parsed <= 0:
        return None, _failure(
            row_number, import_sku, field, "INVALID_PRODUCT_FIELD", f"{field}은 양의 정수여야 합니다."
        )
    return parsed, None


def _non_negative_int(
    value: object, row_number: int, import_sku: str, field: str
) -> tuple[int | None, FailedBulkImportRow | None]:
    parsed = _parse_integer(value)
    if parsed is None or parsed < 0:
        return None, _failure(
            row_number, import_sku, field, "INVALID_PRODUCT_FIELD", f"{field}은 0 이상의 정수여야 합니다."
        )
    return parsed, None


def _parse_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def _parse_ingredients(
    value: object, row_number: int, import_sku: str
) -> tuple[tuple[str, ...] | None, FailedBulkImportRow | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _failure(
            row_number,
            import_sku,
            "ingredients_raw",
            "INVALID_INGREDIENT_INPUT",
            "ingredients_raw는 비어 있을 수 없습니다.",
        )

    tokens = tuple(token.strip() for token in value.split("|"))
    if any(not token for token in tokens):
        return None, _failure(
            row_number,
            import_sku,
            "ingredients_raw",
            "INVALID_INGREDIENT_INPUT",
            "성분 구분 뒤 빈 토큰이 있으면 안 됩니다.",
        )
    if len(tokens) > MAX_INGREDIENTS_PER_PRODUCT:
        return None, _failure(
            row_number,
            import_sku,
            "ingredients_raw",
            "INVALID_INGREDIENT_INPUT",
            f"성분은 최대 {MAX_INGREDIENTS_PER_PRODUCT}개까지 허용합니다.",
        )
    if any(len(token) > MAX_RAW_NAME_LENGTH for token in tokens):
        return None, _failure(
            row_number,
            import_sku,
            "ingredients_raw",
            "INVALID_INGREDIENT_INPUT",
            f"성분명은 최대 {MAX_RAW_NAME_LENGTH}자까지 허용합니다.",
        )
    if any("%" in token for token in tokens):
        return None, _failure(
            row_number,
            import_sku,
            "ingredients_raw",
            "INVALID_INGREDIENT_INPUT",
            "`%` 문자는 현재 성분 입력 형식에서 지원하지 않습니다.",
        )
    return tokens, None


def _brand_failure(
    row: _ParsedBulkImportRow, resolution: BrandResolution
) -> FailedBulkImportRow | None:
    if resolution.status == FOUND:
        return None
    code = {
        "NOT_FOUND": "BRAND_NOT_FOUND",
        AMBIGUOUS: "BRAND_AMBIGUOUS",
        INACTIVE: "BRAND_INACTIVE",
    }[resolution.status]
    return _failure(
        row.row_number,
        row.import_sku,
        "brand_name",
        code,
        f"브랜드를 사용할 수 없습니다: {row.brand_name}",
    )


def _category_failure(
    row: _ParsedBulkImportRow, resolution: CategoryResolution
) -> FailedBulkImportRow | None:
    if resolution.status == FOUND:
        return None
    code = {
        "NOT_FOUND": "CATEGORY_NOT_FOUND",
        AMBIGUOUS: "CATEGORY_AMBIGUOUS",
        INACTIVE: "CATEGORY_INACTIVE",
    }[resolution.status]
    return _failure(
        row.row_number,
        row.import_sku,
        "category_name",
        code,
        f"카테고리를 사용할 수 없습니다: {row.category_name}",
    )


def _require_found_brand_id(resolution: BrandResolution) -> int:
    """FOUND 결과는 항상 brand_id를 가져야 한다."""
    if resolution.status != FOUND or resolution.brand_id is None:
        raise RuntimeError("brand resolution marked FOUND without brand_id")
    return resolution.brand_id


def _require_found_category_id(resolution: CategoryResolution) -> int:
    """FOUND 결과는 항상 category_id를 가져야 한다."""
    if resolution.status != FOUND or resolution.category_id is None:
        raise RuntimeError("category resolution marked FOUND without category_id")
    return resolution.category_id


def _failure(
    row_number: int,
    import_sku: str | None,
    field: str,
    error_code: str,
    message: str,
) -> FailedBulkImportRow:
    return FailedBulkImportRow(
        row_number=row_number,
        import_sku=import_sku,
        field=field,
        error_code=error_code,
        message=message,
    )
