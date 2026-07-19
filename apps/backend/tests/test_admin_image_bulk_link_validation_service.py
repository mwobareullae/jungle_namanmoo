"""M3-C Chunk 1 이미지 대량 연결 검증 서비스 테스트."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage
from app.db.models.commerce import Seller
from app.schemas.admin.image_bulk_link import (
    AdminImageBulkLinkRequest,
    AdminImageBulkLinkRowRequest,
)
from app.services.admin import image_bulk_link_validation_service as validation


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
        _seed(sess)
        yield sess


def _seed(session: Session) -> None:
    seller = Seller(seller_code="mwobareullae", display_name="MwoBareullae")
    brand = Brand(brand_code="brand", name="Brand", normalized_name="brand")
    category = ProductCategory(category_code="skin", name="Skin")
    session.add_all([seller, brand, category])
    session.flush()

    product_one = Product(
        product_code="prod_mwbl_images_one",
        import_sku="IMPORT_001",
        seller_id=seller.id,
        brand_id=brand.id,
        category_id=category.id,
        product_name="Image One",
    )
    product_two = Product(
        product_code="prod_mwbl_images_two",
        import_sku="IMPORT_002",
        seller_id=seller.id,
        brand_id=brand.id,
        category_id=category.id,
        product_name="Image Two",
    )
    session.add_all([product_one, product_two])
    session.flush()
    session.add_all(
        [
            ProductImage(
                product_id=product_one.id,
                image_type="thumbnail",
                display_order=0,
                storage_key="products/IMPORT_001/thumbnail-old.jpg",
            ),
            ProductImage(
                product_id=product_one.id,
                image_type="detail",
                display_order=1,
                storage_key="products/IMPORT_001/detail_01.jpg",
            ),
            ProductImage(
                product_id=product_one.id,
                image_type="detail",
                display_order=2,
                storage_key="products/IMPORT_001/detail_02.jpg",
            ),
        ]
    )
    session.flush()


def _request(*rows: AdminImageBulkLinkRowRequest) -> AdminImageBulkLinkRequest:
    return AdminImageBulkLinkRequest(rows=list(rows))


def _row(**overrides: object) -> AdminImageBulkLinkRowRequest:
    values: dict[str, object] = {
        "import_sku": "IMPORT_001",
        "image_type": "thumbnail",
        "display_order": 0,
        "storage_key": "products/IMPORT_001/thumbnail-new.jpg",
    }
    values.update(overrides)
    return AdminImageBulkLinkRowRequest(**values)


def test_validation_resolves_product_and_returns_change_metadata_without_writes(
    session: Session,
) -> None:
    before = session.scalar(select(func.count()).select_from(ProductImage))

    outcome = validation.validate_image_bulk_link(session, _request(_row()))

    assert not outcome.failed_rows
    assert len(outcome.verified_rows) == 1
    verified = outcome.verified_rows[0]
    assert verified.product_code == "prod_mwbl_images_one"
    assert verified.existing_storage_key == "products/IMPORT_001/thumbnail-old.jpg"
    assert not verified.is_noop
    assert session.scalar(select(func.count()).select_from(ProductImage)) == before


def test_validation_marks_same_slot_same_key_as_noop(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(_row(storage_key="products/IMPORT_001/thumbnail-old.jpg")),
    )

    assert not outcome.failed_rows
    assert outcome.verified_rows[0].is_noop


@pytest.mark.parametrize(
    ("row", "field"),
    [
        (_row(import_sku="import_lowercase"), "import_sku"),
        (_row(image_type="Thumbnail"), "image_type"),
        (_row(display_order=1), "display_order"),
        (_row(image_type="detail", display_order=0), "display_order"),
        (_row(storage_key="   "), "storage_key"),
        (_row(storage_key="https://cdn.example.com/image.jpg"), "storage_key"),
        (_row(storage_key="products/../thumbnail.jpg"), "storage_key"),
    ],
)
def test_validation_rejects_invalid_row_shapes(
    session: Session, row: AdminImageBulkLinkRowRequest, field: str
) -> None:
    outcome = validation.validate_image_bulk_link(session, _request(row))

    assert not outcome.verified_rows
    assert outcome.failed_rows[0].field == field
    assert outcome.failed_rows[0].error_code == "INVALID_IMAGE_INPUT"


def test_validation_marks_unknown_import_sku_as_failed(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(session, _request(_row(import_sku="IMPORT_404")))

    assert not outcome.verified_rows
    assert outcome.failed_rows[0].error_code == "IMPORT_SKU_NOT_FOUND"


def test_validation_marks_second_duplicate_slot_in_request_as_failed(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(_row(), _row(storage_key="products/IMPORT_001/thumbnail-next.jpg")),
    )

    assert [row.row_number for row in outcome.verified_rows] == [1]
    assert outcome.failed_rows[0].row_number == 2
    assert outcome.failed_rows[0].error_code == "DUPLICATE_IMAGE_SLOT_IN_REQUEST"


def test_validation_rejects_storage_key_owned_by_another_existing_slot(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(
            _row(
                image_type="detail",
                display_order=3,
                storage_key="products/IMPORT_001/detail_01.jpg",
            )
        ),
    )

    assert not outcome.verified_rows
    assert outcome.failed_rows[0].error_code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT"


def test_validation_rejects_storage_key_swap_without_inferring_intent(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(
            _row(
                image_type="detail",
                display_order=1,
                storage_key="products/IMPORT_001/detail_02.jpg",
            ),
            _row(
                image_type="detail",
                display_order=2,
                storage_key="products/IMPORT_001/detail_01.jpg",
            ),
        ),
    )

    assert not outcome.verified_rows
    assert [row.error_code for row in outcome.failed_rows] == [
        "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT",
        "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT",
    ]


def test_validation_rejects_same_requested_key_for_two_different_slots(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(
            _row(
                image_type="detail",
                display_order=3,
                storage_key="products/IMPORT_001/detail_new.jpg",
            ),
            _row(
                image_type="detail",
                display_order=4,
                storage_key="products/IMPORT_001/detail_new.jpg",
            ),
        ),
    )

    assert [row.row_number for row in outcome.verified_rows] == [1]
    assert outcome.failed_rows[0].error_code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT"


def test_validation_returns_response_rows_in_input_order(session: Session) -> None:
    outcome = validation.validate_image_bulk_link(
        session,
        _request(
            _row(import_sku="IMPORT_404"),
            _row(image_type="detail", display_order=3, storage_key="products/IMPORT_001/detail_03.jpg"),
        ),
    )

    response = outcome.to_response()
    assert response.summary.model_dump() == {"total": 2, "valid": 1, "failed": 1}
    assert [(row.row_number, row.status) for row in response.rows] == [
        (1, "FAILED"),
        (2, "VALID"),
    ]
