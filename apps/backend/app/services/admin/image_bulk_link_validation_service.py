"""M3-C 이미지 대량 연결의 읽기 전용 행 검증 서비스."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductImage
from app.schemas.admin.image_bulk_link import (
    AdminImageBulkLinkRequest,
    AdminImageBulkLinkRowRequest,
    AdminImageBulkLinkValidationResponse,
    AdminImageBulkLinkValidationRowResult,
    AdminImageBulkLinkValidationSummary,
)
from app.schemas.common import ApiError
from app.services.admin.bulk_import_validation_service import IMPORT_SKU_PATTERN
from app.services.product_thumbnail import normalize_thumbnail_storage_key


THUMBNAIL_IMAGE_TYPE = "thumbnail"
DETAIL_IMAGE_TYPE = "detail"


@dataclass(frozen=True)
class VerifiedImageBulkLinkRow:
    row_number: int
    import_sku: str
    product_id: int
    product_code: str
    image_type: str
    display_order: int
    storage_key: str
    existing_storage_key: str | None

    @property
    def is_noop(self) -> bool:
        return self.existing_storage_key == self.storage_key


@dataclass(frozen=True)
class FailedImageBulkLinkRow:
    row_number: int
    import_sku: str | None
    field: str
    error_code: str
    message: str


@dataclass(frozen=True)
class ImageBulkLinkValidationOutcome:
    verified_rows: list[VerifiedImageBulkLinkRow]
    failed_rows: list[FailedImageBulkLinkRow]

    def to_response(self) -> AdminImageBulkLinkValidationResponse:
        rows = [
            AdminImageBulkLinkValidationRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="VALID",
            )
            for row in self.verified_rows
        ]
        rows.extend(
            AdminImageBulkLinkValidationRowResult(
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
        return AdminImageBulkLinkValidationResponse(
            summary=AdminImageBulkLinkValidationSummary(
                total=len(rows),
                valid=len(self.verified_rows),
                failed=len(self.failed_rows),
            ),
            rows=rows,
        )


@dataclass(frozen=True)
class _ParsedImageBulkLinkRow:
    row_number: int
    import_sku: str
    image_type: str
    display_order: int
    storage_key: str

    @property
    def slot(self) -> tuple[str, int]:
        return (self.image_type, self.display_order)


def validate_image_bulk_link(
    session: Session, request: AdminImageBulkLinkRequest
) -> ImageBulkLinkValidationOutcome:
    """이미지 행을 검증한다. 이 함수는 SELECT만 수행하며 저장하지 않는다."""
    parsed_rows: list[_ParsedImageBulkLinkRow] = []
    failed_rows: list[FailedImageBulkLinkRow] = []
    seen_slots: set[tuple[str, str, int]] = set()

    for row_number, row in enumerate(request.rows, start=1):
        parsed, failure = _parse_row(row_number, row)
        if failure is not None:
            failed_rows.append(failure)
            continue
        assert parsed is not None

        request_slot = (parsed.import_sku, *parsed.slot)
        if request_slot in seen_slots:
            failed_rows.append(
                _failure(
                    row_number,
                    parsed.import_sku,
                    "display_order",
                    "DUPLICATE_IMAGE_SLOT_IN_REQUEST",
                    "같은 import_sku, image_type, display_order 조합은 요청에서 한 번만 사용할 수 있습니다.",
                )
            )
            continue
        seen_slots.add(request_slot)
        parsed_rows.append(parsed)

    products_by_sku = _load_products_by_import_sku(
        session, {row.import_sku for row in parsed_rows}
    )
    product_images = _load_product_images(
        session, {product.id for product in products_by_sku.values()}
    )

    verified_rows: list[VerifiedImageBulkLinkRow] = []
    requested_keys: dict[int, dict[str, tuple[str, int]]] = {}
    for row in parsed_rows:
        product = products_by_sku.get(row.import_sku)
        if product is None:
            failed_rows.append(
                _failure(
                    row.row_number,
                    row.import_sku,
                    "import_sku",
                    "IMPORT_SKU_NOT_FOUND",
                    "이미지 연결 대상 상품을 import_sku로 찾을 수 없습니다.",
                )
            )
            continue

        images_by_slot, slots_by_key = product_images.get(product.id, ({}, {}))
        existing_slot = slots_by_key.get(row.storage_key)
        if existing_slot is not None and existing_slot != row.slot:
            failed_rows.append(_storage_key_conflict(row, "다른 기존 슬롯"))
            continue

        product_requested_keys = requested_keys.setdefault(product.id, {})
        requested_slot = product_requested_keys.get(row.storage_key)
        if requested_slot is not None and requested_slot != row.slot:
            failed_rows.append(_storage_key_conflict(row, "다른 요청 슬롯"))
            continue
        product_requested_keys[row.storage_key] = row.slot

        verified_rows.append(
            VerifiedImageBulkLinkRow(
                row_number=row.row_number,
                import_sku=row.import_sku,
                product_id=product.id,
                product_code=product.product_code,
                image_type=row.image_type,
                display_order=row.display_order,
                storage_key=row.storage_key,
                existing_storage_key=images_by_slot.get(row.slot),
            )
        )

    return ImageBulkLinkValidationOutcome(
        verified_rows=verified_rows,
        failed_rows=failed_rows,
    )


def _parse_row(
    row_number: int, row: AdminImageBulkLinkRowRequest
) -> tuple[_ParsedImageBulkLinkRow | None, FailedImageBulkLinkRow | None]:
    import_sku, failure = _parse_import_sku(row.import_sku, row_number)
    if failure is not None:
        return None, failure
    image_type, failure = _parse_image_type(row.image_type, row_number, import_sku)
    if failure is not None:
        return None, failure
    display_order, failure = _parse_display_order(
        row.display_order, image_type, row_number, import_sku
    )
    if failure is not None:
        return None, failure
    storage_key, failure = _parse_storage_key(row.storage_key, row_number, import_sku)
    if failure is not None:
        return None, failure
    return (
        _ParsedImageBulkLinkRow(
            row_number=row_number,
            import_sku=import_sku,
            image_type=image_type,
            display_order=display_order,
            storage_key=storage_key,
        ),
        None,
    )


def _parse_import_sku(
    value: object, row_number: int
) -> tuple[str | None, FailedImageBulkLinkRow | None]:
    if not isinstance(value, str) or not IMPORT_SKU_PATTERN.fullmatch(value):
        return None, _failure(
            row_number,
            value if isinstance(value, str) else None,
            "import_sku",
            "INVALID_IMAGE_INPUT",
            "import_sku는 1~64자의 대문자 영문·숫자·._- 형식이어야 합니다.",
        )
    return value, None


def _parse_image_type(
    value: object, row_number: int, import_sku: str
) -> tuple[str | None, FailedImageBulkLinkRow | None]:
    if value not in {THUMBNAIL_IMAGE_TYPE, DETAIL_IMAGE_TYPE}:
        return None, _failure(
            row_number,
            import_sku,
            "image_type",
            "INVALID_IMAGE_INPUT",
            "image_type은 thumbnail 또는 detail이어야 합니다.",
        )
    return str(value), None


def _parse_display_order(
    value: object,
    image_type: str,
    row_number: int,
    import_sku: str,
) -> tuple[int | None, FailedImageBulkLinkRow | None]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None, _failure(
            row_number,
            import_sku,
            "display_order",
            "INVALID_IMAGE_INPUT",
            "display_order는 정수여야 합니다.",
        )
    valid = (
        image_type == THUMBNAIL_IMAGE_TYPE and value == 0
    ) or (image_type == DETAIL_IMAGE_TYPE and value >= 1)
    if not valid:
        return None, _failure(
            row_number,
            import_sku,
            "display_order",
            "INVALID_IMAGE_INPUT",
            "thumbnail의 display_order는 0이고 detail은 1 이상이어야 합니다.",
        )
    return value, None


def _parse_storage_key(
    value: object, row_number: int, import_sku: str
) -> tuple[str | None, FailedImageBulkLinkRow | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _failure(
            row_number,
            import_sku,
            "storage_key",
            "INVALID_IMAGE_INPUT",
            "storage_key는 비어 있을 수 없습니다.",
        )
    try:
        storage_key = normalize_thumbnail_storage_key(value)
    except ApiError as exc:
        return None, _failure(
            row_number,
            import_sku,
            "storage_key",
            "INVALID_IMAGE_INPUT",
            exc.message,
        )
    if storage_key is None:
        raise RuntimeError("non-empty storage_key normalized to None")
    return storage_key, None


def _load_products_by_import_sku(session: Session, import_skus: set[str]) -> dict[str, Product]:
    if not import_skus:
        return {}
    products = session.execute(
        select(Product).where(Product.import_sku.in_(import_skus))
    ).scalars()
    return {
        product.import_sku: product
        for product in products
        if product.import_sku is not None
    }


def _load_product_images(
    session: Session, product_ids: set[int]
) -> dict[int, tuple[dict[tuple[str, int], str], dict[str, tuple[str, int]]]]:
    if not product_ids:
        return {}
    images_by_product: dict[
        int, tuple[dict[tuple[str, int], str], dict[str, tuple[str, int]]]
    ] = {}
    for image in session.execute(
        select(ProductImage).where(ProductImage.product_id.in_(product_ids))
    ).scalars():
        images_by_slot, slots_by_key = images_by_product.setdefault(image.product_id, ({}, {}))
        slot = (image.image_type, image.display_order)
        images_by_slot[slot] = image.storage_key
        slots_by_key[image.storage_key] = slot
    return images_by_product


def _storage_key_conflict(
    row: _ParsedImageBulkLinkRow, conflict_scope: str
) -> FailedImageBulkLinkRow:
    return _failure(
        row.row_number,
        row.import_sku,
        "storage_key",
        "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT",
        f"같은 상품의 {conflict_scope}이(가) 이미 사용하는 storage_key입니다.",
    )


def _failure(
    row_number: int,
    import_sku: str | None,
    field: str,
    error_code: str,
    message: str,
) -> FailedImageBulkLinkRow:
    return FailedImageBulkLinkRow(
        row_number=row_number,
        import_sku=import_sku,
        field=field,
        error_code=error_code,
        message=message,
    )
