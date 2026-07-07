import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.performance_logging import log_performance_event
from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import Inventory, ProductPopularityMetric
from app.db.models.recommendation import RecommendationResult, RecommendationRun
from app.db.session import get_db
from app.main import app
from app.middleware.request_logging import request_logging_middleware
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


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mwobareullae",
    }


def test_health_endpoint_includes_request_observability_headers(
    client: TestClient,
) -> None:
    logs = _capture_request_logs()

    try:
        response = client.get("/api/health", headers={"X-Request-ID": "test-request-id"})
    finally:
        logs.close()

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0

    payload = logs.json_lines[-1]
    assert payload["service"] == "commerce-backend"
    assert payload["request_id"] == "test-request-id"
    assert payload["method"] == "GET"
    assert payload["endpoint"] == "/api/health"
    assert payload["status_code"] == 200
    assert payload["response_time_ms"] >= 0
    assert payload["user_id"] is None
    assert payload["error"] is None
    assert payload["timestamp"].endswith("Z")


def test_request_log_includes_authenticated_user_id(client: TestClient) -> None:
    signup_response = client.post(
        "/api/auth/signup",
        json={
            "email": "request-log-user@example.com",
            "password": "password123",
            "nickname": "request-log-user",
            "consents": {
                "tos": True,
                "privacy": True,
                "age14": True,
                "marketing": False,
            },
        },
    )
    logs = _capture_request_logs()

    try:
        response = client.get("/api/me", headers={"X-Request-ID": "auth-log-request"})
    finally:
        logs.close()

    assert signup_response.status_code == 200
    assert response.status_code == 200
    assert logs.json_lines[-1]["request_id"] == "auth-log-request"
    assert logs.json_lines[-1]["endpoint"] == "/api/me"
    assert logs.json_lines[-1]["user_id"] == str(response.json()["id"])


def test_request_log_records_unhandled_exception_as_json() -> None:
    test_app = FastAPI()
    test_app.middleware("http")(request_logging_middleware)

    @test_app.get("/boom/{item_id}")
    def boom(item_id: str):
        raise RuntimeError(f"boom {item_id}")

    logs = _capture_request_logs()
    try:
        response = TestClient(test_app, raise_server_exceptions=False).get(
            "/boom/123",
            headers={"X-Request-ID": "boom-request"},
        )
    finally:
        logs.close()

    assert response.status_code == 500
    payload = logs.json_lines[-1]
    assert payload["request_id"] == "boom-request"
    assert payload["endpoint"] == "/boom/{item_id}"
    assert payload["status_code"] == 500
    assert payload["error"] == "RuntimeError"


def test_performance_log_utility_writes_json_line() -> None:
    logs = _capture_performance_logs()
    try:
        log_performance_event(
            "performance_test_completed",
            request_id="performance-request",
            duration_ms=12.345,
            metadata={
                "count": 3,
                "score": Decimal("1.25"),
                "timestamp": "should_not_override",
            },
        )
    finally:
        logs.close()

    payload = logs.json_lines[-1]
    assert payload["service"] == "commerce-backend"
    assert payload["event"] == "performance_test_completed"
    assert payload["request_id"] == "performance-request"
    assert payload["duration_ms"] == 12.35
    assert payload["count"] == 3
    assert payload["score"] == 1.25
    assert payload["timestamp"].endswith("Z")


def test_get_home_sections_returns_main_page_products(client: TestClient) -> None:
    response = client.get(
        "/api/home/sections",
        params={
            "skin_type": "건성",
            "sensitivity": "보통",
            "limit_per_section": 2,
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["skin_type"] == "건성"
    assert data["sensitivity"] == "보통"
    assert [section["section_id"] for section in data["sections"]] == [
        "evidence_picks",
        "recommended_for_you",
    ]

    first_section = data["sections"][0]
    assert first_section["algorithm"]
    assert 0 < len(first_section["products"]) <= 2

    product = first_section["products"][0]
    assert {
        "product_id",
        "brand",
        "name",
        "category_code",
        "category_name",
        "thumbnail_url",
        "lowest_price",
        "purchase_url",
        "badges",
        "tags",
        "reason_summary",
        "display_score",
    }.issubset(product)
    assert product["thumbnail_url"].startswith("products/")
    assert not product["thumbnail_url"].startswith("http")
    assert product["badges"]
    assert 0 <= product["display_score"] <= 100


def test_get_home_sections_emits_performance_log(client: TestClient) -> None:
    logs = _capture_performance_logs()
    try:
        response = client.get(
            "/api/home/sections",
            params={"limit_per_section": 2},
            headers={"X-Request-ID": "home-performance-request"},
        )
    finally:
        logs.close()

    assert response.status_code == 200
    payload = logs.json_lines[-1]
    assert payload["event"] == "home_sections_completed"
    assert payload["request_id"] == "home-performance-request"
    assert payload["duration_ms"] >= 0
    assert payload["section_count"] >= 1
    assert payload["product_count"] >= 1


def test_get_popular_products_returns_metric_ranked_products(
    client: TestClient,
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        first_product = session.execute(
            select(Product).where(Product.product_code == "prod_001")
        ).scalar_one()
        second_product = session.execute(
            select(Product).where(Product.product_code == "prod_002")
        ).scalar_one()
        session.add_all(
            [
                ProductPopularityMetric(
                    product_id=first_product.id,
                    window_days=7,
                    view_count=100,
                    click_count=30,
                    cart_add_count=10,
                    order_count=5,
                    units_sold=6,
                    review_count=20,
                    average_rating=4.5,
                    popularity_score=70,
                ),
                ProductPopularityMetric(
                    product_id=second_product.id,
                    window_days=7,
                    view_count=200,
                    click_count=60,
                    cart_add_count=20,
                    order_count=9,
                    units_sold=12,
                    review_count=40,
                    average_rating=4.7,
                    popularity_score=92,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/products/popular", params={"window_days": 7, "limit": 2})

    assert response.status_code == 200

    data = response.json()
    assert data["window_days"] == 7
    assert [item["product_id"] for item in data["items"]] == ["prod_002", "prod_001"]

    first_item = data["items"][0]
    assert first_item["thumbnail_url"].startswith("products/")
    assert not first_item["thumbnail_url"].startswith("http")
    assert first_item["popularity_score"] == 92.0
    assert first_item["score_version"] == "popular_v1"
    assert first_item["metrics"] == {
        "view_count": 200,
        "click_count": 60,
        "cart_add_count": 20,
        "order_count": 9,
        "units_sold": 12,
        "wishlist_add_count": 0,
        "checkout_start_count": 0,
        "paid_order_count": 0,
        "home_product_impression_count": 0,
        "home_product_click_count": 0,
        "search_result_impression_count": 0,
        "search_result_click_count": 0,
        "wishlist_remove_count": 0,
        "cart_remove_count": 0,
        "cart_quantity_change_count": 0,
        "payment_failed_count": 0,
        "order_cancel_count": 0,
        "review_count": 40,
        "average_rating": 4.7,
    }


def test_get_home_sections_includes_market_popular_when_metrics_exist(
    client: TestClient,
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        product = session.execute(
            select(Product).where(Product.product_code == "prod_001")
        ).scalar_one()
        session.add(
            ProductPopularityMetric(
                product_id=product.id,
                window_days=7,
                view_count=100,
                click_count=30,
                cart_add_count=10,
                order_count=5,
                units_sold=6,
                review_count=20,
                average_rating=4.5,
                popularity_score=88,
            )
        )
        session.commit()

    response = client.get("/api/home/sections", params={"limit_per_section": 2})

    assert response.status_code == 200

    data = response.json()
    assert data["sections"][0]["section_id"] == "market_popular"
    assert data["sections"][0]["algorithm"] == "product_popularity_metrics_v1"
    assert data["sections"][0]["products"][0]["product_id"] == "prod_001"
    assert data["sections"][0]["products"][0]["display_score"] == 88


def test_create_recommendation_applies_request_defaults(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={
            "concern_text": "모공이랑 속건조가 고민이에요",
            "skin_type": "",
            "sensitivity": None,
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["recommendation_id"].startswith("rec_")
    assert data["summary"]["skin_type"] == "중성"
    assert data["summary"]["sensitivity"] == "보통"
    assert data["summary"]["avoid_ingredients"] == []
    assert 0 < len(data["products"]) <= 50

    product = data["products"][0]
    assert {
        "product_id",
        "rank",
        "total_score",
        "reason_summary",
        "brand",
        "name",
        "thumbnail_url",
        "lowest_price",
        "evidence_tags",
        "key_ingredients",
        "score_breakdown",
        "cart_handoff",
    }.issubset(product)
    assert product["thumbnail_url"].startswith("products/")
    assert not product["thumbnail_url"].startswith("http")
    assert product["cart_handoff"] == {
        "product_id": product["product_id"],
        "quantity": 1,
        "source": "ai_recommendation",
        "recommendation_id": data["recommendation_id"],
        "recommendation_rank": product["rank"],
    }


def test_create_recommendation_uses_concern_parser(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이랑 속건조가 고민이에요"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["summary"]["matched_concerns"]
    assert data["summary"]["expected_effects"]
    assert data["unmatched_terms"] == []


def test_create_recommendation_includes_purchase_constraints(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "라운드랩 크림 2만원 이하로 추천해줘"},
    )

    assert response.status_code == 200

    constraints = response.json()["summary"]["purchase_constraints"]
    assert constraints["categories"][0]["category_code"] == "cream"
    assert constraints["brands"][0]["brand_code"] == "라운드랩"
    assert constraints["price_min"] is None
    assert constraints["price_max"] == 20000


def test_create_recommendation_applies_category_brand_and_price_hard_filters(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "아누아 세럼 2만원대 추천"},
    )

    assert response.status_code == 200

    constraints = response.json()["summary"]["purchase_constraints"]
    assert constraints["categories"][0]["category_code"] == "serum"
    assert constraints["brands"][0]["brand_code"] == "아누아"
    assert constraints["price_min"] == 20000
    assert constraints["price_max"] == 29999
    assert constraints["price_text"] == "2만원대"

    products = response.json()["products"]
    assert [product["product_id"] for product in products] == ["prod_002"]
    assert products[0]["brand"] == "아누아"
    assert 20000 <= products[0]["lowest_price"] <= 29999


def test_create_recommendation_applies_price_max_hard_filter(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "크림 2만원 이하 추천"},
    )

    assert response.status_code == 200

    products = response.json()["products"]
    assert [product["product_id"] for product in products] == ["prod_001"]
    assert products[0]["lowest_price"] <= 20000


def test_create_recommendation_returns_empty_products_when_hard_filter_has_no_match(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "라운드랩 세럼 2만원 이하로 추천해줘"},
    )

    assert response.status_code == 200
    assert response.json()["products"] == []


def test_create_recommendation_keeps_unmatched_terms_from_parser(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이랑 삐딱삐딱"},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["summary"]["matched_concerns"]
    assert data["unmatched_terms"] == ["삐딱삐딱"]


def test_create_recommendation_rejects_blank_concern_text(client: TestClient) -> None:
    response = client.post("/api/recommendations", json={"concern_text": "   "})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INVALID_INPUT",
            "message": "고민 텍스트는 필수입니다.",
        }
    }


def test_create_recommendation_rejects_invalid_skin_type(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이 고민이에요", "skin_type": "기타"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_create_recommendation_rejects_invalid_sensitivity(client: TestClient) -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이 고민이에요", "sensitivity": "매우높음"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_get_recommendation_returns_created_payload(client: TestClient) -> None:
    created_response = client.post(
        "/api/recommendations",
        json={"concern_text": "속건조랑 자극이 고민이에요"},
    )
    created = created_response.json()

    response = client.get(f"/api/recommendations/{created['recommendation_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_recommendation_response_supports_pagination(client: TestClient) -> None:
    created_response = client.post(
        "/api/recommendations",
        params={"page": 1, "page_size": 1},
        json={"concern_text": "속건조 보습 추천"},
    )

    assert created_response.status_code == 200

    first_page = created_response.json()
    assert len(first_page["products"]) == 1
    assert first_page["pagination"]["page"] == 1
    assert first_page["pagination"]["page_size"] == 1
    assert first_page["pagination"]["total_items"] >= 2
    assert first_page["pagination"]["total_pages"] >= 2
    assert first_page["pagination"]["has_next"] is True
    assert first_page["pagination"]["has_prev"] is False

    second_response = client.get(
        f"/api/recommendations/{first_page['recommendation_id']}",
        params={"page": 2, "page_size": 1},
    )

    assert second_response.status_code == 200

    second_page = second_response.json()
    assert len(second_page["products"]) == 1
    assert second_page["products"][0]["rank"] == 2
    assert second_page["pagination"]["page"] == 2
    assert second_page["pagination"]["page_size"] == 1
    assert second_page["pagination"]["total_items"] == first_page["pagination"]["total_items"]
    assert second_page["pagination"]["has_prev"] is True


def test_create_recommendation_narrative_returns_card_payload_by_default(client: TestClient) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl narrative smoke test"},
    ).json()

    response = client.post(
        f"/api/recommendations/{created['recommendation_id']}/narrative",
        json={
            "use_llm": False,
            "product_limit": 2,
        },
    )

    assert response.status_code == 200

    data = response.json()
    narrative = data["narrative"]
    assert data["recommendation_id"] == created["recommendation_id"]
    assert narrative["generation_source"] == "rule_based"
    assert narrative["overview"]["headline"]
    assert narrative["overview"]["summary"]
    assert narrative["overview"]["key_points"]
    assert narrative["selection_guide"] is None
    assert len(narrative["product_explanations"]) == 2
    product = narrative["product_explanations"][0]
    assert product["product_id"] == created["products"][0]["product_id"]
    assert product["role"]
    assert product["card"]["headline"]
    assert product["card"]["reason"]
    assert product["card"]["chips"]
    assert product["detail_sections"] == []
    assert product["caution"] is None


def test_create_recommendation_narrative_full_view_returns_detail_sections(client: TestClient) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl narrative full view smoke test"},
    ).json()

    response = client.post(
        f"/api/recommendations/{created['recommendation_id']}/narrative",
        json={
            "view": "full",
            "use_llm": False,
            "product_limit": 2,
        },
    )

    assert response.status_code == 200

    narrative = response.json()["narrative"]
    assert narrative["generation_source"] == "rule_based"
    assert narrative["selection_guide"]
    assert len(narrative["product_explanations"]) == 2
    product = narrative["product_explanations"][0]
    assert product["detail_sections"]
    assert product["caution"]


def test_create_recommendation_narrative_detail_view_returns_one_product(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl narrative detail view smoke test"},
    ).json()
    target_product = created["products"][1]

    response = client.post(
        f"/api/recommendations/{created['recommendation_id']}/narrative",
        json={
            "view": "detail",
            "product_id": target_product["product_id"],
            "use_llm": False,
        },
    )

    assert response.status_code == 200

    narrative = response.json()["narrative"]
    assert narrative["generation_source"] == "rule_based"
    assert narrative["selection_guide"] is None
    assert len(narrative["product_explanations"]) == 1
    product = narrative["product_explanations"][0]
    assert product["product_id"] == target_product["product_id"]
    assert product["detail_sections"]


def test_create_recommendation_narrative_detail_view_requires_product_id(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl narrative missing product id smoke test"},
    ).json()

    response = client.post(
        f"/api/recommendations/{created['recommendation_id']}/narrative",
        json={
            "view": "detail",
            "use_llm": False,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_create_recommendation_narrative_handles_empty_results(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl narrative empty result smoke test"},
    ).json()

    with Session(db_engine) as session:
        run = session.execute(
            select(RecommendationRun).where(
                RecommendationRun.recommendation_code == created["recommendation_id"],
            )
        ).scalar_one()
        session.query(RecommendationResult).filter(
            RecommendationResult.recommendation_run_id == run.id,
        ).delete()
        session.commit()

    response = client.post(
        f"/api/recommendations/{created['recommendation_id']}/narrative",
        json={
            "use_llm": True,
            "product_limit": 2,
        },
    )

    assert response.status_code == 200

    narrative = response.json()["narrative"]
    assert narrative["generation_source"] == "rule_based"
    assert narrative["overview"]["headline"]
    assert narrative["product_explanations"] == []


def test_get_recommendation_returns_404_for_missing_id(client: TestClient) -> None:
    response = client.get("/api/recommendations/rec_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_recommendation_returns_410_for_expired_id(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl recommendation smoke test"},
    ).json()
    _expire_recommendation(db_engine, created["recommendation_id"])

    response = client.get(f"/api/recommendations/{created['recommendation_id']}")

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "EXPIRED_RECOMMENDATION"


def test_get_product_detail_returns_general_db_detail(client: TestClient) -> None:
    response = client.get("/api/products/prod_001")

    assert response.status_code == 200

    data = response.json()
    assert data["product"]["product_id"] == "prod_001"
    assert data["product"]["thumbnail_url"] == "products/prod_001/thumbnail.jpg"
    assert data["images"]
    assert all(not image["storage_key"].startswith("http") for image in data["images"])
    assert data["prices"]
    assert data["purchase_info"]["seller_code"] == "mwobareullae"
    assert data["purchase_info"]["price"] == 19900
    assert data["purchase_info"]["currency"] == "KRW"
    assert data["purchase_info"]["stock_status"] == "UNKNOWN"
    assert data["purchase_info"]["can_purchase"] is False
    assert data["ingredients"]
    assert data["evidence"]["ingredient_evidence"]
    assert data["sources"]
    assert data["product"]["cart_handoff"] is None


def test_get_product_detail_includes_purchase_stock_info(
    client: TestClient,
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        product_id = session.execute(
            select(Product.id).where(Product.product_code == "prod_001")
        ).scalar_one()
        session.add(
            Inventory(
                product_id=product_id,
                stock_quantity=8,
                reserved_quantity=2,
                safety_stock=1,
                sales_status="ON_SALE",
                inventory_source="TEST",
            )
        )
        session.commit()

    response = client.get("/api/products/prod_001")

    assert response.status_code == 200

    purchase_info = response.json()["purchase_info"]
    assert purchase_info["can_purchase"] is True
    assert purchase_info["sales_status"] == "ON_SALE"
    assert purchase_info["stock_status"] == "LOW_STOCK"
    assert purchase_info["available_quantity"] == 5


def test_get_product_detail_includes_recommendation_context(client: TestClient) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "크림 2만원 이하 추천"},
    ).json()
    recommended_product = created["products"][0]

    response = client.get(
        f"/api/products/{recommended_product['product_id']}",
        params={"recommendation_id": created["recommendation_id"]},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["product"]["total_score"] == recommended_product["total_score"]
    assert data["product"]["score_breakdown"] == recommended_product["score_breakdown"]
    assert data["product"]["cart_handoff"] == recommended_product["cart_handoff"]
    assert data["evidence"]["recommendation_reason"] == recommended_product["reason_summary"]


def test_get_product_detail_returns_404_for_missing_product(client: TestClient) -> None:
    response = client.get("/api/products/missing-product")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_product_detail_returns_404_for_missing_recommendation_context(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/products/prod_001",
        params={"recommendation_id": "rec_missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_product_detail_returns_410_for_expired_recommendation_context(
    client: TestClient,
    db_engine: Engine,
) -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "ttl product detail smoke test"},
    ).json()
    recommended_product = created["products"][0]
    _expire_recommendation(db_engine, created["recommendation_id"])

    response = client.get(
        f"/api/products/{recommended_product['product_id']}",
        params={"recommendation_id": created["recommendation_id"]},
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "EXPIRED_RECOMMENDATION"


def test_openapi_docs_are_available(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200


def _capture_request_logs():
    logger = logging.getLogger("mwobareullae.request")
    handler = _RequestLogCaptureHandler()
    logger.addHandler(handler)
    return handler


def _capture_performance_logs():
    logger = logging.getLogger("mwobareullae.performance")
    handler = _PerformanceLogCaptureHandler()
    logger.addHandler(handler)
    return handler


class _RequestLogCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    @property
    def json_lines(self) -> list[dict]:
        return [json.loads(message) for message in self.messages]

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        logging.getLogger("mwobareullae.request").removeHandler(self)
        super().close()


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


def _expire_recommendation(db_engine: Engine, recommendation_id: str) -> None:
    with Session(db_engine) as session:
        run = session.execute(
            select(RecommendationRun).where(
                RecommendationRun.recommendation_code == recommendation_id,
            )
        ).scalar_one()
        run.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
