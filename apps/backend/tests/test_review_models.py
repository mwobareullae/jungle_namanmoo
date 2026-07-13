from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.catalog import Product
from app.db.models.review import (
    ProductReview,
    ProductReviewMetric,
    ProductReviewProfileLabel,
    ProductReviewSegmentMetric,
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


def _product_id(session: Session) -> int:
    return int(session.execute(select(Product.id).order_by(Product.id)).scalars().first())


def test_review_models_store_source_profile_and_neutral_metrics(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        product_id = _product_id(session)
        review = ProductReview(
            review_code="rev_test_001",
            product_id=product_id,
            source="oliveyoung",
            source_review_id="source-001",
            status="PUBLISHED",
            review_type="MONTH_USE",
            rating=5,
            review_text="한 달 사용 후기",
            helpful_count=3,
            source_has_photo=True,
            source_content_hash="a" * 64,
            profile_mapping_version="review_profile_v1",
        )
        session.add(review)
        session.flush()
        session.add(
            ProductReviewProfileLabel(
                review_id=review.id,
                dimension="SKIN_TYPE",
                value_code="dry",
                source_label="건성",
                mapping_source="dedicated",
                mapping_confidence=Decimal("1.0"),
            )
        )
        metric = ProductReviewMetric(
            product_id=product_id,
            bayesian_photo_rate=Decimal("0.250000"),
            photo_rate_score=Decimal("0.250000"),
        )
        segment = ProductReviewSegmentMetric(
            product_id=product_id,
            dimension="SKIN_TYPE",
            value_code="dry",
        )
        session.add_all([metric, segment])
        session.commit()

        assert metric.review_quality_score == Decimal("0.500000")
        assert metric.bayesian_photo_rate == Decimal("0.250000")
        assert metric.photo_rate_score == Decimal("0.250000")
        assert metric.score_version == "review_quality_v2"
        assert segment.total_affinity_score == Decimal("0.500000")
        assert segment.score_version == "review_quality_v2"
        assert review.source_has_photo is True


def test_review_model_rejects_photo_rate_outside_range(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        session.add(
            ProductReviewMetric(
                product_id=_product_id(session),
                bayesian_photo_rate=Decimal("1.100000"),
                photo_rate_score=Decimal("0.500000"),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_review_model_rejects_rating_outside_range(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        session.add(
            ProductReview(
                review_code="rev_invalid_rating",
                product_id=_product_id(session),
                source="oliveyoung",
                source_review_id="source-invalid-rating",
                status="PUBLISHED",
                review_type="MONTH_USE",
                rating=6,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_review_model_allows_content_free_deleted_tombstone(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        review = ProductReview(
            review_code="rev_deleted_tombstone",
            product_id=_product_id(session),
            source="mubarelle",
            source_review_id="rev_deleted_tombstone",
            status="DELETED",
            review_type="GENERAL",
            rating=None,
            review_text=None,
        )
        session.add(review)
        session.commit()

        assert review.status == "DELETED"
        assert review.rating is None
        assert review.review_text is None


def test_review_model_rejects_duplicate_source_review(db_engine: Engine) -> None:
    with Session(db_engine) as session:
        product_id = _product_id(session)
        session.add_all(
            [
                ProductReview(
                    review_code="rev_duplicate_001",
                    product_id=product_id,
                    source="oliveyoung",
                    source_review_id="source-duplicate",
                    status="PUBLISHED",
                    review_type="MONTH_USE",
                    rating=4,
                ),
                ProductReview(
                    review_code="rev_duplicate_002",
                    product_id=product_id,
                    source="oliveyoung",
                    source_review_id="source-duplicate",
                    status="PUBLISHED",
                    review_type="MONTH_USE",
                    rating=5,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_review_model_allows_same_source_review_id_for_different_products(
    db_engine: Engine,
) -> None:
    with Session(db_engine) as session:
        product_ids = list(
            session.execute(select(Product.id).order_by(Product.id).limit(2)).scalars()
        )
        assert len(product_ids) == 2
        session.add_all(
            [
                ProductReview(
                    review_code="rev_product_scope_001",
                    product_id=int(product_ids[0]),
                    source="oliveyoung",
                    source_review_id="source-product-local",
                    status="PUBLISHED",
                    review_type="MONTH_USE",
                    rating=4,
                ),
                ProductReview(
                    review_code="rev_product_scope_002",
                    product_id=int(product_ids[1]),
                    source="oliveyoung",
                    source_review_id="source-product-local",
                    status="PUBLISHED",
                    review_type="MONTH_USE",
                    rating=5,
                ),
            ]
        )
        session.commit()

        assert session.scalar(select(ProductReview.id).limit(1)) is not None
