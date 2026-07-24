from collections.abc import Generator
from dataclasses import replace

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product, ProductPrice
from app.db.models.commerce import ProductPopularityMetric
from app.db.models.recommendation import HomeSectionSnapshot, ProductRecommendationCoarseFeature
from app.db.session import get_db
from app.main import app
from app.services import home_sections
from app.services.db_seed import seed_database
from app.services.home_section_snapshot_rollup import rollup_home_section_snapshots
from app.services.home_evidence_pick_feature_rollup import (
    rollup_home_evidence_pick_features,
)
from app.services.recommendation_coarse_feature_rollup import (
    rollup_product_recommendation_coarse_features,
)
from app.services.recommendation_feature_rollup import (
    rollup_product_recommendation_features,
)
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


def test_home_product_tags_use_the_highest_ranked_effect_ingredient_pair(client: TestClient) -> None:
    response = client.get("/api/home/evidence-picks", params={"limit": 4})

    assert response.status_code == 200
    products_by_id = {product["product_id"]: product for product in response.json()["products"]}
    assert products_by_id["prod_001"]["tags"] == ["진정", "판테놀"]
    assert products_by_id["prod_002"]["tags"] == ["피지 조절", "나이아신아마이드"]


def test_home_evidence_picks_uses_coarse_shortlist(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rollup_home_coarse_features(db_engine)
    product_id_batches: list[list[int] | None] = []
    original_load_products = home_sections._load_products

    def capture_load_products(
        session: Session,
        *,
        category_code: str | None,
        product_ids: list[int] | None = None,
    ):
        product_id_batches.append(product_ids)
        return original_load_products(
            session,
            category_code=category_code,
            product_ids=product_ids,
        )

    monkeypatch.setattr(home_sections, "_load_products", capture_load_products)

    response = client.get("/api/home/evidence-picks", params={"limit": 4})

    assert response.status_code == 200
    assert len(product_id_batches) == 1
    assert product_id_batches[0] is not None
    assert len(product_id_batches[0]) <= home_sections.HOME_EVIDENCE_SHORTLIST_LIMIT


def test_home_for_you_uses_coarse_shortlist(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rollup_home_coarse_features(db_engine)
    product_id_batches: list[list[int] | None] = []
    original_load_products = home_sections._load_products

    def capture_load_products(
        session: Session,
        *,
        category_code: str | None,
        product_ids: list[int] | None = None,
    ):
        product_id_batches.append(product_ids)
        return original_load_products(
            session,
            category_code=category_code,
            product_ids=product_ids,
        )

    monkeypatch.setattr(home_sections, "_load_products", capture_load_products)

    response = client.get("/api/home/for-you", params={"limit": 4})

    assert response.status_code == 200
    assert len(product_id_batches) == 1
    assert product_id_batches[0] is not None
    assert len(product_id_batches[0]) <= home_sections.HOME_FOR_YOU_SHORTLIST_LIMIT


def test_home_coarse_shortlists_preserve_default_rankings(db_engine: Engine) -> None:
    _rollup_home_coarse_features(db_engine)

    with Session(db_engine) as session:
        fast_evidence = home_sections.get_evidence_picks_response(session, limit=8)
        fast_for_you = home_sections.get_for_you_response(session, limit=8)

        session.execute(
            update(ProductRecommendationCoarseFeature).values(source_current=False)
        )
        legacy_evidence = home_sections.get_evidence_picks_response(session, limit=8)
        legacy_for_you = home_sections.get_for_you_response(session, limit=8)
        session.rollback()

    assert [product.product_id for product in fast_evidence.products] == [
        product.product_id for product in legacy_evidence.products
    ]
    assert [product.product_id for product in fast_for_you.products] == [
        product.product_id for product in legacy_for_you.products
    ]


def test_home_snapshot_rollup_creates_evidence_and_guest_skin_contexts(db_engine: Engine) -> None:
    _rollup_home_coarse_features(db_engine)

    with Session(db_engine) as session:
        result = rollup_home_section_snapshots(session)
        session.commit()
        rows = session.execute(select(HomeSectionSnapshot)).scalars().all()

    assert result.counts_by_context["evidence_picks:overall"] > 0
    assert {
        row.context_key
        for row in rows
        if row.section_id == "for_you"
    } == {
        "guest:skin_type:건성",
        "guest:skin_type:지성",
        "guest:skin_type:복합성",
        "guest:skin_type:수부지",
        "guest:skin_type:중성",
    }


def test_home_evidence_picks_reads_snapshot_and_current_price(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _rollup_home_snapshots(db_engine)
    with Session(db_engine) as session:
        first_snapshot = session.execute(
            select(HomeSectionSnapshot)
            .where(
                HomeSectionSnapshot.section_id == "evidence_picks",
                HomeSectionSnapshot.context_key == "overall",
            )
            .order_by(HomeSectionSnapshot.rank_order.asc())
        ).scalars().first()
        assert first_snapshot is not None
        price = session.execute(
            select(ProductPrice).where(ProductPrice.product_id == first_snapshot.product_id)
        ).scalars().first()
        assert price is not None
        price.price = 12345
        price.is_lowest = True
        session.commit()

    response = client.get("/api/home/evidence-picks", params={"limit": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["algorithm"] == "home_v1_snapshot_evidence"
    assert data["products"][0]["lowest_price"] == 12345


def test_home_evidence_picks_falls_back_when_snapshot_is_stale(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _rollup_home_snapshots(db_engine)
    with Session(db_engine) as session:
        session.execute(
            update(HomeSectionSnapshot)
            .where(
                HomeSectionSnapshot.section_id == "evidence_picks",
                HomeSectionSnapshot.context_key == "overall",
            )
            .values(computed_at=datetime.now(UTC) - timedelta(days=3))
        )
        session.commit()

    response = client.get("/api/home/evidence-picks", params={"limit": 2})

    assert response.status_code == 200
    assert response.json()["algorithm"] == "home_v0_ingredient_evidence"


def test_home_for_you_uses_guest_snapshot_for_default_sensitivity(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _rollup_home_snapshots(db_engine)

    without_sensitivity = client.get(
        "/api/home/for-you",
        params={"skin_type": "dry", "limit": 2},
    )
    default_sensitivity = client.get(
        "/api/home/for-you",
        params={"skin_type": "dry", "sensitivity": "medium", "limit": 2},
    )

    assert without_sensitivity.status_code == 200
    assert default_sensitivity.status_code == 200
    assert without_sensitivity.json()["algorithm"] == "home_v2_for_you_guest_snapshot"
    assert _product_ids(without_sensitivity.json()["products"]) == _product_ids(
        default_sensitivity.json()["products"]
    )


def test_home_for_you_falls_back_for_noncanonical_conditions(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _rollup_home_snapshots(db_engine)

    response = client.get(
        "/api/home/for-you",
        params={"skin_type": "dry", "sensitivity": "high", "limit": 2},
    )

    assert response.status_code == 200
    assert response.json()["algorithm"] == "home_v1_for_you_personalized"


def test_home_for_you_reranks_guest_snapshot_for_logged_in_user(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _rollup_home_snapshots(db_engine)
    _signup(client, email="home-snapshot-user@example.com", nickname="home-snapshot")
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

    response = client.get("/api/home/for-you", params={"skin_type": "dry", "limit": 2})

    assert response.status_code == 200
    data = response.json()
    assert data["algorithm"] == "home_v2_for_you_snapshot_rerank"
    assert "manual_skin_profile" in data["personalization_sources"]

def test_home_for_you_returns_anonymous_fallback(client: TestClient) -> None:
    response = client.get("/api/home/for-you", params={"limit": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["section_id"] == "for_you"
    assert data["algorithm"] == "home_v1_for_you_personalized"
    assert data["personalization_sources"] == ["fallback"]
    assert 0 < len(data["products"]) <= 3


def test_home_for_you_score_boosts_oliveyoung_and_market_popularity() -> None:
    product = home_sections._ProductBase(
        db_product_id=1,
        product_id="product-1",
        brand="brand",
        brand_code="brand",
        category_code="serum",
        category_name="Serum",
        name="product",
        thumbnail_url="",
        lowest_price=20_000,
        oliveyoung_available=False,
        sales_status="ON_SALE",
        stock_status="IN_STOCK",
        available_quantity=10,
        in_stock=True,
    )
    signals = home_sections._ProductSignals(
        key_ingredients=(),
        effects=(),
        tag_effect="",
        tag_ingredient="",
        ingredient_codes=(),
        effect_codes=(),
        max_effect_score=0.7,
        max_evidence_score=0.6,
    )
    context = home_sections._ForYouContext(
        skin_type="normal",
        sensitivity="medium",
        request_skin_type=None,
        request_sensitivity=None,
        concern=None,
        effect=None,
        manual_skin_type=None,
        manual_sensitivity=None,
        skin_test_context=None,
        behavior_context=None,
        sources=("fallback",),
    )

    baseline = home_sections._for_you_score(product, signals, None, 0.5, context)
    popular = home_sections._for_you_score(product, signals, None, 0.9, context)
    oliveyoung = home_sections._for_you_score(
        replace(product, oliveyoung_available=True),
        signals,
        None,
        0.5,
        context,
    )

    assert popular > baseline
    assert oliveyoung == pytest.approx(
        min(1.0, baseline + home_sections.OLIVEYOUNG_AVAILABILITY_BONUS)
    )


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


def _rollup_home_snapshots(db_engine: Engine) -> None:
    _rollup_home_coarse_features(db_engine)
    with Session(db_engine) as session:
        rollup_home_section_snapshots(session)
        session.commit()


def _rollup_home_coarse_features(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        rollup_product_recommendation_features(session)
        rollup_product_recommendation_coarse_features(session)
        rollup_home_evidence_pick_features(session)
        session.commit()


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
