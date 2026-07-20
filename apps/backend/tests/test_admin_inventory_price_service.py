"""P1-M4 Chunk 1 재고·가격 조회 focused 테스트."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductPrice
from app.db.models.commerce import Inventory, InventoryMovement, Seller
from app.db.session import get_db
from app.main import app
from app.api.routes.admin import inventory_price as inventory_price_route
from app.schemas.common import ApiError
from app.services.admin.inventory_price_service import (
    HISTORY_LIMIT,
    INVENTORY_STOCK_MAX,
    adjust_admin_inventory,
    get_admin_inventory_history,
    list_admin_inventory_prices,
    start_admin_product_sale,
    update_admin_inventory_price,
)
from app.services.product_pricing import MAX_PRODUCT_PRICE


ADMIN_EMAIL = "admin-inventory@example.com"


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
    brand = Brand(brand_code="brand_a", name="브랜드에이", normalized_name="branda")
    category = ProductCategory(category_code="serum", name="세럼")
    session.add_all([seller, brand, category])
    session.flush()

    base_time = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)

    def product(
        code: str,
        name: str,
        *,
        sequence: int,
        stock: int | None,
        reserved: int = 0,
        safety: int = 0,
        sales_status: str = "ON_SALE",
        is_active: bool = True,
    ) -> Product:
        row = Product(
            product_code=code,
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name=name,
            is_active=is_active,
            is_recommendable=False,
            updated_at=base_time + timedelta(minutes=sequence),
        )
        session.add(row)
        session.flush()
        session.add(
            ProductPrice(
                product_id=row.id,
                mall_name=seller.display_name,
                price=10_000 + sequence,
                currency="KRW",
                product_url=f"/products/{code}",
                is_lowest=True,
            )
        )
        if stock is not None:
            session.add(
                Inventory(
                    product_id=row.id,
                    stock_quantity=stock,
                    reserved_quantity=reserved,
                    safety_stock=safety,
                    sales_status=sales_status,
                    updated_at=base_time + timedelta(minutes=sequence),
                )
            )
        return row

    in_stock = product("prod_inventory_in", "재고 충분 세럼", sequence=1, stock=6)
    product("prod_inventory_low", "저재고 세럼", sequence=2, stock=7, reserved=1, safety=1)
    product("prod_inventory_sold", "품절 세럼", sequence=3, stock=1, reserved=1, sales_status="SOLD_OUT")
    product(
        "prod_inventory_hidden",
        "숨김 세럼",
        sequence=4,
        stock=99,
        sales_status="HIDDEN",
        is_active=False,
    )
    product("prod_inventory_unknown", "재고 미상 세럼", sequence=5, stock=None)

    inventory = session.execute(select(Inventory).where(Inventory.product_id == in_stock.id)).scalar_one()
    for index in range(HISTORY_LIMIT + 1):
        session.add(
            InventoryMovement(
                inventory_id=inventory.id,
                product_id=in_stock.id,
                movement_type="ADMIN_ADJUST" if index == HISTORY_LIMIT else "RESERVE",
                quantity_delta=-1,
                stock_after=100 - index,
                reason=f"movement-{index}",
                reference_type="test",
                reference_id=str(index),
                created_at=base_time + timedelta(hours=index),
            )
        )


def _as_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": ADMIN_EMAIL,
            "password": "password123",
            "nickname": "admin-inventory",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        session.commit()


def test_list_uses_common_availability_and_keeps_unknown_visible(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = list_admin_inventory_prices(
            session,
            query=None,
            sales_status=None,
            stock_status=None,
            limit=20,
            cursor=None,
        )

    by_code = {item.product_code: item for item in result.items}
    assert by_code["prod_inventory_in"].availability.stock_status == "IN_STOCK"
    assert by_code["prod_inventory_low"].availability.available_quantity == 5
    assert by_code["prod_inventory_low"].availability.stock_status == "LOW_STOCK"
    assert by_code["prod_inventory_sold"].availability.stock_status == "SOLD_OUT"
    assert by_code["prod_inventory_hidden"].availability.stock_status == "HIDDEN"
    assert by_code["prod_inventory_unknown"].availability.stock_status == "UNKNOWN"
    assert by_code["prod_inventory_unknown"].stock_quantity is None


def test_list_filters_actual_sales_status_and_derived_stock_status(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        low_stock = list_admin_inventory_prices(
            session,
            query=None,
            sales_status=None,
            stock_status="LOW_STOCK",
            limit=20,
            cursor=None,
        )
        hidden = list_admin_inventory_prices(
            session,
            query=None,
            sales_status="HIDDEN",
            stock_status="HIDDEN",
            limit=20,
            cursor=None,
        )

    assert [item.product_code for item in low_stock.items] == ["prod_inventory_low"]
    assert [item.product_code for item in hidden.items] == ["prod_inventory_hidden"]


def test_list_cursor_is_stable_and_rejects_filter_change(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        first = list_admin_inventory_prices(
            session,
            query=None,
            sales_status=None,
            stock_status=None,
            limit=2,
            cursor=None,
        )
        second = list_admin_inventory_prices(
            session,
            query=None,
            sales_status=None,
            stock_status=None,
            limit=2,
            cursor=first.next_cursor,
        )
        assert first.next_cursor is not None
        with pytest.raises(ApiError) as exc:
            list_admin_inventory_prices(
                session,
                query=None,
                sales_status=None,
                stock_status="LOW_STOCK",
                limit=2,
                cursor=first.next_cursor,
            )

    first_codes = {item.product_code for item in first.items}
    second_codes = {item.product_code for item in second.items}
    assert not first_codes & second_codes
    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_CURSOR"


def test_history_returns_latest_twenty_real_movement_codes(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        result = get_admin_inventory_history(session, product_code="prod_inventory_in")

    assert result.product_code == "prod_inventory_in"
    assert len(result.items) == HISTORY_LIMIT
    assert result.items[0].reason == "movement-20"
    assert result.items[0].movement_type == "ADMIN_ADJUST"
    assert result.items[-1].reason == "movement-1"


def test_history_rejects_unknown_product(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            get_admin_inventory_history(session, product_code="prod_missing")
    assert exc.value.status_code == 404
    assert exc.value.code == "PRODUCT_NOT_FOUND"


def test_routes_require_admin_and_return_inventory_data(client: TestClient, db_engine: Engine) -> None:
    assert client.get("/api/admin/inventory").status_code == 401
    assert client.post("/api/admin/inventory/prod_inventory_hidden/sale-start").status_code == 401

    client.post(
        "/api/auth/signup",
        json={
            "email": "plain-inventory@example.com",
            "password": "password123",
            "nickname": "plain-inventory",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert client.get("/api/admin/inventory").status_code == 403

    _as_admin(client, db_engine)
    response = client.get("/api/admin/inventory", params={"stock_status": "LOW_STOCK"})
    assert response.status_code == 200
    assert [item["product_code"] for item in response.json()["items"]] == ["prod_inventory_low"]
    history = client.get("/api/admin/inventory/prod_inventory_in/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["movement_type"] == "ADMIN_ADJUST"


def test_route_rejects_invalid_stock_status(client: TestClient, db_engine: Engine) -> None:
    _as_admin(client, db_engine)
    response = client.get("/api/admin/inventory", params={"stock_status": "UNKNOWN"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INVENTORY_STOCK_STATUS"


def test_adjust_sets_absolute_stock_and_records_admin_movement(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        response = adjust_admin_inventory(
            session,
            product_code="prod_inventory_in",
            stock_quantity=12,
            reason="  입고 수량 보정  ",
            now=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        )
        session.commit()

    assert response.changed is True
    assert response.stock_quantity == 12
    assert response.availability.available_quantity == 12
    assert response.movement is not None
    assert response.movement.movement_type == "ADMIN_ADJUST"
    assert response.movement.quantity_delta == 6
    assert response.movement.stock_after == 12
    assert response.movement.reason == "입고 수량 보정"
    assert response.movement.reference_type == "admin_inventory"
    assert response.movement.reference_id == "prod_inventory_in"

    with Session(db_engine) as session:
        inventory = session.execute(
            select(Inventory).join(Product).where(Product.product_code == "prod_inventory_in")
        ).scalar_one()
    assert inventory.stock_quantity == 12


def test_adjust_same_absolute_stock_is_noop_without_movement(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        before = session.scalar(
            select(func.count()).select_from(InventoryMovement).join(Product).where(
                Product.product_code == "prod_inventory_in"
            )
        )
        response = adjust_admin_inventory(
            session,
            product_code="prod_inventory_in",
            stock_quantity=6,
            reason="네트워크 재시도",
        )
        session.commit()
        after = session.scalar(
            select(func.count()).select_from(InventoryMovement).join(Product).where(
                Product.product_code == "prod_inventory_in"
            )
        )

    assert response.changed is False
    assert response.movement is None
    assert before == after


def test_adjust_rejects_out_of_range_and_available_quantity_below_zero(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as max_error:
            adjust_admin_inventory(
                session,
                product_code="prod_inventory_in",
                stock_quantity=INVENTORY_STOCK_MAX + 1,
                reason="오입력 확인",
            )
        with pytest.raises(ApiError) as availability_error:
            adjust_admin_inventory(
                session,
                product_code="prod_inventory_low",
                stock_quantity=1,
                reason="예약 재고보다 낮은 값",
            )
        session.rollback()

    assert max_error.value.status_code == 400
    assert max_error.value.code == "INVALID_INVENTORY_STOCK"
    assert availability_error.value.status_code == 409
    assert availability_error.value.code == "INVENTORY_AVAILABLE_QUANTITY_NEGATIVE"


def test_adjust_distinguishes_missing_product_and_inventory_row(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as product_error:
            adjust_admin_inventory(
                session,
                product_code="prod_missing",
                stock_quantity=1,
                reason="대상 확인",
            )
        with pytest.raises(ApiError) as inventory_error:
            adjust_admin_inventory(
                session,
                product_code="prod_inventory_unknown",
                stock_quantity=1,
                reason="대상 확인",
            )

    assert product_error.value.status_code == 404
    assert product_error.value.code == "PRODUCT_NOT_FOUND"
    assert inventory_error.value.status_code == 404
    assert inventory_error.value.code == "INVENTORY_ROW_NOT_FOUND"


def test_adjust_route_reindexes_only_when_changed_and_not_hidden(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as_admin(client, db_engine)
    sync_calls: list[tuple[str, str]] = []

    def fake_sync(session: Session, product_code: str, *, event_prefix: str = "admin_product") -> None:
        assert session.in_transaction() is False
        sync_calls.append((product_code, event_prefix))

    monkeypatch.setattr(inventory_price_route, "sync_catalog_product_after_commit", fake_sync)

    changed = client.patch(
        "/api/admin/inventory/prod_inventory_in",
        json={"stock_quantity": 10, "reason": "입고 반영"},
    )
    noop = client.patch(
        "/api/admin/inventory/prod_inventory_in",
        json={"stock_quantity": 10, "reason": "응답 재확인"},
    )
    hidden = client.patch(
        "/api/admin/inventory/prod_inventory_hidden",
        json={"stock_quantity": 100, "reason": "판매 준비 재고 입력"},
    )
    sold_out = client.patch(
        "/api/admin/inventory/prod_inventory_sold",
        json={"stock_quantity": 3, "reason": "품절 재고 보정"},
    )

    assert changed.status_code == 200
    assert changed.json()["changed"] is True
    assert changed.json()["movement"]["movement_type"] == "ADMIN_ADJUST"
    assert noop.status_code == 200
    assert noop.json()["changed"] is False
    assert noop.json()["movement"] is None
    assert hidden.status_code == 200
    assert hidden.json()["changed"] is True
    assert sold_out.status_code == 200
    assert sold_out.json()["changed"] is True
    assert sync_calls == [
        ("prod_inventory_in", "admin_inventory"),
        ("prod_inventory_sold", "admin_inventory"),
    ]


def test_adjust_route_rejects_blank_reason_and_unknown_fields(client: TestClient, db_engine: Engine) -> None:
    _as_admin(client, db_engine)
    blank_reason = client.patch(
        "/api/admin/inventory/prod_inventory_in",
        json={"stock_quantity": 10, "reason": "   "},
    )
    unknown_field = client.patch(
        "/api/admin/inventory/prod_inventory_in",
        json={"stock_quantity": 10, "reason": "입고", "safety_stock": 1},
    )
    out_of_range = client.patch(
        "/api/admin/inventory/prod_inventory_in",
        json={"stock_quantity": INVENTORY_STOCK_MAX + 1, "reason": "오입력 확인"},
    )

    assert blank_reason.status_code == 400
    assert blank_reason.json()["error"]["code"] == "INVALID_INVENTORY_ADJUSTMENT_REASON"
    assert unknown_field.status_code == 400
    assert out_of_range.status_code == 400
    assert out_of_range.json()["error"]["code"] == "INVALID_INVENTORY_STOCK"


def test_price_update_changes_price_and_product_updated_at(db_engine: Engine) -> None:
    timestamp = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        outcome = update_admin_inventory_price(
            session,
            product_code="prod_inventory_in",
            price=21_900,
            now=timestamp,
        )
        session.commit()

    assert outcome.response.changed is True
    assert outcome.response.price == 21_900
    assert outcome.response.currency == "KRW"
    assert outcome.response.is_lowest is True
    assert outcome.response.collected_at == timestamp
    assert outcome.response.updated_at == timestamp
    assert outcome.requires_catalog_sync is True

    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == "prod_inventory_in")).scalar_one()
        price_row = session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()
    assert product.updated_at.replace(tzinfo=UTC) == timestamp
    assert price_row.price == 21_900
    assert price_row.product_url == "/product-detail?id=prod_inventory_in"


def test_price_update_same_value_is_noop_without_timestamp_or_sync_change(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == "prod_inventory_in")).scalar_one()
        price_row = session.execute(select(ProductPrice).where(ProductPrice.product_id == product.id)).scalar_one()
        previous_updated_at = product.updated_at
        previous_collected_at = price_row.collected_at

        outcome = update_admin_inventory_price(
            session,
            product_code="prod_inventory_in",
            price=price_row.price,
            now=datetime(2026, 7, 18, 15, 0, tzinfo=UTC),
        )
        session.commit()

    assert outcome.response.changed is False
    assert outcome.response.updated_at == previous_updated_at
    assert outcome.response.collected_at == previous_collected_at
    assert outcome.requires_catalog_sync is False


@pytest.mark.parametrize("invalid_value", [0, MAX_PRODUCT_PRICE + 1])
def test_price_update_rejects_invalid_value_and_detects_duplicate_first_party_rows(
    db_engine: Engine,
    invalid_value: int,
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as invalid_price:
            update_admin_inventory_price(
                session,
                product_code="prod_inventory_in",
                price=invalid_value,
            )

        product = session.execute(select(Product).where(Product.product_code == "prod_inventory_in")).scalar_one()
        session.add(
            ProductPrice(
                product_id=product.id,
                mall_name="뭐바를래",
                price=99_000,
                currency="KRW",
                product_url="/products/duplicate",
                is_lowest=True,
            )
        )
        session.flush()
        with pytest.raises(ApiError) as duplicate_price:
            update_admin_inventory_price(session, product_code="prod_inventory_in", price=22_000)
        session.rollback()

    assert invalid_price.value.status_code == 400
    assert invalid_price.value.code == "INVALID_PRICE"
    assert duplicate_price.value.status_code == 409
    assert duplicate_price.value.code == "PRODUCT_PRICE_INCONSISTENT"


def test_price_update_creates_missing_price_row_and_syncs_non_hidden_product(db_engine: Engine) -> None:
    timestamp = datetime(2026, 7, 18, 15, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == "prod_inventory_unknown")).scalar_one()
        product_id = product.id
        session.execute(delete(ProductPrice).where(ProductPrice.product_id == product.id))
        session.flush()

        outcome = update_admin_inventory_price(
            session,
            product_code="prod_inventory_unknown",
            price=30_000,
            now=timestamp,
        )
        session.commit()

    assert outcome.response.changed is True
    assert outcome.response.price == 30_000
    assert outcome.requires_catalog_sync is True

    with Session(db_engine) as session:
        price_row = session.execute(select(ProductPrice).where(ProductPrice.product_id == product_id)).scalar_one()
    assert price_row.mall_name == "뭐바를래"
    assert price_row.currency == "KRW"
    assert price_row.is_lowest is True


def test_price_route_reindexes_changed_non_hidden_products_only(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as_admin(client, db_engine)
    sync_calls: list[tuple[str, str]] = []

    def fake_sync(session: Session, product_code: str, *, event_prefix: str = "admin_product") -> None:
        assert session.in_transaction() is False
        sync_calls.append((product_code, event_prefix))

    monkeypatch.setattr(inventory_price_route, "sync_catalog_product_after_commit", fake_sync)

    changed = client.patch("/api/admin/inventory/prod_inventory_in/price", json={"price": 20_000})
    noop = client.patch("/api/admin/inventory/prod_inventory_in/price", json={"price": 20_000})
    hidden = client.patch("/api/admin/inventory/prod_inventory_hidden/price", json={"price": 30_000})
    sold_out = client.patch("/api/admin/inventory/prod_inventory_sold/price", json={"price": 40_000})

    assert changed.status_code == 200
    assert changed.json()["changed"] is True
    assert noop.status_code == 200
    assert noop.json()["changed"] is False
    assert hidden.status_code == 200
    assert sold_out.status_code == 200
    assert sync_calls == [
        ("prod_inventory_in", "admin_inventory"),
        ("prod_inventory_sold", "admin_inventory"),
    ]


def test_sale_start_transitions_hidden_product_and_updates_timestamp(db_engine: Engine) -> None:
    timestamp = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        response = start_admin_product_sale(
            session,
            product_code="prod_inventory_hidden",
            now=timestamp,
        )
        session.commit()

    assert response.product_code == "prod_inventory_hidden"
    assert response.sales_status == "ON_SALE"
    assert response.is_active is True
    assert response.started_at == timestamp

    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == "prod_inventory_hidden")
        ).scalar_one()
        inventory = session.execute(
            select(Inventory).where(Inventory.product_id == product.id)
        ).scalar_one()
    assert product.is_active is True
    assert product.updated_at.replace(tzinfo=UTC) == timestamp
    assert inventory.sales_status == "ON_SALE"


@pytest.mark.parametrize(
    ("product_code", "expected_status", "expected_code"),
    [
        ("prod_missing", 404, "PRODUCT_NOT_FOUND"),
        ("prod_inventory_in", 409, "PRODUCT_NOT_HIDDEN"),
        ("prod_inventory_sold", 409, "PRODUCT_NOT_HIDDEN"),
        ("prod_inventory_unknown", 409, "INSUFFICIENT_STOCK_FOR_SALE"),
    ],
)
def test_sale_start_rejects_missing_or_non_hidden_inventory_states(
    db_engine: Engine,
    product_code: str,
    expected_status: int,
    expected_code: str,
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc:
            start_admin_product_sale(session, product_code=product_code)

    assert exc.value.status_code == expected_status
    assert exc.value.code == expected_code


def test_sale_start_checks_price_stock_and_current_taxonomy_activity(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        hidden_product = session.execute(
            select(Product).where(Product.product_code == "prod_inventory_hidden")
        ).scalar_one()
        hidden_product_id = hidden_product.id

        session.execute(delete(ProductPrice).where(ProductPrice.product_id == hidden_product_id))
        with pytest.raises(ApiError) as price_error:
            start_admin_product_sale(session, product_code="prod_inventory_hidden")
        session.rollback()

        inventory = session.execute(
            select(Inventory).where(Inventory.product_id == hidden_product_id)
        ).scalar_one()
        inventory.stock_quantity = 1
        inventory.reserved_quantity = 1
        with pytest.raises(ApiError) as stock_error:
            start_admin_product_sale(session, product_code="prod_inventory_hidden")
        session.rollback()

        brand = session.execute(select(Brand)).scalar_one()
        brand.is_active = False
        with pytest.raises(ApiError) as brand_error:
            start_admin_product_sale(session, product_code="prod_inventory_hidden")
        session.rollback()

        category = session.execute(select(ProductCategory)).scalar_one()
        category.is_active = False
        with pytest.raises(ApiError) as category_error:
            start_admin_product_sale(session, product_code="prod_inventory_hidden")
        session.rollback()

    assert price_error.value.status_code == 409
    assert price_error.value.code == "PRICE_NOT_READY"
    assert stock_error.value.status_code == 409
    assert stock_error.value.code == "INSUFFICIENT_STOCK_FOR_SALE"
    assert brand_error.value.status_code == 409
    assert brand_error.value.code == "BRAND_INACTIVE"
    assert category_error.value.status_code == 409
    assert category_error.value.code == "CATEGORY_INACTIVE"


def test_sale_start_route_always_reindexes_after_commit(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as_admin(client, db_engine)
    sync_calls: list[tuple[str, str]] = []

    def fake_sync(session: Session, product_code: str, *, event_prefix: str = "admin_product") -> None:
        assert session.in_transaction() is False
        sync_calls.append((product_code, event_prefix))

    monkeypatch.setattr(inventory_price_route, "sync_catalog_product_after_commit", fake_sync)

    started = client.post("/api/admin/inventory/prod_inventory_hidden/sale-start")
    repeated = client.post("/api/admin/inventory/prod_inventory_hidden/sale-start")

    assert started.status_code == 200
    assert started.json()["sales_status"] == "ON_SALE"
    assert started.json()["is_active"] is True
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "PRODUCT_NOT_HIDDEN"
    assert sync_calls == [("prod_inventory_hidden", "admin_inventory")]
