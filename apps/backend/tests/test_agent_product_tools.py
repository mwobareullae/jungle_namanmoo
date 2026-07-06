from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory
from app.schemas.common import ApiError
from app.services.agent_product_tools import (
    compare_products,
    find_similar_products,
    refine_product_results,
)
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


def test_find_similar_products_returns_ranked_product_items(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = find_similar_products(session, product_id="prod_001", conversation_id="conv_products")

    assert response.conversation_id == "conv_products"
    assert response.tool_name == "find_similar_products"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "similar_products"
    assert response.ui_action.payload["source_product_id"] == "prod_001"
    assert [item.id for item in response.items] == ["prod_002"]
    assert response.items[0].item_type == "product"
    assert response.items[0].image_storage_key == "products/prod_002/thumbnail.jpg"
    assert response.items[0].metadata["similarity_score"] > 0
    assert "similar_price" in response.items[0].metadata["match_reasons"]


def test_find_similar_products_excludes_unpurchasable_candidates(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10, sales_status="SOLD_OUT")

    with Session(db_engine) as session:
        response = find_similar_products(session, product_id="prod_001")

    assert response.items == []
    assert response.ui_action.payload["products"] == []


def test_compare_products_returns_comparison_payload(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = compare_products(
            session,
            product_ids=["prod_001", "prod_002"],
            conversation_id="conv_compare",
        )

    assert response.conversation_id == "conv_compare"
    assert response.tool_name == "compare_products"
    assert response.ui_action.type == "show_product_comparison"
    assert response.ui_action.target == "product_comparison"
    payload = response.ui_action.payload
    assert payload["layout_hint"] == "bottom_panel"
    assert [product["product_id"] for product in payload["products"]] == ["prod_001", "prod_002"]
    assert payload["products"][0]["thumbnail_storage_key"] == "products/prod_001/thumbnail.jpg"
    assert payload["products"][0]["price"] == 19900
    assert payload["products"][0]["stock_status"] == "IN_STOCK"
    assert payload["products"][0]["key_ingredients"]
    assert payload["products"][0]["effects"]
    assert payload["highlights"]["cheapest_product_id"] == "prod_001"
    assert response.items[0].id == "prod_001"
    assert response.items[1].id == "prod_002"


def test_compare_products_rejects_more_than_policy_limit(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            compare_products(
                session,
                product_ids=["p1", "p2", "p3", "p4", "p5", "p6"],
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_RESULT_LIMIT_EXCEEDED"


def test_refine_product_results_applies_price_and_skin_filters(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        response = refine_product_results(
            session,
            base_product_ids=["prod_001", "prod_002"],
            max_price=20_000,
            skin_type="dry",
            conversation_id="conv_refine",
        )

    assert response.conversation_id == "conv_refine"
    assert response.tool_name == "refine_product_results"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "refined_products"
    assert [item.id for item in response.items] == ["prod_001"]
    assert response.ui_action.payload["filters"]["max_price"] == 20_000
    assert response.ui_action.payload["products"][0]["product_id"] == "prod_001"


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
        product = session.execute(select(Product).where(Product.product_code == product_code)).scalar_one()
        inventory = session.execute(select(Inventory).where(Inventory.product_id == product.id)).scalar_one_or_none()
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
