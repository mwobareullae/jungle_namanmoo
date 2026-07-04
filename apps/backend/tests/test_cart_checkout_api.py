from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product, ProductPrice
from app.db.models.commerce import Cart, CartItem, Inventory
from app.db.session import get_db
from app.main import app
from app.services.cart_service import ANONYMOUS_CART_COOKIE_NAME
from app.services.db_seed import seed_database
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


def test_anonymous_cart_add_creates_cookie_and_storage_key_item(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)

    response = client.post(
        "/api/cart/items",
        json={
            "product_id": "prod_001",
            "quantity": 2,
            "source": "ai_recommendation",
            "recommendation_id": "rec_test",
            "recommendation_rank": 1,
        },
    )

    assert response.status_code == 200
    anonymous_cart_id = response.cookies.get(ANONYMOUS_CART_COOKIE_NAME)
    assert anonymous_cart_id

    data = response.json()
    assert data["owner_type"] == "anonymous"
    assert data["total_quantity"] == 2
    assert data["subtotal"] == 39800
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["product_id"] == "prod_001"
    assert item["unit_price_snapshot"] == 19900
    assert item["source"] == "ai_recommendation"
    assert item["recommendation_id"] == "rec_test"
    assert item["product"]["thumbnail_url"].startswith("products/")
    assert not item["product"]["thumbnail_url"].startswith("http")

    with Session(db_engine) as session:
        cart = session.execute(select(Cart)).scalar_one()
        cart_item = session.execute(select(CartItem)).scalar_one()

    assert cart.user_id is None
    assert cart.anonymous_cart_id == anonymous_cart_id
    assert cart_item.quantity == 2


def test_cart_add_same_product_increases_quantity(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)

    first = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    second = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 2})

    assert first.status_code == 200
    assert second.status_code == 200
    data = second.json()
    assert data["total_quantity"] == 3
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 3

    with Session(db_engine) as session:
        assert len(session.execute(select(CartItem)).scalars().all()) == 1


def test_cart_patch_zero_deletes_item(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    item_id = add_response.json()["items"][0]["id"]

    update_response = client.patch(f"/api/cart/items/{item_id}", json={"quantity": 2})
    delete_response = client.patch(f"/api/cart/items/{item_id}", json={"quantity": 0})

    assert update_response.status_code == 200
    assert update_response.json()["items"][0]["quantity"] == 2
    assert delete_response.status_code == 200
    assert delete_response.json()["items"] == []

    with Session(db_engine) as session:
        assert len(session.execute(select(CartItem)).scalars().all()) == 0


def test_cart_rejects_product_without_stock_information(client: TestClient) -> None:
    response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STOCK_UNKNOWN"


def test_checkout_preview_revalidates_price_and_stock(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    add_response = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 3})
    assert add_response.status_code == 200
    _set_primary_price(db_engine, "prod_001", 20900)
    _set_inventory(db_engine, "prod_001", stock_quantity=1)

    preview_response = client.post("/api/checkout/preview")

    assert preview_response.status_code == 200
    data = preview_response.json()
    assert data["subtotal"] == 62700
    assert data["shipping_fee"] == 0
    assert data["total"] == 62700
    assert data["can_checkout"] is False
    warning_codes = {warning["code"] for warning in data["warnings"]}
    assert {"PRICE_CHANGED", "INSUFFICIENT_STOCK"}.issubset(warning_codes)


def test_cart_merge_moves_anonymous_items_into_user_cart(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    anonymous_add = client.post("/api/cart/items", json={"product_id": "prod_001", "quantity": 1})
    assert anonymous_add.status_code == 200
    anonymous_cart_id = anonymous_add.cookies.get(ANONYMOUS_CART_COOKIE_NAME)

    _signup(client, email="cart-merge@example.com", nickname="cartmerge")
    user_add = client.post("/api/cart/items", json={"product_id": "prod_002", "quantity": 1})
    assert user_add.status_code == 200

    merge_response = client.post("/api/cart/merge")

    assert merge_response.status_code == 200
    data = merge_response.json()
    assert data["merged"] is True
    assert {item["product_id"] for item in data["cart"]["items"]} == {"prod_001", "prod_002"}

    with Session(db_engine) as session:
        anonymous_cart = session.execute(
            select(Cart).where(Cart.anonymous_cart_id == anonymous_cart_id)
        ).scalar_one()
        active_user_cart = session.execute(
            select(Cart).where(Cart.user_id.is_not(None), Cart.status == "ACTIVE")
        ).scalar_one()

    assert anonymous_cart.status == "MERGED"
    assert anonymous_cart.merged_into_cart_id == active_user_cart.id


def _signup(client: TestClient, *, email: str, nickname: str) -> None:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "password123",
            "nickname": nickname,
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    assert response.status_code == 200


def _set_inventory(
    db_engine: Engine,
    product_code: str,
    *,
    stock_quantity: int,
    reserved_quantity: int = 0,
    safety_stock: int = 0,
    sales_status: str = "ON_SALE",
) -> None:
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == product_code)
        ).scalar_one()
        inventory = session.execute(
            select(Inventory).where(Inventory.product_id == product.id)
        ).scalar_one_or_none()
        if inventory is None:
            inventory = Inventory(
                product_id=product.id,
                stock_quantity=stock_quantity,
                reserved_quantity=reserved_quantity,
                safety_stock=safety_stock,
                sales_status=sales_status,
                inventory_source="TEST",
            )
            session.add(inventory)
        else:
            inventory.stock_quantity = stock_quantity
            inventory.reserved_quantity = reserved_quantity
            inventory.safety_stock = safety_stock
            inventory.sales_status = sales_status
        session.commit()


def _set_primary_price(db_engine: Engine, product_code: str, price: int) -> None:
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == product_code)
        ).scalar_one()
        price_row = session.execute(
            select(ProductPrice)
            .where(ProductPrice.product_id == product.id)
            .order_by(ProductPrice.is_lowest.desc(), ProductPrice.price.asc(), ProductPrice.id.asc())
        ).scalars().first()
        assert price_row is not None
        price_row.price = price
        price_row.is_lowest = True
        session.commit()
