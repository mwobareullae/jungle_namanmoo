from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
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
from app.services.review_rollup import (
    REVIEW_SCORE_VERSION,
    calculate_bayesian_mean,
    calculate_month_consistency_score,
    calculate_review_quality_score,
    calculate_review_recency_weight,
    calculate_review_weight,
    kish_effective_sample_size,
    rollup_product_review_metrics,
)
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


def test_review_weight_and_statistical_formulas() -> None:
    computed_at = datetime(2026, 7, 12, tzinfo=UTC)
    assert calculate_review_weight(
        source="oliveyoung",
        review_type="MONTH_USE",
        verified_purchase=True,
        helpful_count=20,
        reviewed_at=computed_at,
        computed_at=computed_at,
    ) == pytest.approx(1.3915)
    assert calculate_review_recency_weight(
        computed_at - timedelta(days=730),
        computed_at,
    ) == pytest.approx(0.75)
    assert calculate_review_recency_weight(None, computed_at) == pytest.approx(0.75)
    assert kish_effective_sample_size(2.0, 2.0) == pytest.approx(2.0)
    assert calculate_bayesian_mean(5.0, 20.0, 3.0) == pytest.approx(4.0)
    assert calculate_month_consistency_score(5.0, 3.0) == pytest.approx(0.5)
    quality, confidence = calculate_review_quality_score(
        rating_score=1.0,
        repurchase_score=1.0,
        month_consistency_score=1.0,
        effective_sample_size=20.0,
    )
    assert confidence == pytest.approx(0.5)
    assert quality == pytest.approx(0.75)


def test_review_rollup_builds_product_and_segment_metrics_idempotently(
    db_engine: Engine,
) -> None:
    computed_at = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(db_engine) as session:
        product_id = int(
            session.execute(select(Product.id).order_by(Product.id)).scalars().first()
        )
        reviews = [
            ProductReview(
                review_code="rollup-review-001",
                product_id=product_id,
                source="oliveyoung",
                source_review_id="rollup-source-001",
                status="PUBLISHED",
                review_type="GENERAL",
                rating=5,
                review_text="일반 후기",
                reviewed_at=computed_at,
                is_repurchase_review=True,
                verified_purchase=True,
                helpful_count=20,
                source_has_photo=False,
                published_at=computed_at,
            ),
            ProductReview(
                review_code="rollup-review-002",
                product_id=product_id,
                source="oliveyoung",
                source_review_id="rollup-source-002",
                status="PUBLISHED",
                review_type="MONTH_USE",
                rating=3,
                review_text="한달 후기",
                reviewed_at=computed_at - timedelta(days=730),
                is_repurchase_review=False,
                verified_purchase=False,
                helpful_count=0,
                source_has_photo=True,
                published_at=computed_at - timedelta(days=730),
            ),
            ProductReview(
                review_code="rollup-review-003",
                product_id=product_id,
                source="oliveyoung",
                source_review_id="rollup-source-003",
                status="PUBLISHED",
                review_type="MONTH_USE",
                rating=4,
                review_text="재구매 한달 후기",
                reviewed_at=computed_at - timedelta(days=30),
                is_repurchase_review=True,
                verified_purchase=None,
                helpful_count=2,
                source_has_photo=False,
                published_at=computed_at - timedelta(days=30),
            ),
        ]
        session.add_all(reviews)
        session.flush()
        session.add_all(
            [
                ProductReviewProfileLabel(
                    review_id=reviews[0].id,
                    dimension="SKIN_TYPE",
                    value_code="dry",
                    source_label="건성",
                    mapping_source="skin_type",
                    mapping_confidence=Decimal("1.0"),
                ),
                ProductReviewProfileLabel(
                    review_id=reviews[1].id,
                    dimension="SKIN_TYPE",
                    value_code="dry",
                    source_label="약건성",
                    mapping_source="skin_type",
                    mapping_confidence=Decimal("0.7"),
                ),
                ProductReviewProfileLabel(
                    review_id=reviews[1].id,
                    dimension="SKIN_CONCERN",
                    value_code="concern_sensitive",
                    source_label="민감성",
                    mapping_source="skin_concern",
                    mapping_confidence=Decimal("1.0"),
                ),
            ]
        )
        session.commit()

        first = rollup_product_review_metrics(session, computed_at=computed_at)
        session.commit()
        metric = session.scalar(
            select(ProductReviewMetric).where(ProductReviewMetric.product_id == product_id)
        )
        assert metric is not None
        assert first.products_updated == 1
        assert first.segments_updated == 2
        assert metric.review_count == 3
        assert metric.rating_count == 3
        assert metric.rating_3_count == 1
        assert metric.rating_4_count == 1
        assert metric.rating_5_count == 1
        assert metric.general_review_count == 1
        assert metric.month_use_review_count == 2
        assert metric.repurchase_known_count == 3
        assert metric.repurchase_review_count == 2
        assert metric.profile_labeled_review_count == 2
        assert metric.source_photo_marker_count == 1
        assert metric.helpful_count_sum == 22
        assert metric.month_consistency_score is not None
        assert Decimal("0") <= metric.review_quality_score <= Decimal("1")
        assert metric.score_version == REVIEW_SCORE_VERSION

        dry_segment = session.scalar(
            select(ProductReviewSegmentMetric).where(
                ProductReviewSegmentMetric.product_id == product_id,
                ProductReviewSegmentMetric.dimension == "SKIN_TYPE",
                ProductReviewSegmentMetric.value_code == "dry",
            )
        )
        assert dry_segment is not None
        assert dry_segment.review_count == 2
        assert dry_segment.effective_sample_size < Decimal("5")
        assert Decimal("0") <= dry_segment.total_affinity_score <= Decimal("1")
        assert dry_segment.score_version == REVIEW_SCORE_VERSION
        first_snapshot = (
            metric.review_quality_score,
            metric.bayesian_rating,
            dry_segment.total_affinity_score,
            dry_segment.effective_sample_size,
        )

        second = rollup_product_review_metrics(session, computed_at=computed_at)
        session.commit()
        session.refresh(metric)
        session.refresh(dry_segment)
        assert second.products_updated == 1
        assert second.segments_updated == 2
        assert session.scalar(select(func.count(ProductReviewMetric.id))) == 1
        assert session.scalar(select(func.count(ProductReviewSegmentMetric.id))) == 2
        assert (
            metric.review_quality_score,
            metric.bayesian_rating,
            dry_segment.total_affinity_score,
            dry_segment.effective_sample_size,
        ) == first_snapshot


def test_targeted_rollup_removes_stale_metrics_when_reviews_are_hidden(
    db_engine: Engine,
) -> None:
    computed_at = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(db_engine) as session:
        product_id = int(
            session.execute(select(Product.id).order_by(Product.id)).scalars().first()
        )
        review = ProductReview(
            review_code="rollup-hidden-001",
            product_id=product_id,
            source="oliveyoung",
            source_review_id="rollup-hidden-source-001",
            status="PUBLISHED",
            review_type="GENERAL",
            rating=5,
            review_text="게시 후기",
            reviewed_at=computed_at,
            is_repurchase_review=True,
            helpful_count=0,
            published_at=computed_at,
        )
        session.add(review)
        session.commit()
        rollup_product_review_metrics(
            session,
            product_id=product_id,
            computed_at=computed_at,
        )
        session.commit()
        assert session.scalar(
            select(ProductReviewMetric.id).where(ProductReviewMetric.product_id == product_id)
        ) is not None

        review.status = "HIDDEN"
        session.commit()
        result = rollup_product_review_metrics(
            session,
            product_id=product_id,
            computed_at=computed_at,
        )
        session.commit()

        assert result.products_updated == 0
        assert session.scalar(
            select(ProductReviewMetric.id).where(ProductReviewMetric.product_id == product_id)
        ) is None
