"""M3-B 엑셀 대량등록의 상품 단위 저장 서비스.

검증을 통과한 행만 저장한다. 서비스는 행별 savepoint와 flush까지만 담당하며,
전체 commit 및 검수 그룹 refresh는 API 라우트가 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.schemas.admin.bulk_import import (
    AdminBulkImportIngredientSummary,
    AdminBulkImportResponse,
    AdminBulkImportRowResult,
    AdminBulkImportSummary,
)
from app.schemas.common import ApiError
from app.services.admin.bulk_import_validation_service import (
    BulkImportValidationOutcome,
    FailedBulkImportRow,
    VerifiedBulkImportRow,
)
from app.services.admin.product_mutation_service import (
    _build_product_url,
    _insert_product_with_code_retry,
    _load_first_party_seller,
)
from app.services.ingredient_resolution_service import ResolutionInput, resolve_many


PENDING_INGREDIENT_PREFIXES = ("ing_pending_", "foreign_pending_")


@dataclass(frozen=True)
class CreatedBulkImportRow:
    row_number: int
    import_sku: str
    product_code: str
    ingredient_counters: dict[str, int]


@dataclass(frozen=True)
class SkippedBulkImportRow:
    row_number: int
    import_sku: str
    existing_product_code: str


@dataclass
class BulkImportStorageOutcome:
    created_rows: list[CreatedBulkImportRow] = field(default_factory=list)
    skipped_rows: list[SkippedBulkImportRow] = field(default_factory=list)
    failed_rows: list[FailedBulkImportRow] = field(default_factory=list)
    requires_review_refresh: bool = False

    def to_response(
        self,
        *,
        review_refresh: str,
        refresh_recovery_command: str | None = None,
    ) -> AdminBulkImportResponse:
        rows: list[AdminBulkImportRowResult] = [
            AdminBulkImportRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="CREATED",
                product_code=row.product_code,
                ingredient_summary=AdminBulkImportIngredientSummary(**row.ingredient_counters),
            )
            for row in self.created_rows
        ]
        rows.extend(
            AdminBulkImportRowResult(
                row_number=row.row_number,
                import_sku=row.import_sku,
                status="SKIPPED",
                existing_product_code=row.existing_product_code,
            )
            for row in self.skipped_rows
        )
        rows.extend(
            AdminBulkImportRowResult(
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
        return AdminBulkImportResponse(
            summary=AdminBulkImportSummary(
                total=len(rows),
                created=len(self.created_rows),
                skipped=len(self.skipped_rows),
                failed=len(self.failed_rows),
            ),
            rows=rows,
            review_refresh=review_refresh,
            refresh_recovery_command=refresh_recovery_command,
        )


def run_bulk_import(
    session: Session,
    validation: BulkImportValidationOutcome,
    *,
    now: datetime | None = None,
) -> BulkImportStorageOutcome:
    """검증 완료 행을 상품 단위 savepoint로 저장한다.

    기존 import_sku는 수정하지 않고 SKIPPED로 반환한다. 성분 해소·pending 생성과
    ProductIngredient 저장은 같은 savepoint에 있으므로, 해당 행이 실패하면 함께 롤백된다.
    """
    timestamp = now or datetime.now(timezone.utc)
    seller = _load_first_party_seller(session)
    outcome = BulkImportStorageOutcome(failed_rows=list(validation.failed_rows))
    brands = _load_active_brands(session, validation.verified_rows)
    categories = _load_active_categories(session, validation.verified_rows)

    for row in validation.verified_rows:
        brand = brands.get(row.brand_id)
        if brand is None:
            outcome.failed_rows.append(
                _master_changed_to_failed_row(row, field="brand_name", code="BRAND_INACTIVE")
            )
            continue
        category = categories.get(row.category_id)
        if category is None:
            outcome.failed_rows.append(
                _master_changed_to_failed_row(row, field="category_name", code="CATEGORY_INACTIVE")
            )
            continue
        try:
            with session.begin_nested():
                product, existing_product_code = _create_or_skip_product(
                    session,
                    seller=seller,
                    brand=brand,
                    category=category,
                    row=row,
                    timestamp=timestamp,
                )
                if product is None:
                    outcome.skipped_rows.append(
                        SkippedBulkImportRow(
                            row_number=row.row_number,
                            import_sku=row.import_sku,
                            existing_product_code=existing_product_code,
                        )
                    )
                    continue

                resolution = resolve_many(
                    session,
                    [ResolutionInput(raw_name=token) for token in row.ingredient_tokens],
                )
                session.add_all(
                    ProductIngredient(
                        product_id=product.id,
                        ingredient_id=result.ingredient_id,
                        ingredient_name=result.raw_name,
                        content_confidence=result.content_confidence,
                        display_order=result.display_order,
                    )
                    for result in resolution.results
                )
                session.flush()

                outcome.created_rows.append(
                    CreatedBulkImportRow(
                        row_number=row.row_number,
                        import_sku=row.import_sku,
                        product_code=product.product_code,
                        ingredient_counters=dict(resolution.counters),
                    )
                )
                if any(
                    result.ingredient_code.startswith(PENDING_INGREDIENT_PREFIXES)
                    for result in resolution.results
                ):
                    outcome.requires_review_refresh = True
        except ApiError as exc:
            outcome.failed_rows.append(_api_error_to_failed_row(row, exc))

    return outcome


def _create_or_skip_product(
    session: Session,
    *,
    seller: Seller,
    brand: Brand,
    category: ProductCategory,
    row: VerifiedBulkImportRow,
    timestamp: datetime,
) -> tuple[Product | None, str]:
    try:
        product = _insert_product_with_code_retry(
            session,
            seller=seller,
            brand=brand,
            category=category,
            name=row.product_name,
            description=None,
            released_at=None,
            timestamp=timestamp,
            import_sku=row.import_sku,
        )
    except IntegrityError:
        existing = session.execute(
            select(Product).where(Product.import_sku == row.import_sku)
        ).scalar_one_or_none()
        if existing is None:
            raise
        return None, existing.product_code

    session.add_all(
        [
            Inventory(
                product_id=product.id,
                stock_quantity=row.stock_quantity,
                reserved_quantity=0,
                safety_stock=0,
                sales_status="HIDDEN",
                inventory_source="ADMIN_BULK_IMPORT",
                updated_at=timestamp,
            ),
            ProductPrice(
                product_id=product.id,
                mall_name=seller.display_name,
                price=row.price,
                currency="KRW",
                product_url=_build_product_url(product.product_code),
                is_lowest=True,
                collected_at=timestamp,
            ),
        ]
    )
    session.flush()
    return product, product.product_code


def _load_active_brands(
    session: Session,
    rows: list[VerifiedBulkImportRow],
) -> dict[int, Brand]:
    ids = {row.brand_id for row in rows}
    if not ids:
        return {}
    rows = session.execute(
        select(Brand).where(Brand.id.in_(ids), Brand.is_active.is_(True))
    ).scalars().all()
    return {int(row.id): row for row in rows}


def _load_active_categories(
    session: Session,
    rows: list[VerifiedBulkImportRow],
) -> dict[int, ProductCategory]:
    ids = {row.category_id for row in rows}
    if not ids:
        return {}
    rows = session.execute(
        select(ProductCategory).where(
            ProductCategory.id.in_(ids), ProductCategory.is_active.is_(True)
        )
    ).scalars().all()
    return {int(row.id): row for row in rows}


def _api_error_to_failed_row(
    row: VerifiedBulkImportRow,
    error: ApiError,
) -> FailedBulkImportRow:
    field = "ingredients_raw" if error.code.startswith("INGREDIENT_") else "product"
    return FailedBulkImportRow(
        row_number=row.row_number,
        import_sku=row.import_sku,
        field=field,
        error_code=error.code,
        message=error.message,
    )


def _master_changed_to_failed_row(
    row: VerifiedBulkImportRow,
    *,
    field: str,
    code: str,
) -> FailedBulkImportRow:
    return FailedBulkImportRow(
        row_number=row.row_number,
        import_sku=row.import_sku,
        field=field,
        error_code=code,
        message="검증 후 마스터 상태가 변경되어 저장할 수 없습니다.",
    )
