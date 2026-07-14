"""P1-M3-A Chunk 4 관리자 상품 등록·수정 focused 테스트."""

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.db.session import get_db
from app.main import app
from app.schemas.admin.product import AdminProductCreateRequest, AdminProductUpdateRequest
from app.schemas.common import ApiError
from app.services.admin import product_mutation_service
from app.services.admin.product_mutation_service import create_admin_product, update_admin_product


ADMIN_EMAIL = "admin-product-mutation@example.com"
FIXED_NOW = datetime(2026, 7, 15, 3, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


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
    brand_a = Brand(brand_code="brand_a", name="브랜드에이", normalized_name="branda")
    brand_b = Brand(brand_code="brand_b", name="브랜드비", normalized_name="brandb")
    inactive_brand = Brand(
        brand_code="brand_inactive",
        name="비활성브랜드",
        normalized_name="inactivebrand",
        is_active=False,
    )
    category_a = ProductCategory(category_code="cat_a", name="세럼")
    category_b = ProductCategory(category_code="cat_b", name="크림")
    inactive_category = ProductCategory(category_code="cat_inactive", name="비활성", is_active=False)
    session.add_all([seller, brand_a, brand_b, inactive_brand, category_a, category_b, inactive_category])
    session.flush()

    editable = Product(
        product_code="prod_mwbl_editable",
        seller_id=seller.id,
        brand_id=brand_a.id,
        category_id=category_a.id,
        product_name="수정 전 상품",
        is_active=True,
        is_recommendable=False,
    )
    hidden = Product(
        product_code="prod_mwbl_hidden",
        seller_id=seller.id,
        brand_id=brand_a.id,
        category_id=category_a.id,
        product_name="준비 중 상품",
        is_active=False,
        is_recommendable=False,
    )
    collision = Product(
        product_code="prod_mwbl_collision",
        seller_id=seller.id,
        brand_id=brand_a.id,
        category_id=category_a.id,
        product_name="코드 충돌 상품",
        is_active=False,
        is_recommendable=False,
    )
    session.add_all([editable, hidden, collision])
    session.flush()
    session.add_all(
        [
            Inventory(product_id=editable.id, sales_status="ON_SALE", stock_quantity=10),
            Inventory(product_id=hidden.id, sales_status="HIDDEN", stock_quantity=0),
            Inventory(product_id=collision.id, sales_status="HIDDEN", stock_quantity=0),
            ProductPrice(
                product_id=editable.id,
                mall_name="뭐바를래",
                price=10_000,
                product_url="/products/prod_mwbl_editable",
                is_lowest=True,
            ),
        ]
    )


def _create_request(**overrides: object) -> AdminProductCreateRequest:
    data: dict[str, object] = {
        "name": "관리자 신규 상품",
        "brand_code": "brand_a",
        "category_code": "cat_a",
        "price": 23_900,
        "description": "신규 상품 설명",
    }
    data.update(overrides)
    return AdminProductCreateRequest(**data)


def _authed_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": ADMIN_EMAIL,
            "password": "password123",
            "nickname": "admin-product-mutation",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def test_create_product_builds_default_inventory_and_first_party_price(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = create_admin_product(session, _create_request(), now=FIXED_NOW)
        product = session.execute(select(Product).where(Product.product_code == result.product_code)).scalar_one()
        inventory = session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()
        price = session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()

        assert result.product_code.startswith("prod_mwbl_")
        assert product.is_active is False
        assert product.is_recommendable is False
        assert inventory.sales_status == "HIDDEN"
        assert (inventory.stock_quantity, inventory.reserved_quantity, inventory.safety_stock) == (0, 0, 0)
        assert (price.mall_name, price.price, price.currency, price.is_lowest) == ("뭐바를래", 23_900, "KRW", True)
        assert price.product_url == f"/product-detail?id={product.product_code}"


def test_update_product_changes_only_requested_basic_fields_and_price(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = update_admin_product(
            session,
            "prod_mwbl_editable",
            AdminProductUpdateRequest(
                name="수정된 상품",
                brand_code="brand_b",
                category_code="cat_b",
                price=31_000,
                description="수정 설명",
                is_active=False,
            ),
            now=FIXED_NOW,
        )
        product = session.execute(select(Product).where(Product.product_code == result.product_code)).scalar_one()
        price = session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()

        assert (result.name, result.brand_code, result.category_code, result.price) == (
            "수정된 상품",
            "brand_b",
            "cat_b",
            31_000,
        )
        assert product.is_active is False
        assert price.product_url == "/product-detail?id=prod_mwbl_editable"


def test_activation_requires_non_hidden_inventory_and_keeps_state_on_error(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            update_admin_product(
                session,
                "prod_mwbl_hidden",
                AdminProductUpdateRequest(is_active=True),
                now=FIXED_NOW,
            )
        session.rollback()
        product = session.execute(select(Product).where(Product.product_code == "prod_mwbl_hidden")).scalar_one()

    assert exc.value.status_code == 409
    assert exc.value.code == "PRODUCT_NOT_READY_FOR_ACTIVATION"
    assert product.is_active is False


@pytest.mark.parametrize(
    ("create_body", "expected_code"),
    [
        (_create_request(brand_code="brand_inactive"), "BRAND_INACTIVE"),
        (_create_request(category_code="cat_inactive"), "CATEGORY_INACTIVE"),
        (_create_request(price=0), "INVALID_PRODUCT_FIELD"),
    ],
)
def test_create_rejects_inactive_masters_and_invalid_price(
    db_engine: Engine,
    create_body: AdminProductCreateRequest,
    expected_code: str,
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            create_admin_product(session, create_body, now=FIXED_NOW)
    assert exc.value.code == expected_code


def test_product_code_collision_retries_with_new_candidate(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = iter(["prod_mwbl_collision", "prod_mwbl_after_retry"])
    monkeypatch.setattr(product_mutation_service, "_generate_product_code", lambda: next(candidates))

    with Session(db_engine) as session:
        result = create_admin_product(session, _create_request(), now=FIXED_NOW)
        assert result.product_code == "prod_mwbl_after_retry"


def test_admin_create_route_commits_product_graph(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.post(
        "/api/admin/products",
        json={
            "name": "API 등록 상품",
            "brand_code": "brand_a",
            "category_code": "cat_a",
            "price": 19_900,
        },
    )
    assert response.status_code == 201
    code = response.json()["product_code"]

    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == code)).scalar_one()
        assert session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()
        assert session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()


def test_admin_patch_route_rejects_empty_body(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.patch("/api/admin/products/prod_mwbl_editable", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PRODUCT_FIELD"


def test_admin_patch_route_rejects_missing_product(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.patch("/api/admin/products/prod_missing", json={"name": "없는 상품"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
