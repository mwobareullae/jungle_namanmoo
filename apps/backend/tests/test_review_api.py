from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.review import ProductReview, ProductReviewProfileLabel
from app.db.session import get_db
from app.main import app
from app.services.db_seed import seed_database
from app.services.elasticsearch_client import default_elasticsearch_client_provider
from app.services.review_rollup import rollup_product_review_metrics
from tests.test_data_loader import EXAMPLES_DIR


COMPUTED_AT = datetime(2026, 7, 12, tzinfo=UTC)


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
        product_id = int(
            session.scalar(select(Product.id).where(Product.product_code == "prod_001"))
        )
        reviews = [
            _review(
                "review-api-latest",
                product_id,
                days_ago=1,
                rating=4,
                helpful_count=1,
                review_type="GENERAL",
                repurchase=False,
                verified_purchase=None,
            ),
            _review(
                "review-api-helpful",
                product_id,
                days_ago=2,
                rating=5,
                helpful_count=10,
                review_type="MONTH_USE",
                repurchase=True,
                verified_purchase=None,
            ),
            _review(
                "review-api-low",
                product_id,
                days_ago=3,
                rating=1,
                helpful_count=2,
                review_type="MONTH_USE",
                repurchase=True,
                verified_purchase=None,
            ),
            _review(
                "review-api-old",
                product_id,
                days_ago=4,
                rating=3,
                helpful_count=0,
                review_type="GENERAL",
                repurchase=False,
                verified_purchase=None,
            ),
            _review(
                "review-api-hidden",
                product_id,
                days_ago=0,
                rating=5,
                helpful_count=99,
                review_type="MONTH_USE",
                repurchase=True,
                verified_purchase=None,
                status="HIDDEN",
            ),
        ]
        session.add_all(reviews)
        session.flush()
        session.add_all(
            [
                _label(reviews[0].id, "SKIN_TYPE", "dry", "건성"),
                _label(
                    reviews[0].id,
                    "SKIN_CONCERN",
                    "concern_sensitive",
                    "민감성",
                ),
                _label(reviews[1].id, "SKIN_TYPE", "oily", "지성"),
                _label(reviews[1].id, "SENSITIVITY", "high", "민감성"),
                _label(reviews[2].id, "SKIN_TONE", "summer_cool", "여름쿨톤"),
            ]
        )
        session.commit()
        rollup_product_review_metrics(session, computed_at=COMPUTED_AT)
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def client(db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    def override_get_db():
        with Session(db_engine) as session:
            yield session

    monkeypatch.setattr(default_elasticsearch_client_provider, "mode", "postgres")
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_product_detail_includes_public_review_summary(client: TestClient) -> None:
    response = client.get("/api/products/prod_001")

    assert response.status_code == 200
    summary = response.json()["review_summary"]
    assert summary == {
        "review_count": 4,
        "average_rating": 3.25,
        "rating_distribution": {"1": 1, "2": 0, "3": 1, "4": 1, "5": 1},
        "general_review_count": 2,
        "month_use_review_count": 2,
        "repurchase_known_count": 4,
        "repurchase_review_count": 2,
        "repurchase_rate": 0.5,
        "profile_labeled_review_count": 3,
        "last_reviewed_at": "2026-07-11T00:00:00Z",
    }
    assert "review_quality_score" not in summary
    assert "bayesian_rating" not in summary


def test_review_list_uses_cursor_without_duplicates(client: TestClient) -> None:
    first = client.get(
        "/api/products/prod_001/reviews",
        params={"limit": 2, "sort": "latest"},
    )
    assert first.status_code == 200
    first_data = first.json()
    assert [item["review_id"] for item in first_data["items"]] == [
        "review-api-latest",
        "review-api-helpful",
    ]
    assert first_data["has_next"] is True
    assert first_data["next_cursor"]

    second = client.get(
        "/api/products/prod_001/reviews",
        params={
            "limit": 2,
            "sort": "latest",
            "cursor": first_data["next_cursor"],
        },
    )
    assert second.status_code == 200
    second_data = second.json()
    assert [item["review_id"] for item in second_data["items"]] == [
        "review-api-low",
        "review-api-old",
    ]
    assert second_data["has_next"] is False
    assert second_data["next_cursor"] is None
    all_ids = {
        item["review_id"] for item in first_data["items"] + second_data["items"]
    }
    assert len(all_ids) == 4
    assert "review-api-hidden" not in all_ids


def test_review_sorts_and_filters_are_applied(client: TestClient) -> None:
    helpful = client.get(
        "/api/products/prod_001/reviews",
        params={"sort": "helpful"},
    ).json()
    assert helpful["items"][0]["review_id"] == "review-api-helpful"

    rating_low = client.get(
        "/api/products/prod_001/reviews",
        params={"sort": "rating_low"},
    ).json()
    assert rating_low["items"][0]["review_id"] == "review-api-low"

    filtered = client.get(
        "/api/products/prod_001/reviews",
        params={
            "skin_type": "dry",
            "concern": "concern_sensitive",
            "rating": 4,
            "repurchase": False,
            "review_type": "GENERAL",
        },
    )
    assert filtered.status_code == 200
    assert [item["review_id"] for item in filtered.json()["items"]] == [
        "review-api-latest"
    ]

    sensitivity = client.get(
        "/api/products/prod_001/reviews",
        params={"sensitivity": "high"},
    ).json()
    assert [item["review_id"] for item in sensitivity["items"]] == [
        "review-api-helpful"
    ]


def test_review_response_hides_internal_and_unavailable_fields(client: TestClient) -> None:
    item = client.get(
        "/api/products/prod_001/reviews",
        params={"skin_type": "dry"},
    ).json()["items"][0]

    assert item["author"] is None
    assert item["verified_purchase"] is None
    assert item["media"] == []
    assert item["profile_labels"] == [
        {
            "dimension": "SKIN_CONCERN",
            "value_code": "concern_sensitive",
            "display_label": "민감성",
        },
        {
            "dimension": "SKIN_TYPE",
            "value_code": "dry",
            "display_label": "건성",
        },
    ]
    assert {
        "source",
        "source_review_id",
        "user_id",
        "source_metadata_json",
    }.isdisjoint(item)


def test_review_list_rejects_invalid_cursor_and_missing_product(client: TestClient) -> None:
    invalid = client.get(
        "/api/products/prod_001/reviews",
        params={"cursor": "not-a-cursor"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_CURSOR"

    missing = client.get("/api/products/missing-product/reviews")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def _review(
    review_code: str,
    product_id: int,
    *,
    days_ago: int,
    rating: int,
    helpful_count: int,
    review_type: str,
    repurchase: bool,
    verified_purchase: bool | None,
    status: str = "PUBLISHED",
) -> ProductReview:
    reviewed_at = COMPUTED_AT - timedelta(days=days_ago)
    return ProductReview(
        review_code=review_code,
        product_id=product_id,
        source="oliveyoung",
        source_review_id=f"source-{review_code}",
        status=status,
        review_type=review_type,
        rating=rating,
        review_text=f"{review_code} 본문",
        reviewed_at=reviewed_at,
        option_text="기본 옵션",
        is_repurchase_review=repurchase,
        verified_purchase=verified_purchase,
        helpful_count=helpful_count,
        source_has_photo=True,
        source_badge_labels_json=["한달사용"] if review_type == "MONTH_USE" else None,
        source_metadata_json={"private": "not-exposed"},
        published_at=reviewed_at,
    )


def _label(
    review_id: int,
    dimension: str,
    value_code: str,
    source_label: str,
) -> ProductReviewProfileLabel:
    return ProductReviewProfileLabel(
        review_id=review_id,
        dimension=dimension,
        value_code=value_code,
        source_label=source_label,
        mapping_source="test",
        mapping_confidence=Decimal("1.0"),
    )
