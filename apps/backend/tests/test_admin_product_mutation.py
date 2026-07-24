"""P1-M3-A Chunk 4 관리자 상품 등록·수정 focused 테스트."""

from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

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
from app.schemas.admin.product import AdminProductCreateRequest, AdminProductUpdateRequest
from app.schemas.common import ApiError
from app.services import catalog_sync
from app.services.admin import product_mutation_service
from app.services.admin.product_mutation_service import create_admin_product, update_admin_product
from app.services.elasticsearch_catalog_index import ElasticsearchCatalogIndexError


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


def test_create_product_with_thumbnail_storage_key(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = create_admin_product(
            session,
            _create_request(thumbnail_storage_key="  products/qa/thumb_0  "),
            now=FIXED_NOW,
        )
    # 공백은 trim 되어 저장되고(원문 그대로 신뢰, 파일 실존 검증은 하지 않음), image_count 에 반영된다.
    assert result.thumbnail_url == "products/qa/thumb_0"
    assert result.image_count == 1


@pytest.mark.parametrize(
    "bad_key",
    [
        "https://image.oliveyoung.co.kr/x.jpg",
        "http://evil.com/a.jpg",
        "products/../../etc/passwd",
        "../secret",
    ],
)
def test_create_product_rejects_absolute_url_and_path_traversal_thumbnail(
    db_engine: Engine, bad_key: str
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            create_admin_product(session, _create_request(thumbnail_storage_key=bad_key), now=FIXED_NOW)
    assert exc.value.code == "INVALID_PRODUCT_FIELD"


def test_create_product_blank_thumbnail_storage_key_is_no_image(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = create_admin_product(session, _create_request(thumbnail_storage_key="   "), now=FIXED_NOW)
    assert result.thumbnail_url == ""
    assert result.image_count == 0


def test_update_thumbnail_storage_key_replaces_without_duplicate_row(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        create_admin_product(
            session,
            AdminProductCreateRequest(
                name="이미지 교체용",
                brand_code="brand_a",
                category_code="cat_a",
                price=1000,
                thumbnail_storage_key="products/qa/thumb_0",
            ),
            now=FIXED_NOW,
        )
        product = session.execute(
            select(Product).where(Product.product_name == "이미지 교체용")
        ).scalar_one()

        updated = update_admin_product(
            session,
            product.product_code,
            AdminProductUpdateRequest(thumbnail_storage_key="products/qa/thumb_1"),
            now=FIXED_NOW,
        )
        image_rows = session.execute(
            select(ProductImage).where(ProductImage.product_id == product.id)
        ).scalars().all()

    assert updated.thumbnail_url == "products/qa/thumb_1"
    assert len(image_rows) == 1  # upsert — 새 행이 추가되는 게 아니라 기존 행이 교체됨


def test_update_thumbnail_storage_key_null_clears_image(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        created = create_admin_product(
            session,
            AdminProductCreateRequest(
                name="이미지 삭제용",
                brand_code="brand_a",
                category_code="cat_a",
                price=1000,
                thumbnail_storage_key="products/qa/thumb_0",
            ),
            now=FIXED_NOW,
        )
        product = session.execute(
            select(Product).where(Product.product_code == created.product_code)
        ).scalar_one()

        cleared = update_admin_product(
            session,
            created.product_code,
            AdminProductUpdateRequest(thumbnail_storage_key=None),
            now=FIXED_NOW,
        )
        image_rows = session.execute(
            select(ProductImage).where(ProductImage.product_id == product.id)
        ).scalars().all()

    assert cleared.thumbnail_url == ""
    assert cleared.image_count == 0
    assert image_rows == []


def test_create_and_update_thumbnail_keep_search_thumbnail_in_sync(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        created = create_admin_product(
            session,
            AdminProductCreateRequest(
                name="thumbnail synchronization",
                brand_code="brand_a",
                category_code="cat_a",
                price=1000,
                thumbnail_storage_key="products/qa/thumb_0",
            ),
            now=FIXED_NOW,
        )
        product = session.execute(
            select(Product).where(Product.product_code == created.product_code)
        ).scalar_one()
        assert product.thumbnail_url == "products/qa/thumb_0"

        update_admin_product(
            session,
            created.product_code,
            AdminProductUpdateRequest(thumbnail_storage_key="products/qa/thumb_1"),
            now=FIXED_NOW,
        )
        assert product.thumbnail_url == "products/qa/thumb_1"

        updated_at_before_noop = product.updated_at
        update_admin_product(
            session,
            created.product_code,
            AdminProductUpdateRequest(thumbnail_storage_key="products/qa/thumb_1"),
            now=datetime(2026, 7, 16, 3, 0, tzinfo=timezone.utc),
        )
        assert product.updated_at == updated_at_before_noop

        update_admin_product(
            session,
            created.product_code,
            AdminProductUpdateRequest(thumbnail_storage_key=None),
            now=FIXED_NOW,
        )
        assert product.thumbnail_url is None


def test_update_thumbnail_storage_key_conflict_with_existing_image(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == "prod_mwbl_editable")
        ).scalar_one()
        session.add(
            ProductImage(product_id=product.id, image_type="detail", display_order=1, storage_key="products/dup/key")
        )
        session.flush()

        with pytest.raises(ApiError) as exc:
            update_admin_product(
                session,
                "prod_mwbl_editable",
                AdminProductUpdateRequest(thumbnail_storage_key="products/dup/key"),
                now=FIXED_NOW,
            )

    assert exc.value.status_code == 409
    assert exc.value.code == "PRODUCT_IMAGE_STORAGE_KEY_CONFLICT"


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


def test_admin_patch_route_rejects_price_above_shared_cap(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)

    response = client.patch("/api/admin/products/prod_mwbl_editable", json={"price": 100_000_001})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PRODUCT_FIELD"


def test_admin_patch_route_omitted_thumbnail_keeps_existing_image(
    client: TestClient, db_engine: Engine
) -> None:
    _authed_admin(client, db_engine)
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == "prod_mwbl_editable")
        ).scalar_one()
        session.add(
            ProductImage(
                product_id=product.id,
                image_type="thumbnail",
                display_order=0,
                storage_key="products/qa/keep_thumbnail",
            )
        )
        session.commit()

    response = client.patch(
        "/api/admin/products/prod_mwbl_editable",
        json={"name": "이미지 유지 수정"},
    )

    assert response.status_code == 200
    assert response.json()["thumbnail_url"] == "products/qa/keep_thumbnail"
    assert response.json()["image_count"] == 1
    with Session(db_engine) as session:
        image_rows = session.execute(
            select(ProductImage).join(Product).where(Product.product_code == "prod_mwbl_editable")
        ).scalars().all()
        assert [image.storage_key for image in image_rows] == ["products/qa/keep_thumbnail"]


def test_admin_patch_route_rejects_missing_product(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    response = client.patch("/api/admin/products/prod_missing", json={"name": "없는 상품"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_admin_product_form_options_return_only_active_masters(client: TestClient, db_engine: Engine) -> None:
    _authed_admin(client, db_engine)
    brands = client.get("/api/admin/product-brands")
    categories = client.get("/api/admin/product-categories")

    assert brands.status_code == 200
    assert categories.status_code == 200
    assert {item["code"] for item in brands.json()["items"]} == {"brand_a", "brand_b"}
    assert {item["code"] for item in categories.json()["items"]} == {"cat_a", "cat_b"}


@pytest.mark.parametrize(
    ("method", "path", "body", "expected_status", "expected_action"),
    [
        (
            "post",
            "/api/admin/products",
            {
                "name": "색인 후처리 등록 상품",
                "brand_code": "brand_a",
                "category_code": "cat_a",
                "price": 19_900,
            },
            201,
            "DELETED_OR_MISSING",
        ),
        (
            "patch",
            "/api/admin/products/prod_mwbl_editable",
            {"name": "색인 후처리 수정 상품"},
            200,
            "INDEXED",
        ),
    ],
)
def test_admin_product_mutation_reindexes_after_commit(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, object],
    expected_status: int,
    expected_action: str,
) -> None:
    _authed_admin(client, db_engine)
    sync_calls: list[str] = []
    performance_events: list[tuple[str, dict[str, object]]] = []

    def fake_reindex(session: Session, *, product_id: str):
        assert session.in_transaction() is False
        sync_calls.append(product_id)
        return SimpleNamespace(action=expected_action)

    def fake_log(event: str, **kwargs: object) -> None:
        performance_events.append((event, kwargs))

    monkeypatch.setattr(catalog_sync, "reindex_catalog_product_to_elasticsearch", fake_reindex)
    monkeypatch.setattr(catalog_sync, "log_performance_event", fake_log)

    response = getattr(client, method)(path, json=body)

    assert response.status_code == expected_status
    product_code = response.json()["product_code"]
    assert sync_calls == [product_code]
    assert [event for event, _ in performance_events] == ["admin_product_catalog_sync_completed"]
    assert performance_events[0][1]["metadata"] == {
        "product_id": product_code,
        "action": expected_action,
    }


def test_admin_product_es_failure_keeps_committed_update(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _authed_admin(client, db_engine)
    performance_events: list[tuple[str, dict[str, object]]] = []

    def fail_reindex(session: Session, *, product_id: str):
        assert session.in_transaction() is False
        raise ElasticsearchCatalogIndexError("test Elasticsearch failure")

    def fake_log(event: str, **kwargs: object) -> None:
        performance_events.append((event, kwargs))

    monkeypatch.setattr(catalog_sync, "reindex_catalog_product_to_elasticsearch", fail_reindex)
    monkeypatch.setattr(catalog_sync, "log_performance_event", fake_log)

    response = client.patch(
        "/api/admin/products/prod_mwbl_editable",
        json={"name": "ES 실패 후에도 저장되는 상품"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "ES 실패 후에도 저장되는 상품"
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == "prod_mwbl_editable")
        ).scalar_one()
        assert product.product_name == "ES 실패 후에도 저장되는 상품"
    assert [event for event, _ in performance_events] == ["admin_product_catalog_sync_failed"]
    assert performance_events[0][1]["metadata"] == {
        "product_id": "prod_mwbl_editable",
        "error": "ElasticsearchCatalogIndexError",
    }
