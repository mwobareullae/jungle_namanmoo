from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.recommendation import RecommendationResult, RecommendationRun
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
    caplog,
) -> None:
    caplog.set_level("INFO", logger="mwobareullae.request")

    response = client.get("/api/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0
    assert any(
        "request_finished" in record.message and "test-request-id" in record.message
        for record in caplog.records
    )


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
        "best_sellers",
        "evidence_picks",
        "recommended_for_you",
    ]

    first_section = data["sections"][0]
    assert first_section["title"] == "지금 인기있는 제품"
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
    assert product["badges"]
    assert 0 <= product["display_score"] <= 100


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
    }.issubset(product)


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


def test_create_recommendation_narrative_returns_fallback_payload(client: TestClient) -> None:
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
    assert len(narrative["product_explanations"]) == 2
    product = narrative["product_explanations"][0]
    assert product["product_id"] == created["products"][0]["product_id"]
    assert product["role"]
    assert product["card"]["headline"]
    assert product["card"]["reason"]
    assert product["card"]["chips"]
    assert product["detail_sections"]


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
    assert data["images"]
    assert data["prices"]
    assert data["ingredients"]
    assert data["evidence"]["ingredient_evidence"]
    assert data["sources"]


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


def _expire_recommendation(db_engine: Engine, recommendation_id: str) -> None:
    with Session(db_engine) as session:
        run = session.execute(
            select(RecommendationRun).where(
                RecommendationRun.recommendation_code == recommendation_id,
            )
        ).scalar_one()
        run.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
