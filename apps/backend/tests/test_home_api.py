from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.commerce import ProductPopularityMetric
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from tests.test_data_loader import EXAMPLES_DIR


DRY = "\uac74\uc131"
HIGH = "\ub192\uc74c"


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


def test_home_sections_endpoint_is_removed(client: TestClient) -> None:
    response = client.get("/api/home/sections")

    assert response.status_code == 404


def test_home_layout_returns_lazy_section_endpoints(client: TestClient) -> None:
    response = client.get("/api/home/layout")

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert [section["section_id"] for section in sections] == [
        "market_popular",
        "for_you",
        "evidence_picks",
    ]
    assert [section["endpoint"] for section in sections] == [
        "/api/home/market-popular",
        "/api/home/for-you",
        "/api/home/evidence-picks",
    ]
    assert all(section["lazy_load"] is True for section in sections)
    assert all("products" not in section for section in sections)


def test_home_market_popular_preserves_metric_ranking(
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

    response = client.get("/api/home/market-popular", params={"limit": 2})

    assert response.status_code == 200
    data = response.json()
    assert data["section_id"] == "market_popular"
    assert data["algorithm"] == "product_popularity_metrics_v1"
    assert [product["product_id"] for product in data["products"]] == ["prod_002", "prod_001"]
    assert [product["display_score"] for product in data["products"]] == [92, 70]


def test_home_recommendation_sections_exclude_non_recommendable_products(
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
        second_product.is_recommendable = False
        second_product.recommend_exclude_reason = "missing_ingredients"
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

    market_response = client.get("/api/home/market-popular", params={"limit": 2})
    evidence_response = client.get("/api/home/evidence-picks", params={"limit": 4})
    for_you_response = client.get("/api/home/for-you", params={"limit": 4})

    assert market_response.status_code == 200
    assert evidence_response.status_code == 200
    assert for_you_response.status_code == 200
    assert _product_ids(market_response.json()["products"]) == ["prod_001"]
    assert "prod_002" not in _product_ids(evidence_response.json()["products"])
    assert "prod_002" not in _product_ids(for_you_response.json()["products"])


def test_home_evidence_picks_returns_sorted_section(client: TestClient) -> None:
    response = client.get("/api/home/evidence-picks", params={"limit": 4})

    assert response.status_code == 200
    data = response.json()
    assert data["section_id"] == "evidence_picks"
    assert data["algorithm"] == "home_v0_ingredient_evidence"
    assert 0 < len(data["products"]) <= 4
    scores = [product["display_score"] for product in data["products"]]
    assert scores == sorted(scores, reverse=True)
    _assert_home_product_contract(data["products"][0])


def test_home_for_you_returns_anonymous_fallback(client: TestClient) -> None:
    response = client.get("/api/home/for-you", params={"limit": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["section_id"] == "for_you"
    assert data["algorithm"] == "home_v1_for_you_personalized"
    assert data["personalization_sources"] == ["fallback"]
    assert 0 < len(data["products"]) <= 3


def test_home_for_you_applies_selected_context(client: TestClient) -> None:
    response = client.get(
        "/api/home/for-you",
        params={
            "skin_type": "dry",
            "sensitivity": "high",
            "concern": "moisture",
            "effect": "barrier",
            "limit": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["skin_type"] == DRY
    assert data["sensitivity"] == HIGH
    assert "request_context" in data["personalization_sources"]
    assert 0 < len(data["products"]) <= 3


def test_home_for_you_applies_saved_manual_skin_profile(client: TestClient) -> None:
    _signup(client, email="home-manual-profile@example.com", nickname="home-manual")
    profile_response = client.put(
        "/api/me/skin-profile",
        json={
            "skin_type": "dry",
            "sensitivity": "high",
            "avoid_ingredients": [],
            "concerns": [],
        },
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()["profile"]

    response = client.get("/api/home/for-you", params={"limit": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["skin_type"] == profile["skin_type"]
    assert data["sensitivity"] == profile["sensitivity"]
    assert "manual_skin_profile" in data["personalization_sources"]
    assert 0 < len(data["products"]) <= 3


def test_home_for_you_applies_skin_test_soft_context(client: TestClient) -> None:
    _signup(client, email="home-skin-test@example.com", nickname="home-skin-test")
    question_set = _question_set(client)
    submit_response = client.post(
        "/api/skin-test/submit",
        json={
            "version": question_set["version"],
            "answers": _answers_for_type(
                question_set["questions"],
                od="O",
                sr="S",
                pn="N",
                wt="T",
            ),
        },
    )
    assert submit_response.status_code == 200

    response = client.get("/api/home/for-you", params={"limit": 3})

    assert response.status_code == 200
    data = response.json()
    assert "skin_test_context" in data["personalization_sources"]
    assert "manual_skin_profile" not in data["personalization_sources"]
    assert 0 < len(data["products"]) <= 3


def test_home_for_you_applies_behavior_affinity(client: TestClient) -> None:
    _signup(client, email="home-behavior@example.com", nickname="home-behavior")
    wishlist_response = client.post("/api/me/wishlist", json={"product_id": "prod_001"})
    assert wishlist_response.status_code == 200

    response = client.get("/api/home/for-you", params={"limit": 3})

    assert response.status_code == 200
    data = response.json()
    assert "behavior_affinity" in data["personalization_sources"]
    assert 0 < len(data["products"]) <= 3


def _assert_home_product_contract(product: dict) -> None:
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
    assert 0 <= product["display_score"] <= 100


def _product_ids(products: list[dict]) -> list[str]:
    return [product["product_id"] for product in products]


def _signup(client: TestClient, *, email: str, nickname: str) -> dict:
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
    return response.json()


def _question_set(client: TestClient) -> dict:
    response = client.get("/api/skin-test/questions")
    assert response.status_code == 200
    return response.json()


def _answers_for_type(
    questions: list[dict],
    *,
    od: str,
    sr: str,
    pn: str,
    wt: str,
) -> list[dict[str, int]]:
    choice_by_sequence = {
        1: 0 if od == "O" else 3,
        2: 0 if sr == "S" else 3,
        3: 0,
        4: 0 if pn == "P" else 3,
        5: 0,
        6: 0 if wt == "W" else 3,
        7: 0,
        8: 0,
    }
    answers: list[dict[str, int]] = []
    for index, question in enumerate(questions, start=1):
        option_index = choice_by_sequence[index]
        option = question["options"][option_index]
        answers.append({"question_id": question["id"], "option_id": option["id"]})
    return answers
