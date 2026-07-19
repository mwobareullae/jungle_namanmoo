"""대표 ProductImage와 Product.thumbnail_url 동기화 테스트."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage
from app.db.models.commerce import Seller
from app.schemas.common import ApiError
from app.services.product_thumbnail import set_product_thumbnail


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
        seller = Seller(seller_code="mwobareullae", display_name="MwoBareullae")
        brand = Brand(brand_code="brand", name="Brand", normalized_name="brand")
        category = ProductCategory(category_code="skin", name="Skin")
        sess.add_all([seller, brand, category])
        sess.flush()
        product = Product(
            product_code="prod_mwbl_thumbnail",
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name="Thumbnail Product",
        )
        sess.add(product)
        sess.flush()
        yield sess


def _product(session: Session) -> Product:
    return session.execute(
        select(Product).where(Product.product_code == "prod_mwbl_thumbnail")
    ).scalar_one()


def test_set_product_thumbnail_creates_replaces_clears_and_noops(session: Session) -> None:
    product = _product(session)

    assert set_product_thumbnail(session, product, "products/thumbnail_1.jpg")
    first = session.execute(
        select(ProductImage).where(ProductImage.product_id == product.id)
    ).scalar_one()
    assert (first.image_type, first.display_order, first.storage_key) == (
        "thumbnail",
        0,
        "products/thumbnail_1.jpg",
    )
    assert product.thumbnail_url == "products/thumbnail_1.jpg"

    assert not set_product_thumbnail(session, product, "products/thumbnail_1.jpg")
    assert set_product_thumbnail(session, product, "products/thumbnail_2.jpg")
    assert first.storage_key == "products/thumbnail_2.jpg"
    assert product.thumbnail_url == "products/thumbnail_2.jpg"

    assert set_product_thumbnail(session, product, None)
    assert product.thumbnail_url is None
    assert session.execute(
        select(ProductImage).where(ProductImage.product_id == product.id)
    ).scalars().all() == []
    assert not set_product_thumbnail(session, product, None)


def test_set_product_thumbnail_rejects_key_already_used_by_detail(session: Session) -> None:
    product = _product(session)
    session.add(
        ProductImage(
            product_id=product.id,
            image_type="detail",
            display_order=1,
            storage_key="products/detail_1.jpg",
        )
    )
    session.flush()

    with pytest.raises(ApiError) as exc_info:
        set_product_thumbnail(session, product, "products/detail_1.jpg")

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT"
