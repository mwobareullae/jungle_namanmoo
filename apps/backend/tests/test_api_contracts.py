from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mwobareullae",
    }


def test_create_recommendation_applies_request_defaults() -> None:
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
    assert data["products"]

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


def test_create_recommendation_rejects_blank_concern_text() -> None:
    response = client.post("/api/recommendations", json={"concern_text": "   "})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "INVALID_INPUT",
            "message": "고민 텍스트는 필수입니다.",
        }
    }


def test_create_recommendation_rejects_invalid_skin_type() -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이 고민이에요", "skin_type": "기타"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_create_recommendation_rejects_invalid_sensitivity() -> None:
    response = client.post(
        "/api/recommendations",
        json={"concern_text": "모공이 고민이에요", "sensitivity": "매우높음"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_get_recommendation_returns_created_payload() -> None:
    created_response = client.post(
        "/api/recommendations",
        json={"concern_text": "속건조랑 자극이 고민이에요"},
    )
    created = created_response.json()

    response = client.get(f"/api/recommendations/{created['recommendation_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_recommendation_returns_404_for_missing_id() -> None:
    response = client.get("/api/recommendations/rec_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_product_detail_returns_general_mock_detail() -> None:
    response = client.get("/api/products/mock-calming-cream")

    assert response.status_code == 200

    data = response.json()
    assert data["product"]["product_id"] == "mock-calming-cream"
    assert data["images"]
    assert data["prices"]
    assert data["ingredients"]
    assert data["evidence"]["ingredient_evidence"]
    assert data["sources"]


def test_get_product_detail_includes_recommendation_context() -> None:
    created = client.post(
        "/api/recommendations",
        json={"concern_text": "속건조와 모공이 고민이에요"},
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


def test_get_product_detail_returns_404_for_missing_product() -> None:
    response = client.get("/api/products/missing-product")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_get_product_detail_returns_404_for_missing_recommendation_context() -> None:
    response = client.get(
        "/api/products/mock-calming-cream",
        params={"recommendation_id": "rec_missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_docs_are_available() -> None:
    response = client.get("/docs")

    assert response.status_code == 200
