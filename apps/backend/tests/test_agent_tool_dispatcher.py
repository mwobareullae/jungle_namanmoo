from collections.abc import Generator
from datetime import UTC, datetime
import json
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.agent import AgentToolCall
from app.db.models.auth import User
from app.db.models.catalog import Product, ProductCategory, ProductIngredient, ProductPrice, ProductSkinProfile
from app.db.models.commerce import Inventory, Order, OrderClaim, OrderItem, ProductPopularityMetric, UserAddress, Wishlist
from app.db.models.events import EventLog
from app.db.models.taxonomy import Ingredient, IngredientAlias
from app.schemas.common import ApiError
from app.schemas.agent import AgentContextResultItem, AgentLastToolResult
from app.services.agent_openai_runner import CommerceAgentContext, _execute_tool
from app.services.agent_order_tools import confirm_agent_tool_call
from app.services.agent_commerce_tools import add_agent_cart_item
from app.services.cart_service import get_cart_response
from app.services.user_activity_service import add_wishlist_item, upsert_recent_view
from app.services.agent_policy import AGENT_TOOL_POLICIES
from app.services.agent_tool_dispatcher import execute_agent_tool, list_agent_tool_names
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR
from tests.test_review_api import _create_order_item


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


def test_dispatcher_lists_registered_agent_tools() -> None:
    assert set(list_agent_tool_names()) == set(AGENT_TOOL_POLICIES)


def test_dispatcher_executes_product_tool_and_records_tool_call(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)

    logs = _capture_performance_logs()
    with Session(db_engine) as session:
        try:
            response = execute_agent_tool(
                session,
                tool_name="find_similar_products",
                arguments={"product_id": "prod_001", "limit": 2},
                conversation_id="conv_dispatch",
                request_id="req_dispatch",
                session_id="sess_dispatch",
                anonymous_user_id="anon_dispatch",
            )
            session.commit()
        finally:
            logs.close()

    assert response.tool_name == "find_similar_products"
    assert response.conversation_id == "conv_dispatch"
    assert [item.id for item in response.items] == ["prod_002"]

    with Session(db_engine) as session:
        tool_call = session.execute(
            select(AgentToolCall).where(AgentToolCall.request_id == "req_dispatch")
        ).scalar_one()

    assert tool_call.tool_name == "find_similar_products"
    assert tool_call.status == "EXECUTED"
    assert tool_call.confirmation_required is False
    assert tool_call.input_json == {"product_id": "prod_001", "limit": 2, "min_price": None, "max_price": None}
    assert tool_call.output_json["tool_name"] == "find_similar_products"
    assert tool_call.output_json["items"][0]["id"] == "prod_002"
    assert tool_call.executed_at is not None
    assert tool_call.latency_ms is not None
    performance_payload = next(
        line for line in logs.json_lines if line["event"] == "agent_tool_completed"
    )
    assert performance_payload["request_id"] == "req_dispatch"
    assert performance_payload["tool_name"] == "find_similar_products"
    assert performance_payload["status"] == "EXECUTED"
    assert performance_payload["item_count"] == 1


def test_dispatcher_creates_real_recommendation_result(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.recommendation_intent.parse_concern_text",
        lambda *_args, **_kwargs: pytest.fail("agent path must not run raw intent parser"),
    )
    monkeypatch.setattr(
        "app.services.recommendation_pipeline.settings.openai_api_key",
        "test-openai-key",
    )
    monkeypatch.setattr(
        "app.services.recommendation_pipeline.get_default_concern_llm_parser",
        lambda: pytest.fail("agent path must not construct backend LLM parser"),
    )
    with Session(db_engine) as session:
        response = execute_agent_tool(
            session,
            tool_name="create_recommendation",
            arguments={
                "concern_text": "민감 피부용 보습 세럼 5만원 이하로 추천해줘",
                "skin_type": "복합성",
                "sensitivity": "높음",
                "avoid_ingredients": [],
                "page_size": 10,
                "concern_ids": ["concern_sensitive"],
                "effect_ids": ["effect_calming", "effect_moisture_barrier"],
                "priority_effect_ids": ["effect_calming"],
                "category_codes": ["serum"],
                "price_max": 50_000,
            },
            conversation_id="conv_recommendation",
        )

    assert response.tool_name == "create_recommendation"
    assert response.ui_action.type == "show_products"
    assert response.ui_action.target == "product_results"
    assert response.ui_action.payload["recommendation_id"].startswith("rec_")
    assert response.ui_action.payload["result_url"].startswith("/search?")
    assert "recommendation_id=" in response.ui_action.payload["result_url"]
    assert response.ui_action.payload["products"]
    assert response.ui_action.payload["summary"]["matched_concerns"] == ["민감"]
    assert response.ui_action.payload["summary"]["purchase_constraints"]["categories"][0][
        "category_code"
    ] == "serum"
    assert response.ui_action.payload["summary"]["purchase_constraints"]["price_max"] == 50_000
    assert response.items[0].metadata["rank"] == 1


def test_dispatcher_rejects_invalid_structured_recommendation_price_range(
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="create_recommendation",
                arguments={
                    "concern_text": "세럼 추천",
                    "category_codes": ["serum"],
                    "price_min": 50_000,
                    "price_max": 30_000,
                },
            )

    assert exc_info.value.code == "AGENT_TOOL_ARGUMENT_INVALID"


def test_dispatcher_rejects_removed_intent_resolved_argument(
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="create_recommendation",
                arguments={
                    "concern_text": "세럼 추천",
                    "intent_resolved": True,
                    "category_codes": ["serum"],
                },
            )

    assert exc_info.value.code == "AGENT_TOOL_ARGUMENT_INVALID"


def test_dispatcher_rejects_unknown_tool(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(session, tool_name="not_a_tool", arguments={})

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "UNKNOWN_AGENT_TOOL"


def test_dispatcher_rejects_invalid_arguments(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="compare_products",
                arguments={"product_ids": ["prod_001"]},
                conversation_id="conv_invalid_args",
                request_id="req_invalid_args",
                session_id="sess_invalid_args",
            )

        recorded = session.execute(
            select(AgentToolCall).where(AgentToolCall.request_id == "req_invalid_args")
        ).scalar_one()

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "AGENT_TOOL_ARGUMENT_INVALID"
    assert recorded.status == "FAILED"
    assert recorded.error_code == "AGENT_TOOL_ARGUMENT_INVALID"
    assert recorded.conversation_id == "conv_invalid_args"
    assert recorded.session_id == "sess_invalid_args"
    assert recorded.input_json == {"product_ids": ["prod_001"]}


def test_dispatcher_rejects_auth_required_tool_without_user(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="order_status_lookup",
                arguments={},
                conversation_id="conv_auth_rejected",
                request_id="req_auth_rejected",
                session_id="sess_auth_rejected",
            )

        recorded = session.execute(
            select(AgentToolCall).where(AgentToolCall.request_id == "req_auth_rejected")
        ).scalar_one()

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "AGENT_AUTH_REQUIRED"
    assert recorded.status == "REJECTED"
    assert recorded.error_code == "AGENT_AUTH_REQUIRED"
    assert recorded.conversation_id == "conv_auth_rejected"
    assert recorded.session_id == "sess_auth_rejected"


def test_dispatcher_builds_order_history_filter_navigation(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = User(email="agent-order-history@example.com", display_name="order-history")
        session.add(user)
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="filter_order_history",
            arguments={"period_months": 12, "status": "DELIVERED"},
            user=user,
            conversation_id="conv_order_history",
        )

    assert response.tool_name == "filter_order_history"
    assert response.ui_action.type == "navigate"
    assert response.ui_action.target == "order_history"
    assert response.ui_action.payload == {"period_months": 12, "status": "DELIVERED"}
    assert response.requires_confirmation is False


def test_prepare_review_draft_uses_reviewable_purchase_without_creating_review(db_engine: Engine) -> None:
    email = "agent-review@example.com"
    with Session(db_engine) as session:
        session.add(User(email=email, display_name="agent-review"))
        session.commit()
    order_item_id = _create_order_item(db_engine, email=email, item_status="DELIVERED")

    with Session(db_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        response = execute_agent_tool(
            session,
            tool_name="prepare_review_draft",
            arguments={
                "rating": 4,
                "review_text": "보습감은 좋았지만 마무리가 조금 끈적였어요.",
            },
            user=user,
            conversation_id="conv_review",
        )

    assert response.ui_action.type == "navigate"
    assert response.ui_action.target == "review_write"
    assert response.ui_action.payload["order_item_id"] == order_item_id
    assert response.ui_action.payload["rating"] == 4
    assert response.ui_action.payload["review_text"] == "보습감은 좋았지만 마무리가 조금 끈적였어요."


def test_prepare_claim_draft_checks_real_eligibility_without_creating_claim(db_engine: Engine) -> None:
    email = "agent-claim@example.com"
    with Session(db_engine) as session:
        session.add(User(email=email, display_name="agent-claim"))
        session.commit()
    order_item_id = _create_order_item(db_engine, email=email, item_status="DELIVERED")

    with Session(db_engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        order_code = session.scalar(
            select(Order.order_code).join(OrderItem, OrderItem.order_id == Order.id).where(OrderItem.id == order_item_id)
        )
        order = session.scalar(select(Order).where(Order.order_code == order_code))
        order.status = "DELIVERED"
        order.delivered_at = datetime.now(UTC)
        session.flush()
        response = execute_agent_tool(
            session,
            tool_name="prepare_claim_draft",
            arguments={
                "order_code": order_code,
                "order_item_id": order_item_id,
                "claim_type": "RETURN",
                "reason_code": "CHANGE_OF_MIND",
                "reason_detail": "향이 저와 맞지 않아요.",
            },
            user=user,
            conversation_id="conv_claim",
        )
        claim_count = len(session.scalars(select(OrderClaim)).all())

    assert claim_count == 0
    assert response.requires_confirmation is False
    assert response.ui_action.type == "navigate"
    assert response.ui_action.target == "claim_request"
    assert response.ui_action.payload == {
        "order_code": order_code,
        "order_item_id": order_item_id,
        "claim_type": "RETURN",
        "reason_code": "CHANGE_OF_MIND",
        "reason_detail": "향이 저와 맞지 않아요.",
    }


def test_compose_cart_requires_confirmation_before_bulk_add(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    with Session(db_engine) as session:
        user = User(email="compose@example.com", display_name="compose-user")
        session.add(user)
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="compose_cart",
            arguments={"categories": ["cream", "serum"], "max_budget": 50_000},
            user=user,
            conversation_id="conv_compose",
            request_id="req_compose",
        )
        session.commit()

        assert response.requires_confirmation is True
        assert response.tool_call_id is not None
        assert [item.id for item in response.items] == ["prod_001", "prod_002"]
        assert sum(item.price or 0 for item in response.items) == 42_800
        assert get_cart_response(session, user, None).items == []

        confirmed = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=response.tool_call_id,
            action="confirm",
        )
        session.commit()
        cart = get_cart_response(session, user, None)

    assert confirmed.status == "EXECUTED"
    assert confirmed.ui_action.type == "show_cart"
    assert {item.product_id for item in cart.items} == {"prod_001", "prod_002"}


def test_bulk_popular_ingredient_wishlist_confirms_real_db_write_and_is_idempotent(db_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        user = User(email="bulk-wishlist@example.com", display_name="bulk-wishlist-user")
        products = session.scalars(select(Product).order_by(Product.product_code.asc()).limit(2)).all()
        assert len(products) == 2
        ingredient_id = session.scalar(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == products[0].id).limit(1)
        )
        assert ingredient_id is not None
        ingredient = session.get(Ingredient, ingredient_id)
        assert ingredient is not None
        session.add(user)
        for rank, product in enumerate(products, start=1):
            session.add(ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=100 - rank,
                order_count=20 - rank,
                units_sold=20 - rank,
                score_version="behavior_rollup_v1",
                computed_at=now,
            ))
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": ingredient.name_ko, "rank_limit": 20, "window_days": 7},
            user=user,
            conversation_id="conv_bulk_wishlist",
            request_id="req_bulk_wishlist",
        )
        session.commit()

        assert response.requires_confirmation is True
        assert response.tool_call_id is not None
        assert response.ui_action.target == "agent_confirmation"
        assert session.scalar(select(Wishlist).where(Wishlist.user_id == user.id)) is None
        matched_ids = response.ui_action.payload["matched_product_ids"]
        assert matched_ids
        assert [item.metadata["rank"] for item in response.items] == sorted(item.metadata["rank"] for item in response.items)

        confirmed = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=response.tool_call_id,
            action="confirm",
        )
        session.commit()

        wished_codes = set(session.scalars(
            select(Product.product_code).join(Wishlist, Wishlist.product_id == Product.id).where(Wishlist.user_id == user.id)
        ))
        events = session.scalars(
            select(EventLog).where(EventLog.user_id == user.id, EventLog.event_name == "wishlist_added")
        ).all()
        assert confirmed.status == "EXECUTED"
        assert confirmed.ui_action.target == "popular_wishlist"
        assert wished_codes == set(confirmed.ui_action.payload["added_product_ids"])
        assert {event.product_id for event in events} == wished_codes
        assert {event.source for event in events} == {"agent_bulk_wishlist"}

        repeated = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": ingredient.name_ko, "rank_limit": 20, "window_days": 7},
            user=user,
            conversation_id="conv_bulk_wishlist",
        )
        session.commit()
        assert repeated.requires_confirmation is False
        assert "이미 모두 찜" in repeated.message
        assert len(session.scalars(select(Wishlist).where(Wishlist.user_id == user.id)).all()) == len(wished_codes)


def test_bulk_popular_wishlist_filters_by_skin_profile(db_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        user = User(email="bulk-skin-wishlist@example.com", display_name="bulk-skin-wishlist-user")
        products = session.scalars(select(Product).order_by(Product.product_code.asc()).limit(2)).all()
        assert len(products) == 2
        session.add(user)
        session.execute(delete(ProductSkinProfile).where(ProductSkinProfile.product_id.in_([product.id for product in products])))
        session.add_all(
            [
                ProductSkinProfile(
                    product_id=products[0].id,
                    dry_fit=0.2,
                    oily_fit=0.2,
                    combination_fit=0.3,
                    normal_fit=0.2,
                    dehydrated_oily_fit=0.9,
                    sensitive_fit=0.8,
                ),
                ProductSkinProfile(
                    product_id=products[1].id,
                    dry_fit=0.2,
                    oily_fit=0.2,
                    combination_fit=0.2,
                    normal_fit=0.2,
                    dehydrated_oily_fit=0.4,
                    sensitive_fit=0.4,
                ),
            ]
        )
        for rank, product in enumerate(products, start=1):
            session.add(
                ProductPopularityMetric(
                    product_id=product.id,
                    window_days=7,
                    popularity_score=100 - rank,
                    order_count=20 - rank,
                    units_sold=20 - rank,
                    score_version="behavior_rollup_v1",
                    computed_at=now,
                )
            )
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"skin_type": "수부지", "rank_limit": 20, "window_days": 7},
            user=user,
            conversation_id="conv_bulk_skin_wishlist",
        )

        assert response.requires_confirmation is True
        assert response.ui_action.payload["matched_product_ids"] == [products[0].product_code]
        assert response.ui_action.payload["ingredient_name"] == "수부지 피부"

def test_bulk_popular_ingredient_wishlist_rejection_does_not_write(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = User(email="bulk-reject@example.com", display_name="bulk-reject-user")
        product = session.scalar(select(Product).order_by(Product.product_code.asc()))
        assert product is not None
        ingredient_id = session.scalar(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == product.id).limit(1)
        )
        ingredient = session.get(Ingredient, ingredient_id)
        assert ingredient is not None
        session.add_all([
            user,
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=100,
                score_version="behavior_rollup_v1",
                computed_at=datetime.now(UTC),
            ),
        ])
        session.commit()
        session.refresh(user)

        prepared = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": ingredient.name_ko, "rank_limit": 20, "window_days": 7},
            user=user,
        )
        session.commit()
        rejected = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=prepared.tool_call_id or "",
            action="reject",
        )
        session.commit()

        assert rejected.status == "REJECTED"
        assert session.scalar(select(Wishlist).where(Wishlist.user_id == user.id)) is None
        assert session.scalar(select(EventLog).where(EventLog.user_id == user.id)) is None


def test_bulk_popular_ingredient_wishlist_resolves_alias_without_substring_match(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = User(email="bulk-alias@example.com", display_name="bulk-alias-user")
        product = session.scalar(select(Product).order_by(Product.product_code.asc()))
        assert product is not None
        ingredient_id = session.scalar(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == product.id).limit(1)
        )
        assert ingredient_id is not None
        ingredient = session.get(Ingredient, ingredient_id)
        assert ingredient is not None
        session.add_all([
            user,
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=100,
                score_version="behavior_rollup_v1",
                computed_at=datetime.now(UTC),
            ),
            IngredientAlias(
                ingredient_id=ingredient.id,
                alias="검증용 별칭",
                normalized_alias="검증용별칭",
                alias_type="synonym",
                confidence="high",
                source="test",
            ),
        ])
        session.commit()
        session.refresh(user)

        alias_response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": "검증용 별칭", "rank_limit": 20, "window_days": 7},
            user=user,
        )
        assert alias_response.items[0].id == product.product_code

        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="bulk_wishlist_by_popular_ingredient",
                arguments={"ingredient_name": f"가짜{ingredient.name_ko}성분", "rank_limit": 20, "window_days": 7},
                user=user,
            )
        assert exc_info.value.code == "AGENT_INGREDIENT_NOT_FOUND"


def test_bulk_popular_ingredient_wishlist_does_not_inspect_beyond_rank_limit(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = User(email="bulk-rank@example.com", display_name="bulk-rank-user")
        products = session.scalars(select(Product).order_by(Product.product_code.asc()).limit(2)).all()
        assert len(products) == 2
        first_ingredient_ids = set(session.scalars(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == products[0].id)
        ))
        second_ingredient_ids = set(session.scalars(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == products[1].id)
        ))
        exclusive_ids = second_ingredient_ids - first_ingredient_ids
        assert exclusive_ids
        ingredient = session.get(Ingredient, next(iter(exclusive_ids)))
        assert ingredient is not None
        session.add_all([
            user,
            ProductPopularityMetric(product_id=products[0].id, window_days=7, popularity_score=100, score_version="behavior_rollup_v1", computed_at=datetime.now(UTC)),
            ProductPopularityMetric(product_id=products[1].id, window_days=7, popularity_score=90, score_version="behavior_rollup_v1", computed_at=datetime.now(UTC)),
        ])
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": ingredient.name_ko, "rank_limit": 1, "window_days": 7},
            user=user,
        )

    assert response.requires_confirmation is False
    assert response.ui_action.payload["inspected_count"] == 1
    assert response.ui_action.payload["matched_count"] == 0
    assert "찾지 못했어요" in response.message


def test_bulk_popular_wishlist_combines_rank_ingredients_category_and_price(db_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        user = User(email="bulk-compound@example.com", display_name="bulk-compound-user")
        products = session.scalars(select(Product).order_by(Product.product_code.asc()).limit(2)).all()
        ingredients = session.scalars(select(Ingredient).where(Ingredient.is_active.is_(True)).limit(2)).all()
        assert len(products) == 2
        assert len(ingredients) == 2
        category = session.get(ProductCategory, products[0].category_id)
        assert category is not None

        session.add(user)
        for product in products:
            product.category_id = category.id
        session.execute(delete(ProductPopularityMetric).where(ProductPopularityMetric.window_days == 7))
        session.execute(delete(ProductIngredient).where(ProductIngredient.product_id.in_([product.id for product in products])))
        session.execute(delete(ProductPrice).where(ProductPrice.product_id.in_([product.id for product in products])))
        session.add_all(
            [
                ProductPopularityMetric(product_id=products[0].id, window_days=7, popularity_score=100, score_version="behavior_rollup_v1", computed_at=now),
                ProductPopularityMetric(product_id=products[1].id, window_days=7, popularity_score=90, score_version="behavior_rollup_v1", computed_at=now),
                ProductIngredient(product_id=products[0].id, ingredient_id=ingredients[0].id, ingredient_name=ingredients[0].name_ko),
                ProductIngredient(product_id=products[1].id, ingredient_id=ingredients[0].id, ingredient_name=ingredients[0].name_ko),
                ProductIngredient(product_id=products[1].id, ingredient_id=ingredients[1].id, ingredient_name=ingredients[1].name_ko),
                ProductPrice(product_id=products[0].id, mall_name="test", price=10_000, product_url="/products/first", is_lowest=True),
                ProductPrice(product_id=products[1].id, mall_name="test", price=20_000, product_url="/products/second", is_lowest=True),
            ]
        )
        session.commit()
        session.refresh(user)

        all_response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={
                "ingredient_names": [ingredients[0].name_ko, ingredients[1].name_ko],
                "ingredient_match_mode": "all",
                "category": category.category_code,
                "price_max": 25_000,
                "rank_limit": 50,
                "window_days": 7,
            },
            user=user,
        )

        assert all_response.requires_confirmation is True
        assert [item.id for item in all_response.items] == [products[1].product_code]
        assert all_response.items[0].metadata["rank"] == 2
        assert all_response.ui_action.payload["criteria"] == {
            "ingredient_names": [ingredients[0].name_ko, ingredients[1].name_ko],
            "ingredient_match_mode": "all",
            "category": {"category_code": category.category_code, "name": category.name},
            "price_min": None,
            "price_max": 25_000,
            "skin_type": None,
            "sensitivity": None,
        }

        any_response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={
                "ingredient_names": [ingredients[0].name_ko, ingredients[1].name_ko],
                "ingredient_match_mode": "any",
                "category": category.category_code,
                "price_max": 25_000,
                "rank_limit": 50,
                "window_days": 7,
            },
            user=user,
        )
        assert [item.id for item in any_response.items] == [products[0].product_code, products[1].product_code]

        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="bulk_wishlist_by_popular_ingredient",
                arguments={"ingredient_name": ingredients[0].name_ko, "rank_limit": 51, "window_days": 7},
                user=user,
            )
        assert exc_info.value.code == "AGENT_BULK_WISHLIST_RANK_LIMIT"


def test_bulk_popular_wishlist_resolves_korean_category_and_ingredient_particle(db_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(db_engine) as session:
        user = User(email="bulk-korean-query@example.com", display_name="bulk-korean-query-user")
        product = session.scalar(select(Product).order_by(Product.product_code.asc()))
        ingredient = session.scalar(select(Ingredient).where(Ingredient.is_active.is_(True)))
        category = session.scalar(select(ProductCategory).where(ProductCategory.category_code == "serum"))
        assert product is not None
        assert ingredient is not None
        assert category is not None
        product_code = product.product_code
        ingredient_name = ingredient.name_ko

        product.category_id = category.id
        session.execute(delete(ProductPopularityMetric).where(ProductPopularityMetric.window_days == 7))
        session.execute(delete(ProductIngredient).where(ProductIngredient.product_id == product.id))
        session.add_all(
            [
                user,
                ProductPopularityMetric(
                    product_id=product.id,
                    window_days=7,
                    popularity_score=100,
                    score_version="behavior_rollup_v1",
                    computed_at=now,
                ),
                ProductIngredient(
                    product_id=product.id,
                    ingredient_id=ingredient.id,
                    ingredient_name=ingredient.name_ko,
                ),
            ]
        )
        session.commit()
        session.refresh(user)

        response = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={
                "ingredient_name": f"{ingredient.name_ko}이",
                "category": "세럼",
                "rank_limit": 20,
                "window_days": 7,
            },
            user=user,
        )

    assert response.requires_confirmation is True
    assert [item.id for item in response.items] == [product_code]
    assert response.ui_action.payload["criteria"]["ingredient_names"] == [ingredient_name]
    assert response.ui_action.payload["criteria"]["category"]["category_code"] == "serum"


def test_bulk_popular_ingredient_wishlist_rolls_back_all_items_on_save_failure(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(db_engine) as session:
        user = User(email="bulk-rollback@example.com", display_name="bulk-rollback-user")
        product = session.scalar(select(Product).order_by(Product.product_code.asc()))
        assert product is not None
        ingredient_id = session.scalar(
            select(ProductIngredient.ingredient_id).where(ProductIngredient.product_id == product.id).limit(1)
        )
        ingredient = session.get(Ingredient, ingredient_id)
        assert ingredient is not None
        session.add_all([
            user,
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                popularity_score=100,
                score_version="behavior_rollup_v1",
                computed_at=datetime.now(UTC),
            ),
        ])
        session.commit()
        session.refresh(user)
        prepared = execute_agent_tool(
            session,
            tool_name="bulk_wishlist_by_popular_ingredient",
            arguments={"ingredient_name": ingredient.name_ko, "rank_limit": 20, "window_days": 7},
            user=user,
        )
        session.commit()

        def fail_event_write(*args, **kwargs):
            raise SQLAlchemyError("forced event failure")

        monkeypatch.setattr("app.services.agent_bulk_wishlist.create_event_logs", fail_event_write)
        failed = confirm_agent_tool_call(
            session,
            user,
            tool_call_id=prepared.tool_call_id or "",
            action="confirm",
        )
        session.commit()

        assert failed.status == "FAILED"
        assert session.scalar(select(Wishlist).where(Wishlist.user_id == user.id)) is None
        assert session.scalar(select(EventLog).where(EventLog.user_id == user.id)) is None


def test_register_shipping_address_resumes_checkout_without_logging_pii(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    raw_phone = "010-9876-5432"
    raw_address = "서울특별시 중구 세종대로 110"

    with Session(db_engine) as session:
        user = User(email="agent-address@example.com", display_name="배송받는사람")
        session.add(user)
        session.commit()
        session.refresh(user)
        add_agent_cart_item(
            session,
            user,
            conversation_id="conv_address",
            product_id="prod_001",
            quantity=1,
            recommendation_id=None,
            recommendation_rank=None,
        )

        response = execute_agent_tool(
            session,
            tool_name="register_shipping_address",
            arguments={
                "recipient_name": "배송받는사람",
                "phone": raw_phone,
                "postal_code": "04524",
                "address1": raw_address,
                "continue_checkout": True,
            },
            user=user,
            conversation_id="conv_address",
            request_id="req_address",
        )
        session.commit()

        address = session.scalar(select(UserAddress).where(UserAddress.user_id == user.id))
        tool_call = session.scalar(select(AgentToolCall).where(AgentToolCall.request_id == "req_address"))

    assert address is not None
    assert address.is_default is True
    assert address.phone == "01098765432"
    assert address.address1 == raw_address
    assert address.address2 is None
    assert response.tool_name == "register_shipping_address"
    assert response.ui_action.type == "show_checkout_preview"
    assert response.ui_action.payload["address_id"] == address.id
    assert tool_call is not None
    assert tool_call.input_json["pii_redacted"] is True
    assert tool_call.input_json["address2_provided"] is False
    serialized_input = json.dumps(tool_call.input_json, ensure_ascii=False)
    assert raw_phone not in serialized_input
    assert raw_address not in serialized_input


def test_prepare_product_checkout_preserves_selection_through_address_registration(
    db_engine: Engine,
) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    with Session(db_engine) as session:
        user = User(email="agent-product-checkout@example.com", display_name="주문사용자")
        session.add(user)
        session.commit()
        session.refresh(user)

        missing_address = execute_agent_tool(
            session,
            tool_name="prepare_product_checkout",
            arguments={
                "product_id": "prod_001",
                "quantity": 1,
                "recommendation_id": "rec_product_checkout",
                "recommendation_rank": 2,
            },
            user=user,
            conversation_id="conv_product_checkout",
        )
        session.commit()
        selected_ids = missing_address.ui_action.payload["cart_item_ids"]

        resumed = execute_agent_tool(
            session,
            tool_name="register_shipping_address",
            arguments={
                "recipient_name": "주문사용자",
                "phone": "010-1234-5678",
                "postal_code": "04524",
                "address1": "서울특별시 중구 세종대로 110",
                "address2": "3층",
                "continue_checkout": True,
                "cart_item_ids": selected_ids,
            },
            user=user,
            conversation_id="conv_product_checkout",
        )
        repeated = execute_agent_tool(
            session,
            tool_name="prepare_product_checkout",
            arguments={"product_id": "prod_001", "quantity": 1},
            user=user,
            conversation_id="conv_product_checkout",
        )
        cart = get_cart_response(session, user, None)

    assert missing_address.error is not None
    assert missing_address.error.code == "AGENT_ADDRESS_REQUIRED"
    assert missing_address.ui_action.type == "noop"
    assert missing_address.ui_action.payload["agent_flow"] == "product_checkout"
    assert missing_address.items[0].id == "prod_001"
    assert resumed.ui_action.type == "show_checkout_preview"
    assert [item["id"] for item in resumed.ui_action.payload["items"]] == selected_ids
    assert repeated.ui_action.type == "show_checkout_preview"
    assert repeated.ui_action.payload["agent_flow"] == "product_checkout"
    assert len(cart.items) == 1
    assert cart.items[0].quantity == 1


def test_register_shipping_address_requires_missing_profile_details(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        user = User(email="agent-address-missing@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)

        with pytest.raises(ApiError) as exc_info:
            execute_agent_tool(
                session,
                tool_name="register_shipping_address",
                arguments={
                    "postal_code": "04524",
                    "address1": "서울특별시 중구 세종대로 110",
                    "address2": "3층",
                    "continue_checkout": False,
                },
                user=user,
            )

        address_count = len(session.scalars(select(UserAddress).where(UserAddress.user_id == user.id)).all())

    assert exc_info.value.code == "AGENT_ADDRESS_DETAILS_REQUIRED"
    assert address_count == 0


def test_openai_tool_returns_structured_address_request(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    with Session(db_engine) as session:
        user = User(email="agent-address-followup@example.com", display_name="주소요청")
        session.add(user)
        session.commit()
        session.refresh(user)
        add_agent_cart_item(
            session,
            user,
            conversation_id="conv_address_followup",
            product_id="prod_001",
            quantity=1,
            recommendation_id=None,
            recommendation_rank=None,
        )
        context = CommerceAgentContext(
            session=session,
            user=user,
            conversation_id="conv_address_followup",
            request_id="req_address_followup",
            session_id=None,
            anonymous_user_id=None,
        )
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="prepare_checkout",
            arguments={"cart_item_ids": None, "address_id": None},
        )

    payload = json.loads(result)
    assert payload["error"]["code"] == "AGENT_ADDRESS_REQUIRED"
    assert "받는 분 이름" in payload["message"]
    assert context.last_tool_response is not None


def test_openai_tool_adds_to_anonymous_cart(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    anonymous_cart_id = "agent-anonymous-cart"
    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_login_required",
            request_id="req_login_required",
            session_id=None,
            anonymous_user_id=None,
            anonymous_cart_id=anonymous_cart_id,
        )
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="add_to_cart",
            arguments={"product_id": "prod_001", "quantity": 1},
        )
        cart = get_cart_response(session, None, anonymous_cart_id)

    payload = json.loads(result)
    assert payload["conversation_id"] == "conv_login_required"
    assert payload["tool_name"] == "add_to_cart"
    assert payload["error"] is None
    assert payload["ui_action"]["type"] == "show_cart"
    assert cart.total_quantity == 1
    assert context.last_tool_response is not None


def test_dispatcher_resolves_popular_rank_before_adding_to_anonymous_cart(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    anonymous_cart_id = "agent-popular-cart"
    now = datetime.now(UTC)

    with Session(db_engine) as session:
        products = session.scalars(select(Product).order_by(Product.product_code.asc())).all()
        assert len(products) >= 2
        session.add_all([
            ProductPopularityMetric(
                product_id=products[0].id,
                window_days=7,
                popularity_score=100,
                score_version="behavior_rollup_v1",
                computed_at=now,
            ),
            ProductPopularityMetric(
                product_id=products[1].id,
                window_days=7,
                popularity_score=90,
                score_version="behavior_rollup_v1",
                computed_at=now,
            ),
        ])
        session.flush()

        response = execute_agent_tool(
            session,
            tool_name="add_to_cart",
            arguments={"reference_source": "popular", "reference_rank": 1},
            anonymous_cart_id=anonymous_cart_id,
            conversation_id="conv_popular_cart",
        )
        cart = get_cart_response(session, None, anonymous_cart_id)

    assert response.message == "인기 1위 상품을 장바구니에 담았어요."
    assert response.ui_action.type == "show_cart"
    assert [item.product_id for item in cart.items] == [products[0].product_code]


def test_dispatcher_resolves_current_product_reference_before_adding_to_cart(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    anonymous_cart_id = "agent-current-product-cart"

    with Session(db_engine) as session:
        response = execute_agent_tool(
            session,
            tool_name="add_to_cart",
            arguments={"reference_source": "current_product"},
            current_product_id="prod_002",
            anonymous_cart_id=anonymous_cart_id,
            conversation_id="conv_current_product_cart",
        )
        cart = get_cart_response(session, None, anonymous_cart_id)

    assert response.message == "상품을 장바구니에 담았어요."
    assert [item.product_id for item in cart.items] == ["prod_002"]


def test_dispatcher_resolves_wishlist_and_recent_references(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    with Session(db_engine) as session:
        user = User(email="agent-activity-reference@example.com", display_name="activity-reference")
        session.add(user)
        session.flush()
        add_wishlist_item(session, user, "prod_001")
        upsert_recent_view(session, user, "prod_002")
        session.commit()

        wishlist_response = execute_agent_tool(
            session,
            tool_name="add_to_cart",
            arguments={"reference_source": "wishlist", "reference_rank": 1},
            user=user,
            conversation_id="conv_wishlist_reference",
        )
        recent_response = execute_agent_tool(
            session,
            tool_name="add_to_cart",
            arguments={"reference_source": "recent", "reference_position": "last"},
            user=user,
            conversation_id="conv_recent_reference",
        )
        cart = get_cart_response(session, user, None)

    assert wishlist_response.message == "상품을 장바구니에 담았어요."
    assert recent_response.message == "상품을 장바구니에 담았어요."
    assert {item.product_id for item in cart.items} == {"prod_001", "prod_002"}


def test_openai_tool_deterministically_resolves_last_tool_result_position(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    anonymous_cart_id = "agent-last-result-cart"
    last_tool_result = AgentLastToolResult(
        action_type="show_products",
        target="similar_products",
        items=[
            AgentContextResultItem(item_type="product", id="prod_001", title="첫 번째 상품"),
            AgentContextResultItem(item_type="product", id="prod_002", title="두 번째 상품"),
        ],
    )

    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_last_result",
            request_id="req_last_result",
            session_id="sess_last_result",
            anonymous_user_id="anon_last_result",
            anonymous_cart_id=anonymous_cart_id,
            user_message="이 중에서 마지막 거 장바구니에 담아줘",
            last_tool_result=last_tool_result,
        )
        tool_context = SimpleNamespace(context=context)

        for _ in range(3):
            _execute_tool(
                tool_context,
                tool_name="add_to_cart",
                arguments={"product_id": "prod_001", "quantity": 1},
            )

        cart = get_cart_response(session, None, anonymous_cart_id)

    assert [(item.product_id, item.quantity) for item in cart.items] == [("prod_002", 3)]


def test_openai_tool_preserves_product_id_explicitly_written_by_user(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    anonymous_cart_id = "agent-explicit-result-cart"
    last_tool_result = AgentLastToolResult(
        action_type="show_products",
        target="similar_products",
        items=[
            AgentContextResultItem(item_type="product", id="prod_001", title="첫 번째 상품"),
            AgentContextResultItem(item_type="product", id="prod_002", title="두 번째 상품"),
        ],
    )

    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_explicit_result",
            request_id="req_explicit_result",
            session_id="sess_explicit_result",
            anonymous_user_id="anon_explicit_result",
            anonymous_cart_id=anonymous_cart_id,
            user_message="마지막 상품 말고 prod_001을 장바구니에 담아줘",
            last_tool_result=last_tool_result,
        )
        _execute_tool(
            SimpleNamespace(context=context),
            tool_name="add_to_cart",
            arguments={"product_id": "prod_001", "quantity": 1},
        )
        cart = get_cart_response(session, None, anonymous_cart_id)

    assert [item.product_id for item in cart.items] == ["prod_001"]


def test_dispatcher_resolves_recommendation_rank_before_adding_to_cart(db_engine: Engine) -> None:
    _set_inventory(db_engine, "prod_001", stock_quantity=10)
    _set_inventory(db_engine, "prod_002", stock_quantity=10)
    anonymous_cart_id = "agent-recommendation-cart"

    with Session(db_engine) as session:
        recommendation = execute_agent_tool(
            session,
            tool_name="create_recommendation",
            arguments={
                "concern_text": "민감 피부용 보습 세럼을 추천해줘",
                "page_size": 10,
                "concern_ids": ["concern_sensitive"],
                "effect_ids": ["effect_moisture_barrier"],
                "category_codes": ["serum"],
            },
            conversation_id="conv_recommendation_cart",
        )
        recommendation_id = str(recommendation.ui_action.payload["recommendation_id"])
        assert recommendation.ui_action.payload["summary"]["sensitivity"] == "높음"
        expected_product_id = recommendation.items[0].id

        response = execute_agent_tool(
            session,
            tool_name="add_to_cart",
            arguments={
                "reference_source": "recommendation",
                "reference_rank": 1,
                "recommendation_id": recommendation_id,
            },
            anonymous_cart_id=anonymous_cart_id,
            conversation_id="conv_recommendation_cart",
        )
        cart = get_cart_response(session, None, anonymous_cart_id)

    assert response.message == "추천 결과 1위 상품을 장바구니에 담았어요."
    assert [item.product_id for item in cart.items] == [expected_product_id]


def test_openai_tool_hides_unexpected_internal_error(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_safe_error",
            request_id="req_safe_error",
            session_id=None,
            anonymous_user_id=None,
        )

        def raise_internal_error(*args, **kwargs):
            raise RuntimeError('relation "private_table" does not exist')

        monkeypatch.setattr("app.services.agent_openai_runner.execute_agent_tool", raise_internal_error)
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="find_similar_products",
            arguments={"product_id": "prod_001", "limit": 2},
        )

    payload = json.loads(result)
    assert payload["error"]["code"] == "AGENT_TOOL_EXECUTION_FAILED"
    assert "private_table" not in payload["message"]
    assert "잠시 후 다시 시도" in payload["message"]


def test_openai_tool_turns_empty_cart_into_non_retryable_guidance(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_empty_cart",
            request_id="req_empty_cart",
            session_id=None,
            anonymous_user_id=None,
        )

        def raise_empty_cart(*args, **kwargs):
            raise ApiError(400, "AGENT_CART_EMPTY", "장바구니가 비어 있어요.")

        monkeypatch.setattr("app.services.agent_openai_runner.execute_agent_tool", raise_empty_cart)
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="prepare_checkout",
            arguments={"cart_item_ids": None, "address_id": None},
        )

    payload = json.loads(result)
    assert payload["error"]["code"] == "AGENT_CART_EMPTY"
    assert payload["error"]["retryable"] is False
    assert "장바구니가 비어" in payload["message"]


def test_openai_tool_turns_missing_comparison_selection_into_clarification(
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(db_engine) as session:
        context = CommerceAgentContext(
            session=session,
            user=None,
            conversation_id="conv_clarification",
            request_id="req_clarification",
            session_id=None,
            anonymous_user_id=None,
        )

        def raise_missing_selection(*args, **kwargs):
            raise ApiError(400, "AGENT_COMPARE_REQUIRES_TWO_PRODUCTS", "internal detail")

        monkeypatch.setattr("app.services.agent_openai_runner.execute_agent_tool", raise_missing_selection)
        result = _execute_tool(
            type("RunContext", (), {"context": context})(),
            tool_name="compare_products",
            arguments={"product_ids": ["prod_001"]},
        )

    payload = json.loads(result)
    assert payload["error"]["code"] == "AGENT_CLARIFICATION_REQUIRED"
    assert "비교할 상품을 2개 이상" in payload["message"]


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


class _PerformanceLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.performance").removeHandler(self)
        super().close()


def _capture_performance_logs() -> _PerformanceLogCaptureHandler:
    logger = logging.getLogger("mwobareullae.performance")
    logger.setLevel(logging.INFO)
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler
