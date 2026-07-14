"""P1-M3-A 관리자 상품 조회 서비스·라우트 focused 테스트.

계약 고정 포인트만 최소로 검증한다(전수 아님):
  - 관리자 목록은 고객 목록과 달리 비활성·HIDDEN 상품도 포함한다(핵심 차이).
  - 재고 행이 없는 상품은 가용성 UNKNOWN, UNKNOWN 필터로 조회된다.
  - 대표 이미지는 products.thumbnail_url 이 아니라 product_images.storage_key.
  - 이름/브랜드/노출 필터, 상세 404, 라우트 401/403/200, 잘못된 sales_status 400.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.db.session import get_db
from app.main import app
from app.schemas.common import ApiError
from app.services.admin.product_service import get_admin_product_detail, list_admin_products


ADMIN_EMAIL = "admin-product@example.com"


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
    cat_serum = ProductCategory(category_code="cat_serum", name="세럼")
    cat_cream = ProductCategory(category_code="cat_cream", name="크림")
    session.add_all([seller, brand_a, brand_b, cat_serum, cat_cream])
    session.flush()

    def _product(code: str, name: str, brand: Brand, category: ProductCategory, *, is_active: bool = True) -> Product:
        product = Product(
            product_code=code,
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name=name,
            is_active=is_active,
            is_recommendable=False,
        )
        session.add(product)
        session.flush()
        return product

    # p1: 활성·ON_SALE·재고 40·대표 이미지 있음
    p1 = _product("prod_mwbl_active", "히알루론산 세럼", brand_a, cat_serum)
    session.add(Inventory(product_id=p1.id, sales_status="ON_SALE", stock_quantity=40))
    session.add(ProductPrice(product_id=p1.id, mall_name="뭐바를래", price=19900, product_url="/products/prod_mwbl_active", is_lowest=True))
    session.add(ProductImage(product_id=p1.id, image_type="thumbnail", storage_key="products/prod_mwbl_active/thumb_0", display_order=0))
    session.add(ProductImage(product_id=p1.id, image_type="detail", storage_key="products/prod_mwbl_active/detail_1", display_order=1))

    # p2: 비활성(관리자 목록엔 보여야 함)
    p2 = _product("prod_mwbl_inactive", "비활성 크림", brand_a, cat_serum, is_active=False)
    session.add(Inventory(product_id=p2.id, sales_status="ON_SALE", stock_quantity=10))

    # p3: 활성이지만 재고 HIDDEN
    p3 = _product("prod_mwbl_hidden", "숨김 크림", brand_b, cat_cream)
    session.add(Inventory(product_id=p3.id, sales_status="HIDDEN", stock_quantity=5))

    # p4: 활성이지만 재고 행 자체가 없음 → UNKNOWN
    _product("prod_mwbl_noinv", "재고미상 크림", brand_b, cat_cream)


def _authed_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": ADMIN_EMAIL,
            "password": "password123",
            "nickname": "admin-product",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


# --- 서비스 계층 ---


def test_admin_list_includes_inactive_and_hidden(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = list_admin_products(session, page=1, page_size=50)
    codes = {item.product_code for item in result.items}
    assert result.pagination.total_items == 4
    assert {"prod_mwbl_active", "prod_mwbl_inactive", "prod_mwbl_hidden", "prod_mwbl_noinv"} <= codes


def test_no_inventory_product_is_unknown(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        detail = get_admin_product_detail(session, "prod_mwbl_noinv")
    assert detail.availability.sales_status == "UNKNOWN"
    assert detail.availability.stock_status == "UNKNOWN"
    assert detail.availability.available_quantity is None
    assert detail.availability.in_stock is False
    assert detail.stock_quantity is None


def test_hidden_inventory_status(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        detail = get_admin_product_detail(session, "prod_mwbl_hidden")
    assert detail.availability.sales_status == "HIDDEN"
    assert detail.availability.stock_status == "HIDDEN"
    assert detail.availability.in_stock is False


def test_unknown_filter_returns_only_no_inventory(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = list_admin_products(session, sales_status="UNKNOWN", page=1, page_size=50)
    assert {item.product_code for item in result.items} == {"prod_mwbl_noinv"}


def test_thumbnail_returns_storage_key(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        detail = get_admin_product_detail(session, "prod_mwbl_active")
    # products.thumbnail_url(=None) 이 아니라 product_images 의 thumbnail storage_key 여야 한다
    assert detail.thumbnail_url == "products/prod_mwbl_active/thumb_0"
    assert detail.image_count == 2
    assert detail.price == 19900
    assert detail.seller_code == "mwobareullae"


def test_filters_name_brand_active(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        by_name = list_admin_products(session, query="세럼", page=1, page_size=50)
        by_brand = list_admin_products(session, brand_code="brand_b", page=1, page_size=50)
        inactive_only = list_admin_products(session, is_active=False, page=1, page_size=50)
    assert {i.product_code for i in by_name.items} == {"prod_mwbl_active"}
    assert {i.product_code for i in by_brand.items} == {"prod_mwbl_hidden", "prod_mwbl_noinv"}
    assert {i.product_code for i in inactive_only.items} == {"prod_mwbl_inactive"}


def test_detail_not_found_raises(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            get_admin_product_detail(session, "prod_does_not_exist")
    assert exc.value.status_code == 404


def test_pagination_stable(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        page1 = list_admin_products(session, page=1, page_size=2)
        page2 = list_admin_products(session, page=2, page_size=2)
    assert page1.pagination.total_pages == 2
    assert page1.pagination.has_next is True
    assert page2.pagination.has_prev is True
    codes = [i.product_code for i in page1.items] + [i.product_code for i in page2.items]
    assert len(set(codes)) == 4  # 페이지 간 중복 없음(안정 정렬)


# --- 라우트 계층(인증·검증) ---


def test_route_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/products").status_code == 401


def test_route_rejects_non_admin(client: TestClient, db_engine: Engine) -> None:
    client.post(
        "/api/auth/signup",
        json={
            "email": "plain-user@example.com",
            "password": "password123",
            "nickname": "plain",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert client.get("/api/admin/products").status_code == 403


def test_route_returns_list_for_admin(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.get("/api/admin/products", params={"page_size": 50})
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total_items"] == 4
    assert any(item["product_code"] == "prod_mwbl_inactive" for item in body["items"])


def test_route_rejects_invalid_sales_status(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.get("/api/admin/products", params={"sales_status": "NOPE"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_route_detail_404(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    assert client.get("/api/admin/products/prod_does_not_exist").status_code == 404
