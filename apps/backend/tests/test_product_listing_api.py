from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, ProductPopularityMetric
from app.db.models.review import ProductReviewMetric
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


@pytest.fixture()
def db_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session, EXAMPLES_DIR)
        first, second = session.execute(
            select(Product).order_by(Product.product_code.asc())
        ).scalars().all()
        first.released_at = datetime(2026, 7, 1, tzinfo=UTC)
        second.released_at = datetime(2026, 7, 10, tzinfo=UTC)
        session.add_all(
            [
                ProductPopularityMetric(product_id=first.id, window_days=7, popularity_score=30),
                ProductPopularityMetric(product_id=second.id, window_days=7, popularity_score=80),
                ProductReviewMetric(product_id=first.id, review_count=10, rating_count=10, average_rating=4.9),
                ProductReviewMetric(product_id=second.id, review_count=20, rating_count=20, average_rating=4.6),
                Inventory(
                    product_id=first.id,
                    stock_quantity=10,
                    reserved_quantity=0,
                    safety_stock=0,
                    sales_status="ON_SALE",
                ),
                Inventory(
                    product_id=second.id,
                    stock_quantity=0,
                    reserved_quantity=0,
                    safety_stock=0,
                    sales_status="SOLD_OUT",
                ),
            ]
        )
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine) -> TestClient:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_products_supports_listing_filters_and_pagination(client: TestClient) -> None:
    response = client.get(
        "/api/products",
        params=[
            ("category_group", "skincare"),
            ("min_price", "20000"),
            ("sort", "price_low"),
            ("page", "1"),
            ("page_size", "20"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["product_id"] for item in payload["items"]] == ["prod_002"]
    assert payload["items"][0]["lowest_price"] == 22900
    assert payload["items"][0]["category_name"] == "세럼"
    assert payload["items"][0]["in_stock"] is False
    assert payload["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total_items": 1,
        "total_pages": 1,
        "has_next": False,
        "has_prev": False,
    }
    assert payload["applied_filters"]["category_groups"] == ["skincare"]


def test_list_products_uses_release_date_for_newest_sort(client: TestClient) -> None:
    response = client.get("/api/products", params={"sort": "newest", "page_size": 20})

    assert response.status_code == 200
    payload = response.json()
    # Purchaseable products remain ahead of sold-out products across listing sorts.
    assert [item["product_id"] for item in payload["items"]] == ["prod_001", "prod_002"]
    assert payload["items"][1]["released_at"].startswith("2026-07-10T")


def test_list_products_rejects_invalid_price_range(client: TestClient) -> None:
    response = client.get("/api/products", params={"min_price": 30000, "max_price": 10000})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PRODUCT_FILTER"


def test_list_categories_and_brands_expose_listing_metadata(client: TestClient) -> None:
    categories = client.get("/api/categories")
    brands = client.get("/api/brands", params={"q": "라운"})

    assert categories.status_code == 200
    category_by_code = {item["code"]: item for item in categories.json()["items"]}
    assert category_by_code["cream"] == {
        "code": "cream",
        "name": "크림",
        "group": "skincare",
        "group_name": "스킨케어",
        "product_count": 1,
    }
    assert brands.status_code == 200
    assert brands.json()["items"] == [{"code": "라운드랩", "name": "라운드랩", "product_count": 1}]
