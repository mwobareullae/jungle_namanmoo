"""M3-C Chunk 3 이미지 대량 연결 저장·라우트 focused 테스트."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import products as products_route
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage
from app.db.models.commerce import Inventory, Seller
from app.db.session import get_db
from app.main import app
from app.schemas.admin.image_bulk_link import AdminImageBulkLinkRequest, AdminImageBulkLinkRowRequest
from app.services.admin.image_bulk_link_service import run_image_bulk_link
from app.services.admin.image_bulk_link_validation_service import (
    ImageBulkLinkValidationOutcome,
    VerifiedImageBulkLinkRow,
    validate_image_bulk_link,
)


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


@pytest.fixture()
def client(db_engine: Engine) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed(session: Session) -> None:
    seller = Seller(seller_code="mwobareullae", display_name="뭐바를래")
    brand = Brand(brand_code="brand", name="브랜드", normalized_name="brand")
    category = ProductCategory(category_code="skin", name="스킨")
    session.add_all([seller, brand, category])
    session.flush()

    for code, sku, sales_status in [
        ("prod_image_on_sale", "IMPORT_IMAGE_001", "ON_SALE"),
        ("prod_image_hidden", "IMPORT_IMAGE_002", "HIDDEN"),
    ]:
        product = Product(
            product_code=code,
            import_sku=sku,
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name=code,
            thumbnail_url=f"products/{sku}/thumbnail-old.jpg",
            updated_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        )
        session.add(product)
        session.flush()
        session.add_all(
            [
                Inventory(
                    product_id=product.id,
                    stock_quantity=10,
                    reserved_quantity=0,
                    safety_stock=0,
                    sales_status=sales_status,
                ),
                ProductImage(
                    product_id=product.id,
                    image_type="thumbnail",
                    display_order=0,
                    storage_key=f"products/{sku}/thumbnail-old.jpg",
                ),
                ProductImage(
                    product_id=product.id,
                    image_type="detail",
                    display_order=1,
                    storage_key=f"products/{sku}/detail-01.jpg",
                ),
            ]
        )
    session.flush()


def _row(**overrides: object) -> AdminImageBulkLinkRowRequest:
    values: dict[str, object] = {
        "import_sku": "IMPORT_IMAGE_001",
        "image_type": "thumbnail",
        "display_order": 0,
        "storage_key": "products/IMPORT_IMAGE_001/thumbnail-new.jpg",
    }
    values.update(overrides)
    return AdminImageBulkLinkRowRequest(**values)


def _request(*rows: AdminImageBulkLinkRowRequest) -> AdminImageBulkLinkRequest:
    return AdminImageBulkLinkRequest(rows=list(rows))


def _as_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "admin-image-link@example.com",
            "password": "password123",
            "nickname": "admin-image-link",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.scalar(select(User).where(User.email == "admin-image-link@example.com"))
        assert user is not None
        user.role = "ADMIN"
        session.commit()


def test_storage_updates_only_requested_slots_and_tracks_non_hidden_product_for_sync(session: Session) -> None:
    validation = validate_image_bulk_link(
        session,
        _request(
            _row(),
            _row(
                image_type="detail",
                display_order=2,
                storage_key="products/IMPORT_IMAGE_001/detail-02.jpg",
            ),
            _row(
                import_sku="IMPORT_IMAGE_002",
                storage_key="products/IMPORT_IMAGE_002/thumbnail-new.jpg",
            ),
        ),
    )

    outcome = run_image_bulk_link(session, validation, now=datetime(2026, 7, 19, 9, 0, tzinfo=UTC))

    assert outcome.to_response().summary.model_dump() == {
        "total": 3,
        "updated": 3,
        "skipped": 0,
        "failed": 0,
    }
    assert outcome.catalog_sync_product_codes == {"prod_image_on_sale"}
    on_sale = session.scalar(select(Product).where(Product.product_code == "prod_image_on_sale"))
    assert on_sale is not None
    assert on_sale.thumbnail_url == "products/IMPORT_IMAGE_001/thumbnail-new.jpg"
    images = session.execute(
        select(ProductImage)
        .where(ProductImage.product_id == on_sale.id)
        .order_by(ProductImage.image_type, ProductImage.display_order)
    ).scalars().all()
    assert [(image.image_type, image.display_order, image.storage_key) for image in images] == [
        ("detail", 1, "products/IMPORT_IMAGE_001/detail-01.jpg"),
        ("detail", 2, "products/IMPORT_IMAGE_001/detail-02.jpg"),
        ("thumbnail", 0, "products/IMPORT_IMAGE_001/thumbnail-new.jpg"),
    ]


def test_storage_returns_skipped_for_same_key_without_touching_updated_at(session: Session) -> None:
    product = session.scalar(select(Product).where(Product.product_code == "prod_image_on_sale"))
    assert product is not None
    original_updated_at = product.updated_at
    validation = validate_image_bulk_link(
        session,
        _request(_row(storage_key="products/IMPORT_IMAGE_001/thumbnail-old.jpg")),
    )

    outcome = run_image_bulk_link(session, validation, now=datetime(2026, 7, 19, 10, 0, tzinfo=UTC))

    assert outcome.to_response().summary.model_dump() == {
        "total": 1,
        "updated": 0,
        "skipped": 1,
        "failed": 0,
    }
    assert product.updated_at == original_updated_at
    assert not outcome.catalog_sync_product_codes


def test_storage_rolls_back_only_conflicting_row(session: Session) -> None:
    product = session.scalar(select(Product).where(Product.product_code == "prod_image_on_sale"))
    assert product is not None
    outcome = run_image_bulk_link(
        session,
        ImageBulkLinkValidationOutcome(
            verified_rows=[
                VerifiedImageBulkLinkRow(
                    row_number=1,
                    import_sku="IMPORT_IMAGE_001",
                    product_id=product.id,
                    product_code=product.product_code,
                    image_type="detail",
                    display_order=2,
                    storage_key="products/IMPORT_IMAGE_001/detail-02.jpg",
                    existing_storage_key=None,
                ),
                VerifiedImageBulkLinkRow(
                    row_number=2,
                    import_sku="IMPORT_IMAGE_001",
                    product_id=product.id,
                    product_code=product.product_code,
                    image_type="detail",
                    display_order=3,
                    storage_key="products/IMPORT_IMAGE_001/detail-01.jpg",
                    existing_storage_key=None,
                ),
            ],
            failed_rows=[],
        ),
    )

    response = outcome.to_response()
    assert [(row.row_number, row.status) for row in response.rows] == [(1, "UPDATED"), (2, "FAILED")]
    assert response.rows[1].error_code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT"
    assert session.scalar(
        select(ProductImage.storage_key).where(
            ProductImage.product_id == product.id,
            ProductImage.image_type == "detail",
            ProductImage.display_order == 2,
        )
    ) == "products/IMPORT_IMAGE_001/detail-02.jpg"


def test_route_commits_and_syncs_only_changed_non_hidden_products(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[str] = []
    monkeypatch.setattr(
        products_route,
        "sync_catalog_product_after_commit",
        lambda _session, product_code, **_kwargs: synced.append(product_code),
    )

    response = products_route.bulk_link_product_images(
        _request(
            _row(),
            _row(
                import_sku="IMPORT_IMAGE_002",
                storage_key="products/IMPORT_IMAGE_002/thumbnail-new.jpg",
            ),
        ),
        session,
    )

    assert response.summary.model_dump() == {"total": 2, "updated": 2, "skipped": 0, "failed": 0}
    assert synced == ["prod_image_on_sale"]


def test_request_rejects_more_than_one_thousand_rows() -> None:
    with pytest.raises(ValidationError):
        AdminImageBulkLinkRequest(rows=[_row() for _ in range(1001)])


def test_endpoint_returns_partial_success_response(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(db_engine) as session:
        _seed(session)
        session.commit()
    _as_admin(client, db_engine)
    monkeypatch.setattr(products_route, "sync_catalog_product_after_commit", lambda *_args, **_kwargs: None)

    response = client.post(
        "/api/admin/products/images/bulk",
        json={
            "rows": [
                _row().model_dump(),
                _row(import_sku="IMPORT_IMAGE_404").model_dump(),
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"total": 2, "updated": 1, "skipped": 0, "failed": 1}
    assert [(row["row_number"], row["status"]) for row in payload["rows"]] == [
        (1, "UPDATED"),
        (2, "FAILED"),
    ]
