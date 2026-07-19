"""M3-C 이미지 대량 연결의 행별 저장 서비스.

검증을 통과한 행만 처리한다. 각 이미지 행은 독립 savepoint로 저장하며,
서비스는 flush까지만 수행한다. 전체 commit과 커밋 후 ES 동기화는 라우트가
담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.catalog import Product, ProductImage
from app.db.models.commerce import Inventory
from app.schemas.admin.image_bulk_link import (
    AdminImageBulkLinkResponse,
    AdminImageBulkLinkRowResult,
    AdminImageBulkLinkSummary,
)
from app.schemas.common import ApiError
from app.services.admin.image_bulk_link_validation_service import (
    FailedImageBulkLinkRow,
    ImageBulkLinkValidationOutcome,
    VerifiedImageBulkLinkRow,
)
from app.services.product_thumbnail import set_product_thumbnail


DETAIL_IMAGE_TYPE = "detail"


@dataclass(frozen=True)
class UpdatedImageBulkLinkRow:
    row_number: int
    import_sku: str
    product_code: str


@dataclass(frozen=True)
class SkippedImageBulkLinkRow:
    row_number: int
    import_sku: str
    product_code: str


@dataclass
class ImageBulkLinkStorageOutcome:
    updated_rows: list[UpdatedImageBulkLinkRow] = field(default_factory=list)
    skipped_rows: list[SkippedImageBulkLinkRow] = field(default_factory=list)
    failed_rows: list[FailedImageBulkLinkRow] = field(default_factory=list)
    catalog_sync_product_codes: set[str] = field(default_factory=set)

    def to_response(self) -> AdminImageBulkLinkResponse:
        rows: list[AdminImageBulkLinkRowResult] = [
            AdminImageBulkLinkRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="UPDATED",
                product_code=row.product_code,
            )
            for row in self.updated_rows
        ]
        rows.extend(
            AdminImageBulkLinkRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="SKIPPED",
                product_code=row.product_code,
            )
            for row in self.skipped_rows
        )
        rows.extend(
            AdminImageBulkLinkRowResult(
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
        return AdminImageBulkLinkResponse(
            summary=AdminImageBulkLinkSummary(
                total=len(rows),
                updated=len(self.updated_rows),
                skipped=len(self.skipped_rows),
                failed=len(self.failed_rows),
            ),
            rows=rows,
        )


def run_image_bulk_link(
    session: Session,
    validation: ImageBulkLinkValidationOutcome,
    *,
    now: datetime | None = None,
) -> ImageBulkLinkStorageOutcome:
    """검증 완료 이미지를 행별 savepoint로 연결한다.

    같은 슬롯의 같은 storage_key는 SKIPPED로 반환한다. 실제 변경된 판매 중
    상품만 결과에 기록하며, 호출자는 commit 후 해당 상품만 ES에 동기화한다.
    """

    timestamp = now or datetime.now(UTC)
    outcome = ImageBulkLinkStorageOutcome(failed_rows=list(validation.failed_rows))

    for row in validation.verified_rows:
        try:
            with session.begin_nested():
                product = session.execute(
                    select(Product).where(Product.id == row.product_id).with_for_update()
                ).scalar_one_or_none()
                if product is None:
                    raise ApiError(404, "PRODUCT_NOT_FOUND", "이미지 연결 대상 상품을 찾을 수 없습니다.")

                changed = _set_image_slot(session, product=product, row=row)
                if not changed:
                    outcome.skipped_rows.append(
                        SkippedImageBulkLinkRow(
                            row_number=row.row_number,
                            import_sku=row.import_sku,
                            product_code=product.product_code,
                        )
                    )
                    continue

                product.updated_at = timestamp
                session.flush()
                outcome.updated_rows.append(
                    UpdatedImageBulkLinkRow(
                        row_number=row.row_number,
                        import_sku=row.import_sku,
                        product_code=product.product_code,
                    )
                )
                if _requires_catalog_sync(session, product_id=product.id):
                    outcome.catalog_sync_product_codes.add(product.product_code)
        except ApiError as exc:
            outcome.failed_rows.append(_api_error_to_failed_row(row, exc))
        except IntegrityError:
            outcome.failed_rows.append(
                FailedImageBulkLinkRow(
                    row_number=row.row_number,
                    import_sku=row.import_sku,
                    field="storage_key",
                    error_code="PRODUCT_IMAGE_STORAGE_KEY_CONFLICT",
                    message="이미 같은 storage_key를 사용하는 이미지가 있습니다.",
                )
            )

    return outcome


def _set_image_slot(
    session: Session,
    *,
    product: Product,
    row: VerifiedImageBulkLinkRow,
) -> bool:
    if row.image_type != DETAIL_IMAGE_TYPE:
        return set_product_thumbnail(session, product, row.storage_key)

    image = session.execute(
        select(ProductImage)
        .where(
            ProductImage.product_id == product.id,
            ProductImage.image_type == row.image_type,
            ProductImage.display_order == row.display_order,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if image is not None and image.storage_key == row.storage_key:
        return False

    if image is None:
        session.add(
            ProductImage(
                product_id=product.id,
                image_type=row.image_type,
                display_order=row.display_order,
                storage_key=row.storage_key,
            )
        )
    else:
        image.storage_key = row.storage_key
    session.flush()
    return True


def _requires_catalog_sync(session: Session, *, product_id: int) -> bool:
    sales_status = session.execute(
        select(Inventory.sales_status).where(Inventory.product_id == product_id)
    ).scalar_one_or_none()
    return sales_status != "HIDDEN"


def _api_error_to_failed_row(
    row: VerifiedImageBulkLinkRow,
    error: ApiError,
) -> FailedImageBulkLinkRow:
    field = "storage_key" if error.code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT" else "import_sku"
    return FailedImageBulkLinkRow(
        row_number=row.row_number,
        import_sku=row.import_sku,
        field=field,
        error_code=error.code,
        message=error.message,
    )
