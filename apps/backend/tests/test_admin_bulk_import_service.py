"""M3-B Chunk 3 bulk 저장·부분 성공·refresh 경계 테스트."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import products as products_route
from app.db.base import Base
from app.db.models.catalog import Brand, Product, ProductCategory, ProductIngredient, ProductPrice
from app.db.models.commerce import Inventory, Seller
from app.db.models.auth import User
from app.db.models.taxonomy import Ingredient
from app.db.session import get_db
from app.main import app
from app.schemas.admin.bulk_import import AdminBulkImportRequest, AdminBulkImportRowRequest
from app.schemas.common import ApiError
from app.services.admin import bulk_import_service
from app.services.admin.bulk_import_validation_service import validate_bulk_import
from app.services.admin.ingredient_mapping_pending_groups import PendingIngredientGroupsRefreshError
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
        _seed_masters(sess)
        sess.commit()
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


def _seed_masters(session: Session) -> None:
    session.add_all(
        [
            Seller(seller_code="mwobareullae", display_name="뭐바를래", status="ACTIVE"),
            Brand(
                brand_code="bulk_brand",
                name="대량 브랜드",
                normalized_name=normalize_for_resolution("대량 브랜드"),
            ),
            ProductCategory(category_code="bulk_category", name="스킨케어"),
            Ingredient(
                ingredient_code="ing_water",
                name_ko="정제수",
                normalized_name=normalize_for_resolution("정제수"),
                is_active=True,
            ),
        ]
    )


def _request(*, sku: str = "IMPORT_001", ingredients: str = "정제수") -> AdminBulkImportRequest:
    return AdminBulkImportRequest(
        rows=[
            AdminBulkImportRowRequest(
                import_sku=sku,
                product_name="대량등록 상품",
                brand_name="대량 브랜드",
                category_name="스킨케어",
                price=12_000,
                stock_quantity=17,
                ingredients_raw=ingredients,
            )
        ]
    )


def _promote_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": "bulk-import-admin@example.com",
            "password": "password123",
            "nickname": "bulk-import-admin",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.execute(
            select(User).where(User.email == "bulk-import-admin@example.com")
        ).scalar_one()
        user.role = "ADMIN"
        session.commit()


def test_run_bulk_import_creates_hidden_product_price_inventory_and_ingredients(session: Session) -> None:
    stored = bulk_import_service.run_bulk_import(session, validate_bulk_import(session, _request()))

    assert len(stored.created_rows) == 1
    assert not stored.skipped_rows
    assert not stored.failed_rows
    assert stored.requires_review_refresh is False

    product = session.execute(select(Product)).scalar_one()
    inventory = session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one()
    price = session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()
    ingredient = session.execute(
        select(ProductIngredient).where(ProductIngredient.product_id == product.id)
    ).scalar_one()

    assert product.import_sku == "IMPORT_001"
    assert product.is_active is False
    assert inventory.sales_status == "HIDDEN"
    assert inventory.stock_quantity == 17
    assert price.price == 12_000
    assert ingredient.ingredient_name == "정제수"


def test_run_bulk_import_skips_existing_import_sku_without_mutating_product(session: Session) -> None:
    first = bulk_import_service.run_bulk_import(session, validate_bulk_import(session, _request()))
    session.commit()
    existing_code = first.created_rows[0].product_code

    second = bulk_import_service.run_bulk_import(session, validate_bulk_import(session, _request()))

    assert not second.created_rows
    assert second.skipped_rows == [
        bulk_import_service.SkippedBulkImportRow(
            row_number=1,
            import_sku="IMPORT_001",
            existing_product_code=existing_code,
        )
    ]
    assert session.execute(select(Product)).scalars().all()[0].product_code == existing_code


def test_resolution_error_rolls_back_only_that_product_row(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_resolution_error(*args: object, **kwargs: object) -> object:
        raise ApiError(409, "INGREDIENT_PENDING_CODE_CONFLICT", "pending 충돌")

    monkeypatch.setattr(bulk_import_service, "resolve_many", _raise_resolution_error)

    stored = bulk_import_service.run_bulk_import(session, validate_bulk_import(session, _request()))

    assert not stored.created_rows
    assert stored.failed_rows[0].error_code == "INGREDIENT_PENDING_CODE_CONFLICT"
    assert session.execute(select(Product)).scalars().all() == []


def test_pending_ingredient_marks_refresh_required(session: Session) -> None:
    stored = bulk_import_service.run_bulk_import(
        session,
        validate_bulk_import(session, _request(ingredients="새로운성분")),
    )

    assert len(stored.created_rows) == 1
    assert stored.requires_review_refresh is True
    assert stored.created_rows[0].ingredient_counters["created_pending_count"] == 1


def test_bulk_route_skips_es_sync_and_returns_not_required_for_hidden_product(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unexpected_es_sync(*args: object, **kwargs: object) -> None:
        raise AssertionError("HIDDEN bulk product must not invoke ES sync")

    monkeypatch.setattr(products_route, "_sync_catalog_product_after_commit", _unexpected_es_sync)

    response = products_route.bulk_create_products(_request(), session)

    assert response.summary.created == 1
    assert response.review_refresh == "NOT_REQUIRED"


def test_bulk_route_preserves_saved_rows_when_refresh_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refresh_failure(*args: object, **kwargs: object) -> float:
        raise PendingIngredientGroupsRefreshError("refresh failed")

    monkeypatch.setattr(products_route, "refresh_pending_ingredient_mapping_groups", _refresh_failure)

    response = products_route.bulk_create_products(_request(ingredients="새로운성분"), session)

    assert response.summary.created == 1
    assert response.review_refresh == "FAILED"
    assert response.refresh_recovery_command == "python -m app.cli.refresh_ingredient_mapping_pending_groups"
    assert session.execute(select(Product)).scalar_one().import_sku == "IMPORT_001"


def test_bulk_storage_loads_master_rows_once_not_per_product(
    session: Session, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = AdminBulkImportRequest(
        rows=[
            _request(sku=f"IMPORT_{index:03d}").rows[0]
            for index in range(1, 6)
        ]
    )
    validation = validate_bulk_import(session, request)

    monkeypatch.setattr(
        bulk_import_service,
        "resolve_many",
        lambda *_args, **_kwargs: SimpleNamespace(
            results=[],
            counters={
                "input_count": 0,
                "saved_count": 0,
                "canonical_count": 0,
                "pending_count": 0,
                "duplicate_count": 0,
                "created_pending_count": 0,
            },
        ),
    )
    counter = {"selects": 0}

    def _count_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counter["selects"] += 1

    event.listen(db_engine, "before_cursor_execute", _count_selects)
    try:
        stored = bulk_import_service.run_bulk_import(session, validation)
    finally:
        event.remove(db_engine, "before_cursor_execute", _count_selects)

    assert len(stored.created_rows) == 5
    # seller + active brands + active categories만 읽고, 행별 master 조회는 하지 않는다.
    assert counter["selects"] <= 3


def test_bulk_endpoint_returns_partial_success_contract(
    client: TestClient, db_engine: Engine
) -> None:
    with Session(db_engine) as session:
        _seed_masters(session)
        session.commit()
    _promote_admin(client, db_engine)

    response = client.post(
        "/api/admin/products/bulk",
        json={
            "rows": [
                {
                    "import_sku": "IMPORT_API_001",
                    "product_name": "API 대량등록 상품",
                    "brand_name": "대량 브랜드",
                    "category_name": "스킨케어",
                    "price": 18000,
                    "stock_quantity": 8,
                    "ingredients_raw": "정제수",
                },
                {
                    "import_sku": "import_invalid",
                    "product_name": "실패 상품",
                    "brand_name": "대량 브랜드",
                    "category_name": "스킨케어",
                    "price": 18000,
                    "stock_quantity": 8,
                    "ingredients_raw": "정제수",
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"total": 2, "created": 1, "skipped": 0, "failed": 1}
    assert [row["status"] for row in body["rows"]] == ["CREATED", "FAILED"]
    assert body["review_refresh"] == "NOT_REQUIRED"


@pytest.mark.slow
def test_bulk_import_200_rows_records_local_processing_duration(
    session: Session, record_property: pytest.RecordProperty
) -> None:
    """시간 상한을 강제하지 않는 로컬 추적용 벤치다.

    PostgreSQL·refresh 시간을 포함한 운영 부하 평가는 별도로 수행한다. 이 테스트는
    200행 저장 경로가 정상 완료되는지와, 실행 시간이 CI 합격 조건이 아닌 기록값임을 보장한다.
    """
    request = AdminBulkImportRequest(
        rows=[
            _request(sku=f"IMPORT_BENCH_{index:03d}").rows[0]
            for index in range(1, 201)
        ]
    )
    counter = {"selects": 0}

    def _count_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counter["selects"] += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _count_selects)
    started_at = perf_counter()
    try:
        stored = bulk_import_service.run_bulk_import(session, validate_bulk_import(session, request))
        duration_ms = (perf_counter() - started_at) * 1000
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)

    assert len(stored.created_rows) == 200
    assert not stored.failed_rows
    # PostgreSQL 실측(200행 canonical-only) 807 SELECT를 상한으로 고정한다.
    assert counter["selects"] <= 807
    record_property("bulk_import_200_rows_selects", counter["selects"])
    record_property("bulk_import_200_rows_storage_ms", round(duration_ms, 2))
