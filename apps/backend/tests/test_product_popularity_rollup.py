from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Order, OrderItem, ProductPopularityMetric, Seller
from app.db.models.events import EventLog
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from app.services.popularity_score import POPULARITY_SCORE_VERSION, calculate_product_popularity_score
from app.services.product_popularity_rollup import rollup_product_popularity_metrics
from tests.test_data_loader import EXAMPLES_DIR


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session, EXAMPLES_DIR)
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


def test_calculate_product_popularity_score_uses_counts_and_capped_rates() -> None:
    score = calculate_product_popularity_score(
        view_count=100,
        wishlist_add_count=12,
        cart_add_count=8,
        checkout_start_count=5,
        paid_order_count=2,
        home_product_impression_count=1000,
        home_product_click_count=60,
        search_result_impression_count=500,
        search_result_click_count=40,
    )

    assert score > calculate_product_popularity_score(view_count=100)
    assert calculate_product_popularity_score(view_count=1, cart_add_count=999) < 100


def test_rollup_product_popularity_metrics_from_behavior_events(db_engine: Engine) -> None:
    computed_at = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        product = session.execute(select(Product).where(Product.product_code == "prod_001")).scalar_one()
        seller = session.execute(select(Seller).order_by(Seller.id)).scalars().first()
        assert seller is not None
        product_db_id = int(product.id)
        product_name = product.product_name
        seller_db_id = int(seller.id)
        seller_name = seller.display_name
        session.add(
            ProductPopularityMetric(
                product_id=product_db_id,
                window_days=7,
                view_count=999,
                popularity_score=999,
                score_version="seed_popular_v1",
            )
        )
        order = Order(
            order_code="ord_rollup_001",
            user_id=1,
            idempotency_key="rollup-order",
            status="PAID",
            subtotal_amount=20000,
            shipping_fee=3000,
            discount_amount=0,
            total_amount=23000,
            currency="KRW",
            item_count=1,
            total_quantity=2,
            ordered_at=computed_at,
            paid_at=computed_at,
            created_at=computed_at,
            updated_at=computed_at,
        )
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product_db_id,
                seller_id=seller_db_id,
                product_name_snapshot=product_name,
                brand_name_snapshot="brand",
                seller_name_snapshot=seller_name,
                unit_price=10000,
                quantity=2,
                line_subtotal=20000,
                line_discount_amount=0,
                line_total=20000,
                currency="KRW",
                status="ORDERED",
                created_at=computed_at,
                updated_at=computed_at,
            )
        )
        session.add_all(
            [
                _event("view_1", "product_viewed", computed_at, product_id="prod_001"),
                _event("view_2", "product_viewed", computed_at, product_id="prod_001"),
                _event("home_imp_1", "home_product_impression", computed_at, product_id="prod_001"),
                _event("home_imp_2", "home_product_impression", computed_at, product_id="prod_001"),
                _event("home_click_1", "home_product_click", computed_at, product_id="prod_001"),
                _event("search_imp_1", "search_result_impression", computed_at, product_id="prod_001"),
                _event("search_click_1", "search_result_click", computed_at, product_id="prod_001"),
                _event("wishlist_1", "wishlist_added", computed_at, product_id="prod_001"),
                _event("cart_1", "cart_added", computed_at, product_id="prod_001"),
                _event(
                    "checkout_1",
                    "checkout_started",
                    computed_at,
                    metadata_json={"product_ids": ["prod_001"]},
                ),
                _event("paid_1", "order_completed", computed_at, order_id=order.id),
                _event("old_view", "product_viewed", computed_at - timedelta(days=8), product_id="prod_001"),
            ]
        )

        result = rollup_product_popularity_metrics(session, window_days=7, computed_at=computed_at)
        session.commit()

    assert result.touched_products == 1
    with Session(db_engine) as session:
        metric = session.execute(
            select(ProductPopularityMetric).where(ProductPopularityMetric.product_id == product_db_id)
        ).scalar_one()

    assert metric.score_version == POPULARITY_SCORE_VERSION
    assert metric.view_count == 2
    assert metric.home_product_impression_count == 2
    assert metric.home_product_click_count == 1
    assert metric.search_result_impression_count == 1
    assert metric.search_result_click_count == 1
    assert metric.wishlist_add_count == 1
    assert metric.cart_add_count == 1
    assert metric.checkout_start_count == 1
    assert metric.paid_order_count == 1
    assert metric.order_count == 1
    assert metric.units_sold == 2
    assert float(metric.popularity_score) > 0


def test_event_api_rollup_updates_popular_products_response(client: TestClient, db_engine: Engine) -> None:
    computed_at = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    with Session(db_engine) as session:
        session.execute(delete(ProductPopularityMetric))
        session.commit()

    response = client.post(
        "/api/events/batch",
        json={
            "events": [
                _event_payload("prod1_view_1", "product_viewed", "prod_001", computed_at),
                _event_payload("prod1_view_2", "product_viewed", "prod_001", computed_at),
                _event_payload("prod1_home_imp", "home_product_impression", "prod_001", computed_at),
                _event_payload("prod1_home_click", "home_product_click", "prod_001", computed_at),
                _event_payload("prod1_search_imp", "search_result_impression", "prod_001", computed_at),
                _event_payload("prod1_search_click", "search_result_click", "prod_001", computed_at),
                _event_payload("prod1_wishlist", "wishlist_added", "prod_001", computed_at),
                _event_payload("prod1_cart", "cart_added", "prod_001", computed_at),
                _event_payload("prod2_view", "product_viewed", "prod_002", computed_at),
            ]
        },
        headers={
            "x-mwbl-anonymous-user-id": "anon-popular-e2e",
            "x-mwbl-session-id": "session-popular-e2e",
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted_count"] == 9

    with Session(db_engine) as session:
        result = rollup_product_popularity_metrics(session, window_days=7, computed_at=computed_at)
        session.commit()

    assert result.touched_products == 2

    popular_response = client.get("/api/products/popular", params={"window_days": 7, "limit": 2})

    assert popular_response.status_code == 200
    items = popular_response.json()["items"]
    assert [item["product_id"] for item in items] == ["prod_001", "prod_002"]
    first_metrics = items[0]["metrics"]
    assert items[0]["score_version"] == POPULARITY_SCORE_VERSION
    assert first_metrics["view_count"] == 2
    assert first_metrics["home_product_impression_count"] == 1
    assert first_metrics["home_product_click_count"] == 1
    assert first_metrics["search_result_impression_count"] == 1
    assert first_metrics["search_result_click_count"] == 1
    assert first_metrics["wishlist_add_count"] == 1
    assert first_metrics["cart_add_count"] == 1


def _event(
    event_id: str,
    event_name: str,
    occurred_at: datetime,
    *,
    product_id: str | None = None,
    order_id: int | None = None,
    metadata_json: dict | None = None,
) -> EventLog:
    return EventLog(
        event_id=event_id,
        event_name=event_name,
        occurred_at=occurred_at,
        product_id=product_id,
        order_id=order_id,
        metadata_json=metadata_json or {},
        created_at=occurred_at,
    )


def _event_payload(event_id: str, event_name: str, product_id: str, occurred_at: datetime) -> dict:
    return {
        "event_id": event_id,
        "event_name": event_name,
        "product_id": product_id,
        "occurred_at": occurred_at.isoformat(),
        "page": "home" if event_name.startswith("home_") else "search",
        "source": "market_popular" if event_name.startswith("home_") else "search_result",
        "metadata": {
            "section_id": "market_popular" if event_name.startswith("home_") else "search_results",
        },
    }
