from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product, ProductIngredient
from app.db.models.commerce import Inventory
from app.db.models.recommendation import RecommendationResult, RecommendationRun
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
    assert response.message == "비슷한 상품 1개를 찾았어요."
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
    assert response.message == "선택한 상품 2개를 비교했어요."
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
            skin_type="건성",
            conversation_id="conv_refine",
        )

    assert response.conversation_id == "conv_refine"
    assert response.tool_name == "refine_product_results"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "refined_products"
    assert response.message == "조건에 맞는 상품 1개로 추천 결과를 다시 정리했어요."
    assert [item.id for item in response.items] == ["prod_001"]
    assert response.ui_action.payload["filters"]["max_price"] == 20_000
    assert response.ui_action.payload["products"][0]["product_id"] == "prod_001"


def test_refine_product_results_applies_required_ingredient_filter(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        ingredient_name = session.execute(
            select(ProductIngredient.ingredient_name)
            .join(Product, Product.id == ProductIngredient.product_id)
            .where(Product.product_code == "prod_001")
            .limit(1)
        ).scalar_one()
        response = refine_product_results(
            session,
            base_product_ids=["prod_001", "prod_002"],
            required_ingredient_names=[ingredient_name],
        )

    assert [item.id for item in response.items] == ["prod_001"]
    assert response.ui_action.payload["filters"]["required_ingredient_names"] == [ingredient_name]


def test_refine_product_results_filters_full_saved_recommendation_and_preserves_rank(
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    with Session(db_engine) as session:
        products = session.execute(
            select(Product).where(Product.product_code.in_(["prod_001", "prod_002"]))
        ).scalars().all()
        product_ids = {product.product_code: product.id for product in products}
        run = RecommendationRun(
            recommendation_code="rec_agent_refine_full",
            concern_text="보습과 진정 상품 추천",
            skin_type="복합성",
            sensitivity="보통",
            avoid_ingredients=[],
            scoring_version="test",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(run)
        session.flush()
        session.add_all([
            RecommendationResult(
                recommendation_run_id=run.id,
                product_id=product_ids["prod_001"],
                rank_order=1,
                total_score=Decimal("91.00"),
                reason_summary="첫 번째 추천",
                score_breakdown={},
            ),
            RecommendationResult(
                recommendation_run_id=run.id,
                product_id=product_ids["prod_002"],
                rank_order=2,
                total_score=Decimal("87.00"),
                reason_summary="두 번째 추천",
                score_breakdown={},
            ),
        ])
        session.commit()

        response = refine_product_results(
            session,
            recommendation_id=run.recommendation_code,
            base_product_ids=["prod_001"],
            min_price=20_000,
            limit=1,
            conversation_id="conv_refine_full",
        )
        second_page_response = refine_product_results(
            session,
            recommendation_id=run.recommendation_code,
            limit=1,
            page=2,
        )

    assert response.message == "전체 추천 결과에서 조건에 맞는 상품 1개를 다시 정리했어요."
    assert [item.id for item in response.items] == ["prod_002"]
    assert response.items[0].metadata["rank"] == 2
    assert response.items[0].metadata["total_score"] == 87
    assert response.ui_action.payload["recommendation_id"] == "rec_agent_refine_full"
    assert response.ui_action.payload["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 1,
        "total_pages": 1,
        "has_next": False,
        "has_prev": False,
    }
    assert response.ui_action.payload["products"][0]["rank"] == 2
    assert response.ui_action.payload["products"][0]["total_score"] == 87
    assert "refine_min_price=20000" in response.ui_action.payload["result_url"]
    assert [item.id for item in second_page_response.items] == ["prod_002"]
    assert second_page_response.ui_action.payload["pagination"]["page"] == 2
    assert second_page_response.ui_action.payload["pagination"]["total_pages"] == 2
    assert second_page_response.ui_action.payload["pagination"]["has_prev"] is True


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
