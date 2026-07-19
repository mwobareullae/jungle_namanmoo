"""M5 운영 대시보드 단일 집계 API focused 테스트."""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Brand, Product, ProductCategory, ProductImage
from app.db.models.commerce import Inventory, Order, OrderClaim, Seller
from app.db.session import get_db
from app.main import app
from app.schemas.admin.ingredient_mapping import IngredientMappingSummary
from app.services.admin import dashboard_service


ADMIN_EMAIL = "admin-dashboard@example.com"


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_catalog(session)
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


def _seed_catalog(session: Session) -> None:
    seller = Seller(seller_code="mwobareullae", display_name="뭐바를래")
    brand = Brand(brand_code="brand_dashboard", name="대시보드 브랜드", normalized_name="dashboardbrand")
    category = ProductCategory(category_code="dashboard_serum", name="대시보드 세럼")
    session.add_all([seller, brand, category])
    session.flush()

    def product(code: str, *, recommendable: bool, inventory: tuple[int, int, int, str] | None) -> Product:
        row = Product(
            product_code=code,
            seller_id=seller.id,
            brand_id=brand.id,
            category_id=category.id,
            product_name=code,
            is_recommendable=recommendable,
        )
        session.add(row)
        session.flush()
        if inventory is not None:
            stock, reserved, safety, sales_status = inventory
            session.add(
                Inventory(
                    product_id=row.id,
                    stock_quantity=stock,
                    reserved_quantity=reserved,
                    safety_stock=safety,
                    sales_status=sales_status,
                )
            )
        return row

    in_stock = product("prod_dashboard_in", recommendable=True, inventory=(10, 0, 0, "ON_SALE"))
    product("prod_dashboard_low", recommendable=False, inventory=(7, 1, 1, "ON_SALE"))
    product("prod_dashboard_sold", recommendable=False, inventory=(1, 1, 0, "SOLD_OUT"))
    product("prod_dashboard_hidden", recommendable=False, inventory=(10, 0, 0, "HIDDEN"))
    product("prod_dashboard_unknown", recommendable=True, inventory=None)
    session.add(
        ProductImage(
            product_id=in_stock.id,
            image_type="thumbnail",
            display_order=0,
            storage_key="products/prod_dashboard_in/thumbnail.jpg",
        )
    )


def _as_admin(client: TestClient, db_engine: Engine) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": ADMIN_EMAIL,
            "password": "password123",
            "nickname": "admin-dashboard",
            "consents": {"tos": True, "privacy": True, "age14": True, "marketing": False},
        },
    )
    assert response.status_code == 200
    with Session(db_engine) as session:
        user = session.execute(select(User).where(User.email == ADMIN_EMAIL)).scalar_one()
        user.role = "ADMIN"
        _seed_orders(session, user_id=user.id)
        session.commit()


def _seed_orders(session: Session, *, user_id: int) -> None:
    now = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    for code, status, quantity in (
        ("ord_dashboard_pending", "PENDING_PAYMENT", 3),
        ("ord_dashboard_prepare", "PREPARING_SHIPMENT", 1),
        ("ord_dashboard_cancel", "CANCEL_REQUESTED", 1),
    ):
        session.add(
            Order(
                order_code=code,
                user_id=user_id,
                idempotency_key=f"key_{code}",
                status=status,
                subtotal_amount=1_000,
                total_amount=1_000,
                item_count=1,
                total_quantity=quantity,
                ordered_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()

    claim_order = session.execute(
        select(Order).where(Order.order_code == "ord_dashboard_prepare")
    ).scalar_one()
    session.add_all(
        [
            OrderClaim(
                claim_code="claim_dashboard_requested",
                order_id=claim_order.id,
                user_id=user_id,
                claim_type="RETURN",
                status="REQUESTED",
                reason_code="CHANGE_OF_MIND",
            ),
            OrderClaim(
                claim_code="claim_dashboard_completed",
                order_id=claim_order.id,
                user_id=user_id,
                claim_type="EXCHANGE",
                status="COMPLETED",
                reason_code="DEFECTIVE",
            ),
        ]
    )


def _summary() -> IngredientMappingSummary:
    return IngredientMappingSummary(
        pending_count=3,
        held_count=2,
        needs_review_count=1,
        unclassified_count=6,
        approved_count=4,
        rejected_count=5,
    )


def test_dashboard_summary_requires_admin(client: TestClient) -> None:
    assert client.get("/api/admin/dashboard/summary").status_code == 401


def test_dashboard_summary_returns_existing_summary_contract(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard_service, "get_ingredient_mapping_summary", lambda _session: _summary())
    _as_admin(client, db_engine)

    response = client.get("/api/admin/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "order_summary": {
            "pending_payment_count": 1,
            "preparing_shipment_count": 1,
            "cancel_requested_count": 1,
            "reserved_quantity_total": 3,
        },
        "ingredient_review_summary": {
            "pending_count": 3,
            "held_count": 2,
            "needs_review_count": 1,
            "unclassified_count": 6,
            "approved_count": 4,
            "rejected_count": 5,
        },
        "product_stats": {
            "total_count": 5,
            "recommendable_count": 2,
            "image_missing_count": 4,
        },
        "stock_status_breakdown": {
            "in_stock_count": 1,
            "low_stock_count": 1,
            "sold_out_count": 1,
            "hidden_count": 1,
            "unknown_count": 1,
        },
        "claim_summary": {
            "pending_count": 1,
        },
    }


def test_dashboard_summary_keeps_zero_counts(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dashboard_service,
        "get_ingredient_mapping_summary",
        lambda _session: IngredientMappingSummary(
            pending_count=0,
            held_count=0,
            needs_review_count=0,
            unclassified_count=0,
            approved_count=0,
            rejected_count=0,
        ),
    )
    _as_admin(client, db_engine)

    response = client.get("/api/admin/dashboard/summary")

    assert response.status_code == 200
    assert response.json()["ingredient_review_summary"]["pending_count"] == 0
