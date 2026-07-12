from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.auth import User
from app.db.models.catalog import Product
from app.db.models.commerce import Order, OrderItem, Seller
from app.db.models.review import ProductReview, ProductReviewMetric, ProductReviewProfileLabel
from app.db.models.skin import SkinProfile
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


def test_delivered_order_owner_can_create_verified_review(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-create@example.com", nickname="reviewer")
    order_item_id = _create_order_item(
        db_engine,
        email="review-create@example.com",
        item_status="DELIVERED",
    )
    with Session(db_engine) as session:
        user_id = int(
            session.scalar(select(User.id).where(User.email == "review-create@example.com"))
        )
        session.add(
            SkinProfile(
                user_id=user_id,
                skin_type="건성",
                sensitivity="높음",
                skin_type_confidence=Decimal("1.0000"),
                sensitivity_confidence=Decimal("0.9000"),
                concern_profile_json={"concerns": ["concern_pore"]},
                source="manual",
            )
        )
        session.commit()

    response = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "  좋아요  ",
            "is_repurchase_review": True,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PUBLISHED"
    assert data["review"]["review_text"] == "좋아요"
    assert data["review"]["verified_purchase"] is True
    assert data["review_summary"]["review_count"] == 5
    assert {
        (label["dimension"], label["value_code"])
        for label in data["review"]["profile_labels"]
    } == {
        ("SKIN_TYPE", "dry"),
        ("SENSITIVITY", "high"),
        ("SKIN_CONCERN", "concern_pore"),
    }

    with Session(db_engine) as session:
        review = session.scalar(
            select(ProductReview).where(ProductReview.order_item_id == order_item_id)
        )
        metric = session.scalar(
            select(ProductReviewMetric).where(ProductReviewMetric.product_id == review.product_id)
        )
        assert review.source == "mubarelle"
        assert review.source_review_id == review.review_code
        assert review.review_text == "좋아요"
        assert metric.review_count == 5


def test_review_create_requires_delivered_order_and_rejects_duplicate(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-eligibility@example.com", nickname="eligibility")
    shipped_item_id = _create_order_item(
        db_engine,
        email="review-eligibility@example.com",
        item_status="SHIPPED",
    )

    not_delivered = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": shipped_item_id,
            "rating": 4,
            "review_text": "아직 배송 중이에요",
        },
    )
    assert not_delivered.status_code == 409
    assert not_delivered.json()["error"]["code"] == "REVIEW_NOT_ELIGIBLE"

    delivered_item_id = _create_order_item(
        db_engine,
        email="review-eligibility@example.com",
        item_status="DELIVERED",
    )
    payload = {
        "order_item_id": delivered_item_id,
        "rating": 4,
        "review_text": "배송완료 후 작성",
    }
    assert client.post("/api/products/prod_001/reviews", json=payload).status_code == 201
    duplicate = client.post("/api/products/prod_001/reviews", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "REVIEW_ALREADY_EXISTS"


def test_review_create_requires_login_and_nonblank_text(client: TestClient) -> None:
    unauthorized = client.post(
        "/api/products/prod_001/reviews",
        json={"order_item_id": 1, "rating": 5, "review_text": "좋음"},
    )
    assert unauthorized.status_code == 401

    _signup(client, email="review-validation@example.com", nickname="validation")
    invalid = client.post(
        "/api/products/prod_001/reviews",
        json={"order_item_id": 1, "rating": 5, "review_text": "   "},
    )
    assert invalid.status_code == 400


def test_review_create_accepts_one_character_and_rejects_over_2000_characters(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-length@example.com", nickname="length")
    first_item_id = _create_order_item(
        db_engine,
        email="review-length@example.com",
        item_status="DELIVERED",
    )
    one_character = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": first_item_id,
            "rating": 5,
            "review_text": "굿",
        },
    )
    assert one_character.status_code == 201

    second_item_id = _create_order_item(
        db_engine,
        email="review-length@example.com",
        item_status="DELIVERED",
    )
    too_long = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": second_item_id,
            "rating": 5,
            "review_text": "a" * 2001,
        },
    )
    assert too_long.status_code == 400


def test_review_create_enforces_order_ownership_and_product_match(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-order-owner@example.com", nickname="order-owner")
    order_item_id = _create_order_item(
        db_engine,
        email="review-order-owner@example.com",
        item_status="DELIVERED",
    )

    mismatch = client.post(
        "/api/products/prod_002/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "상품 불일치",
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "REVIEW_PRODUCT_MISMATCH"

    _signup(client, email="review-order-other@example.com", nickname="order-other")
    not_owner = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "다른 사용자 주문",
        },
    )
    assert not_owner.status_code == 404
    assert not_owner.json()["error"]["code"] == "REVIEW_ORDER_ITEM_NOT_FOUND"


def test_review_owner_can_update_without_changing_original_reviewed_at(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-update@example.com", nickname="update-owner")
    order_item_id = _create_order_item(
        db_engine,
        email="review-update@example.com",
        item_status="DELIVERED",
    )
    created = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 2,
            "review_text": "처음 후기",
            "is_repurchase_review": False,
        },
    ).json()
    review_id = created["review_id"]
    original_reviewed_at = created["review"]["reviewed_at"]

    response = client.patch(
        f"/api/reviews/{review_id}",
        json={
            "rating": 5,
            "review_text": "  수정한 후기  ",
            "is_repurchase_review": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["review"]["rating"] == 5
    assert data["review"]["review_text"] == "수정한 후기"
    assert data["review"]["is_repurchase_review"] is True
    assert data["review"]["reviewed_at"] == original_reviewed_at
    assert data["review_summary"]["average_rating"] == 3.6


def test_review_delete_redacts_content_updates_rollup_and_allows_recreate(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-delete@example.com", nickname="delete-owner")
    order_item_id = _create_order_item(
        db_engine,
        email="review-delete@example.com",
        item_status="DELIVERED",
    )
    created = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "삭제할 후기",
        },
    ).json()
    review_id = created["review_id"]

    deleted = client.delete(f"/api/reviews/{review_id}")

    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"
    assert deleted.json()["review"] is None
    assert deleted.json()["review_summary"]["review_count"] == 4
    assert review_id not in {
        item["review_id"]
        for item in client.get("/api/products/prod_001/reviews").json()["items"]
    }
    with Session(db_engine) as session:
        review = session.scalar(
            select(ProductReview).where(ProductReview.review_code == review_id)
        )
        label_count = int(
            session.scalar(
                select(func.count(ProductReviewProfileLabel.id)).where(
                    ProductReviewProfileLabel.review_id == review.id
                )
            )
            or 0
        )
        assert review.status == "DELETED"
        assert review.rating is None
        assert review.review_text is None
        assert review.verified_purchase is None
        assert label_count == 0

    repeated_delete = client.delete(f"/api/reviews/{review_id}")
    assert repeated_delete.status_code == 200
    assert repeated_delete.json()["review_summary"]["review_count"] == 4

    recreated = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 4,
            "review_text": "다시 작성한 후기",
        },
    )
    assert recreated.status_code == 201
    assert recreated.json()["review_id"] == review_id
    assert recreated.json()["review_summary"]["review_count"] == 5


def test_other_user_cannot_update_or_delete_review(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-owner@example.com", nickname="real-owner")
    order_item_id = _create_order_item(
        db_engine,
        email="review-owner@example.com",
        item_status="DELIVERED",
    )
    review_id = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "내 후기",
        },
    ).json()["review_id"]

    _signup(client, email="review-attacker@example.com", nickname="attacker")
    patch_response = client.patch(
        f"/api/reviews/{review_id}",
        json={"review_text": "가로챈 후기"},
    )
    delete_response = client.delete(f"/api/reviews/{review_id}")

    assert patch_response.status_code == 404
    assert patch_response.json()["error"]["code"] == "REVIEW_NOT_FOUND"
    assert delete_response.status_code == 404
    assert delete_response.json()["error"]["code"] == "REVIEW_NOT_FOUND"


def test_my_reviews_and_reviewable_items_expose_ownership_state(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-my@example.com", nickname="reviewer")
    order_item_id = _create_order_item(
        db_engine,
        email="review-my@example.com",
        item_status="DELIVERED",
    )
    review_id = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "내 리뷰 목록 확인",
        },
    ).json()["review_id"]

    my_reviews = client.get("/api/me/reviews")
    reviewable = client.get("/api/me/reviewable-order-items")
    public_items = client.get("/api/products/prod_001/reviews").json()["items"]
    public_review = next(item for item in public_items if item["review_id"] == review_id)

    assert my_reviews.status_code == 200
    assert my_reviews.json()["total_items"] == 1
    assert my_reviews.json()["items"][0]["review"]["review_id"] == review_id
    assert my_reviews.json()["items"][0]["review"]["is_mine"] is True
    assert my_reviews.json()["items"][0]["review"]["can_edit"] is True
    assert my_reviews.json()["items"][0]["review"]["can_delete"] is True
    assert reviewable.status_code == 200
    assert reviewable.json()["items"][0]["order_item_id"] == order_item_id
    assert reviewable.json()["items"][0]["review_status"] == "PUBLISHED"
    assert reviewable.json()["items"][0]["can_write"] is False
    assert public_review["author"]["display_name"] == "r*******"
    assert public_review["is_mine"] is True

    client.delete(f"/api/reviews/{review_id}")
    after_delete = client.get("/api/me/reviewable-order-items").json()["items"][0]
    assert after_delete["review_id"] == review_id
    assert after_delete["review_status"] == "DELETED"
    assert after_delete["can_write"] is True


def test_other_user_sees_public_author_but_not_edit_permissions(
    client: TestClient,
    db_engine: Engine,
) -> None:
    _signup(client, email="review-public-owner@example.com", nickname="owner")
    order_item_id = _create_order_item(
        db_engine,
        email="review-public-owner@example.com",
        item_status="DELIVERED",
    )
    review_id = client.post(
        "/api/products/prod_001/reviews",
        json={
            "order_item_id": order_item_id,
            "rating": 5,
            "review_text": "공개 작성자 확인",
        },
    ).json()["review_id"]

    _signup(client, email="review-public-reader@example.com", nickname="reader")
    item = next(
        item
        for item in client.get("/api/products/prod_001/reviews").json()["items"]
        if item["review_id"] == review_id
    )

    assert item["author"]["display_name"] == "o****"
    assert item["is_mine"] is False
    assert item["can_edit"] is False
    assert item["can_delete"] is False


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


def _create_order_item(
    engine: Engine,
    *,
    email: str,
    item_status: str,
) -> int:
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        product = session.scalar(select(Product).where(Product.product_code == "prod_001"))
        seller = session.scalar(select(Seller).order_by(Seller.id))
        sequence = int(session.scalar(select(func.count(Order.id))) or 0) + 1
        order = Order(
            order_code=f"order-review-{sequence}",
            user_id=int(user.id),
            idempotency_key=f"review-order-{sequence}",
            status="DELIVERED" if item_status == "DELIVERED" else "SHIPPED",
            subtotal_amount=10000,
            shipping_fee=0,
            discount_amount=0,
            total_amount=10000,
            currency="KRW",
            item_count=1,
            total_quantity=1,
        )
        session.add(order)
        session.flush()
        order_item = OrderItem(
            order_id=int(order.id),
            product_id=int(product.id),
            seller_id=int(seller.id),
            product_name_snapshot=product.product_name,
            brand_name_snapshot="brand",
            seller_name_snapshot=seller.display_name,
            unit_price=10000,
            quantity=1,
            line_subtotal=10000,
            line_discount_amount=0,
            line_total=10000,
            currency="KRW",
            status=item_status,
        )
        session.add(order_item)
        session.commit()
        return int(order_item.id)
