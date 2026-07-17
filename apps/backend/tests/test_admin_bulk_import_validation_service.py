"""M3-B Chunk 2: 엑셀 행별 검증과 브랜드·카테고리 해소 테스트."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import (
    Brand,
    BrandAlias,
    ProductCategory,
    ProductCategoryAlias,
)
from app.schemas.admin.bulk_import import (
    AdminBulkImportRequest,
    AdminBulkImportRowRequest,
)
from app.schemas.common import ApiError
from app.services.admin import brand_category_resolution_service as resolution
from app.services.admin import bulk_import_validation_service as validation
from app.services.ingredient_resolution_service import normalize_for_resolution


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def session(db_engine: Engine) -> Generator[Session, None, None]:
    with Session(db_engine) as sess:
        yield sess


def _brand(session: Session, code: str, name: str, *, active: bool = True) -> Brand:
    row = Brand(
        brand_code=code,
        name=name,
        normalized_name=normalize_for_resolution(name),
        is_active=active,
    )
    session.add(row)
    session.flush()
    return row


def _category(
    session: Session, code: str, name: str, *, active: bool = True
) -> ProductCategory:
    row = ProductCategory(category_code=code, name=name, is_active=active)
    session.add(row)
    session.flush()
    return row


def _request(*rows: AdminBulkImportRowRequest) -> AdminBulkImportRequest:
    return AdminBulkImportRequest(rows=list(rows))


def _row(**overrides: object) -> AdminBulkImportRowRequest:
    values: dict[str, object] = {
        "import_sku": "IMPORT_001",
        "product_name": "수분 세럼",
        "brand_name": "테스트 브랜드",
        "category_name": "스킨케어",
        "price": 12000,
        "stock_quantity": 10,
        "ingredients_raw": "정제수|글리세린",
    }
    values.update(overrides)
    return AdminBulkImportRowRequest(**values)


def test_brand_and_category_resolution_distinguishes_all_outcomes(session: Session) -> None:
    active_brand = _brand(session, "brand_active", "테스트 브랜드")
    active_category = _category(session, "skin", "스킨케어")
    session.add_all(
        [
            BrandAlias(
                brand_id=active_brand.id,
                alias="테스트브랜드별칭",
                normalized_alias=normalize_for_resolution("테스트브랜드별칭"),
            ),
            ProductCategoryAlias(
                category_id=active_category.id,
                alias="스킨",
                normalized_alias=normalize_for_resolution("스킨"),
            ),
        ]
    )
    inactive_brand = _brand(session, "brand_inactive", "중지 브랜드", active=False)
    inactive_category = _category(session, "body", "중지 카테고리", active=False)
    brand_one = _brand(session, "brand_one", "첫 브랜드")
    brand_two = _brand(session, "brand_two", "둘 브랜드")
    category_one = _category(session, "category_one", "첫 카테고리")
    category_two = _category(session, "category_two", "둘 카테고리")
    session.add_all(
        [
            BrandAlias(
                brand_id=brand_one.id,
                alias="공통 별칭",
                normalized_alias=normalize_for_resolution("공통 별칭"),
            ),
            BrandAlias(
                brand_id=brand_two.id,
                alias="공통 별칭",
                normalized_alias=normalize_for_resolution("공통 별칭"),
            ),
            ProductCategoryAlias(
                category_id=category_one.id,
                alias="공통 분류",
                normalized_alias=normalize_for_resolution("공통 분류"),
            ),
            ProductCategoryAlias(
                category_id=category_two.id,
                alias="공통 분류",
                normalized_alias=normalize_for_resolution("공통 분류"),
            ),
        ]
    )
    session.flush()

    assert resolution.resolve_brand(session, "테스트 브랜드") == resolution.BrandResolution(
        resolution.FOUND, active_brand.id
    )
    assert resolution.resolve_brand(session, "테스트브랜드별칭") == resolution.BrandResolution(
        resolution.FOUND, active_brand.id
    )
    assert resolution.resolve_brand(session, "없는 브랜드").status == resolution.NOT_FOUND
    assert resolution.resolve_brand(session, "공통 별칭").status == resolution.AMBIGUOUS
    assert resolution.resolve_brand(session, "중지 브랜드") == resolution.BrandResolution(
        resolution.INACTIVE, inactive_brand.id
    )

    assert resolution.resolve_category(session, "스킨") == resolution.CategoryResolution(
        resolution.FOUND, active_category.id
    )
    assert resolution.resolve_category(session, "없는 분류").status == resolution.NOT_FOUND
    assert resolution.resolve_category(session, "공통 분류").status == resolution.AMBIGUOUS
    assert resolution.resolve_category(session, "중지 카테고리") == resolution.CategoryResolution(
        resolution.INACTIVE, inactive_category.id
    )


def test_validation_returns_valid_and_failed_rows_without_rejecting_request(
    session: Session,
) -> None:
    brand = _brand(session, "brand_valid", "테스트 브랜드")
    category = _category(session, "skin", "스킨케어")

    outcome = validation.validate_bulk_import(
        session,
        _request(
            _row(),
            _row(import_sku="import_lowercase", product_name="잘못된 SKU 상품"),
        ),
    )
    response = outcome.to_response()

    assert response.summary.model_dump() == {"total": 2, "valid": 1, "failed": 1}
    assert [row.status for row in response.rows] == ["VALID", "FAILED"]
    assert response.rows[1].error_code == "INVALID_INPUT"
    assert outcome.verified_rows[0].brand_id == brand.id
    assert outcome.verified_rows[0].category_id == category.id


@pytest.mark.parametrize(
    ("ingredients_raw", "expected_message"),
    [
        ("정제수||글리세린", "빈 토큰"),
        ("정제수|나이아신아마이드 2%", "`%` 문자"),
        ("   ", "비어 있을 수"),
    ],
)
def test_validation_rejects_unsupported_or_empty_ingredients(
    session: Session, ingredients_raw: str, expected_message: str
) -> None:
    _brand(session, "brand_valid", "테스트 브랜드")
    _category(session, "skin", "스킨케어")

    outcome = validation.validate_bulk_import(session, _request(_row(ingredients_raw=ingredients_raw)))

    assert not outcome.verified_rows
    assert outcome.failed_rows[0].error_code == "INVALID_INGREDIENT_INPUT"
    assert expected_message in outcome.failed_rows[0].message


def test_validation_marks_second_duplicate_import_sku_as_failed(session: Session) -> None:
    _brand(session, "brand_valid", "테스트 브랜드")
    _category(session, "skin", "스킨케어")

    outcome = validation.validate_bulk_import(
        session,
        _request(_row(), _row(product_name="두 번째 상품")),
    )

    assert [row.row_number for row in outcome.verified_rows] == [1]
    assert outcome.failed_rows[0].row_number == 2
    assert outcome.failed_rows[0].error_code == "DUPLICATE_IMPORT_SKU_IN_REQUEST"


def test_validation_reports_master_resolution_errors_per_row(session: Session) -> None:
    _brand(session, "brand_valid", "테스트 브랜드")
    _category(session, "skin", "스킨케어")

    outcome = validation.validate_bulk_import(
        session,
        _request(
            _row(brand_name="없는 브랜드"),
            _row(import_sku="IMPORT_002", category_name="없는 분류"),
        ),
    )

    assert [row.error_code for row in outcome.failed_rows] == [
        "BRAND_NOT_FOUND",
        "CATEGORY_NOT_FOUND",
    ]


def test_validation_rejects_more_than_200_rows_before_row_processing(session: Session) -> None:
    request = _request(*[_row(import_sku=f"IMPORT_{index:03d}") for index in range(201)])

    with pytest.raises(ApiError) as exc_info:
        validation.validate_bulk_import(session, request)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_INPUT"
