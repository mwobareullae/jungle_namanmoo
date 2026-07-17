from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory
from app.db.models.commerce import Seller


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = sa.create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_product_import_sku_schema_matches_bulk_import_contract() -> None:
    column = Product.__table__.c.import_sku
    check_constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in Product.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    indexes = {index.name: index for index in Product.__table__.indexes}

    assert column.nullable is True
    assert isinstance(column.type, sa.String)
    assert column.type.length == 64
    assert check_constraints["ck_products_import_sku_format"] == (
        "import_sku is null or import_sku ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'"
    )

    import_sku_index = indexes["uq_products_import_sku_not_null"]
    assert import_sku_index.unique is True
    assert str(import_sku_index.dialect_options["postgresql"]["where"]) == "import_sku IS NOT NULL"
    assert str(import_sku_index.dialect_options["sqlite"]["where"]) == "import_sku IS NOT NULL"


def test_product_import_sku_allows_legacy_nulls_but_blocks_duplicate_values(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        seller, brand, category = _seed_references(session)
        session.add_all(
            [
                _product("prod_legacy_1", seller.id, brand.id, category.id),
                _product("prod_legacy_2", seller.id, brand.id, category.id),
                _product("prod_imported_1", seller.id, brand.id, category.id, import_sku="IMPORT_SERUM_001"),
            ]
        )
        session.commit()

        session.add(_product("prod_imported_2", seller.id, brand.id, category.id, import_sku="IMPORT_SERUM_001"))
        with pytest.raises(IntegrityError):
            session.flush()


def _seed_references(session: Session) -> tuple[Seller, Brand, ProductCategory]:
    seller = Seller(seller_code="first_party", display_name="First Party")
    brand = Brand(brand_code="brand_import", name="Import Brand", normalized_name="importbrand")
    category = ProductCategory(category_code="category_import", name="Import Category")
    session.add_all([seller, brand, category])
    session.flush()
    return seller, brand, category


def _product(
    product_code: str,
    seller_id: int,
    brand_id: int,
    category_id: int,
    *,
    import_sku: str | None = None,
) -> Product:
    return Product(
        product_code=product_code,
        import_sku=import_sku,
        seller_id=seller_id,
        brand_id=brand_id,
        category_id=category_id,
        product_name=product_code,
    )
