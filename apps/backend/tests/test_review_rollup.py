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
    # OliveYoung seed의 MONTH_USE·verified 값은 리뷰 간 변별력이 없으므로
    # helpful만 남는다. helpful=20 → 1.10.
    assert calculate_review_weight(
        source="oliveyoung",
        review_type="MONTH_USE",
        verified_purchase=True,
        helpful_count=20,
    ) == pytest.approx(1.10)
    # 자사몰 리뷰는 표시·정보 추출에는 남지만 추천 점수 기여는 0이다.
    assert calculate_review_weight(
        source="mubarelle",
        review_type="GENERAL",
        verified_purchase=True,
        helpful_count=0,
    ) == pytest.approx(0.0)
    # 다른 소스는 별도 계약이 생기기 전까지 기존 필드 배율을 보존한다.
    assert calculate_review_weight(
        source="partner",
        review_type="MONTH_USE",
        verified_purchase=True,
        helpful_count=20,
    ) == pytest.approx(1.3915)
    assert kish_effective_sample_size(2.0, 2.0) == pytest.approx(2.0)
    assert calculate_bayesian_mean(5.0, 20.0, 3.0) == pytest.approx(4.0)
    assert calculate_month_consistency_score(5.0, 3.0) == pytest.approx(0.5)
    quality, confidence = calculate_review_quality_score(
        rating_score=1.0,
        repurchase_score=1.0,
        effective_sample_size=20.0,
    )
    assert confidence == pytest.approx(0.5)
    assert quality == pytest.approx(0.75)

    quality_with_low_repurchase, _ = calculate_review_quality_score(
        rating_score=1.0,
        repurchase_score=0.0,
        effective_sample_size=20.0,
    )
    assert quality_with_low_repurchase == pytest.approx(0.65)

    quality_without_repurchase, _ = calculate_review_quality_score(
        rating_score=1.0,
        repurchase_score=None,
        effective_sample_size=20.0,
    )
    assert quality_without_repurchase == pytest.approx(0.75)


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
        expected_quality, expected_confidence = calculate_review_quality_score(
            rating_score=float(metric.rating_score),
            repurchase_score=float(metric.repurchase_score),
            effective_sample_size=float(metric.effective_sample_size),
        )
        assert float(metric.review_quality_score) == pytest.approx(
            expected_quality,
            abs=1e-6,
        )
        assert float(metric.confidence) == pytest.approx(
            expected_confidence,
            abs=1e-6,
        )
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


def test_mubarelle_reviews_are_visible_but_do_not_change_recommendation_scores(
    db_engine: Engine,
) -> None:
    computed_at = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(db_engine) as session:
        product_id = int(
            session.execute(select(Product.id).order_by(Product.id)).scalars().first()
        )
        external_review = ProductReview(
            review_code="rollup-external-score-001",
            product_id=product_id,
            source="oliveyoung",
            source_review_id="rollup-external-score-source-001",
            status="PUBLISHED",
            review_type="MONTH_USE",
            rating=1,
            review_text="외부 리뷰",
            reviewed_at=computed_at - timedelta(days=3650),
            is_repurchase_review=False,
            verified_purchase=None,
            helpful_count=0,
            source_has_photo=False,
            published_at=computed_at,
        )
        session.add(external_review)
        session.flush()
        session.add(
            ProductReviewProfileLabel(
                review_id=external_review.id,
                dimension="SKIN_TYPE",
                value_code="dry",
                source_label="건성",
                mapping_source="skin_type",
                mapping_confidence=Decimal("1.0"),
            )
        )
        session.commit()

        rollup_product_review_metrics(session, computed_at=computed_at)
        session.commit()
        metric = session.scalar(
            select(ProductReviewMetric).where(ProductReviewMetric.product_id == product_id)
        )
        segment = session.scalar(
            select(ProductReviewSegmentMetric).where(
                ProductReviewSegmentMetric.product_id == product_id,
                ProductReviewSegmentMetric.dimension == "SKIN_TYPE",
                ProductReviewSegmentMetric.value_code == "dry",
            )
        )
        assert metric is not None
        assert segment is not None
        score_snapshot = (
            metric.weighted_average_rating,
            metric.bayesian_rating,
            metric.bayesian_repurchase_rate,
            metric.effective_sample_size,
            metric.review_quality_score,
            segment.weighted_average_rating,
            segment.effective_sample_size,
            segment.total_affinity_score,
        )

        first_party_review = ProductReview(
            review_code="rollup-first-party-info-001",
            product_id=product_id,
            source="mubarelle",
            source_review_id="rollup-first-party-info-source-001",
            status="PUBLISHED",
            review_type="GENERAL",
            rating=5,
            review_text="자사몰 구매 리뷰",
            reviewed_at=computed_at,
            is_repurchase_review=True,
            verified_purchase=True,
            helpful_count=20,
            source_has_photo=True,
            published_at=computed_at,
        )
        session.add(first_party_review)
        session.flush()
        session.add(
            ProductReviewProfileLabel(
                review_id=first_party_review.id,
                dimension="SKIN_TYPE",
                value_code="dry",
                source_label="건성",
                mapping_source="skin_type",
                mapping_confidence=Decimal("1.0"),
            )
        )
        session.commit()

        rollup_product_review_metrics(session, computed_at=computed_at)
        session.commit()
        session.refresh(metric)
        session.refresh(segment)

        # 공개 요약과 정보 추출용 통계에는 자사몰 리뷰가 그대로 남는다.
        assert metric.review_count == 2
        assert metric.rating_count == 2
        assert metric.rating_1_count == 1
        assert metric.rating_5_count == 1
        assert metric.average_rating == Decimal("3.0000")
        assert metric.source_photo_marker_count == 1
        assert metric.profile_labeled_review_count == 2
        assert segment.review_count == 1

        # 품질·프로필 affinity·카테고리 prior에 쓰는 가중 통계는 변하지 않는다.
        assert (
            metric.weighted_average_rating,
            metric.bayesian_rating,
            metric.bayesian_repurchase_rate,
            metric.effective_sample_size,
            metric.review_quality_score,
            segment.weighted_average_rating,
            segment.effective_sample_size,
            segment.total_affinity_score,
        ) == score_snapshot


def test_mubarelle_only_product_keeps_summary_without_score_or_affinity(
    db_engine: Engine,
) -> None:
    computed_at = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(db_engine) as session:
        product_id = int(
            session.execute(select(Product.id).order_by(Product.id)).scalars().first()
        )
        review = ProductReview(
            review_code="rollup-first-party-only-001",
            product_id=product_id,
            source="mubarelle",
            source_review_id="rollup-first-party-only-source-001",
            status="PUBLISHED",
            review_type="GENERAL",
            rating=5,
            review_text="자사몰 리뷰만 존재",
            reviewed_at=computed_at,
            is_repurchase_review=True,
            verified_purchase=True,
            helpful_count=20,
            source_has_photo=True,
            published_at=computed_at,
        )
        session.add(review)
        session.flush()
        session.add(
            ProductReviewProfileLabel(
                review_id=review.id,
                dimension="SKIN_TYPE",
                value_code="dry",
                source_label="건성",
                mapping_source="skin_type",
                mapping_confidence=Decimal("1.0"),
            )
        )
        session.commit()

        result = rollup_product_review_metrics(
            session,
            product_id=product_id,
            computed_at=computed_at,
        )
        session.commit()
        metric = session.scalar(
            select(ProductReviewMetric).where(ProductReviewMetric.product_id == product_id)
        )

        assert metric is not None
        assert result.reviews_rolled_up == 1
        assert result.segments_updated == 0
        assert metric.review_count == 1
        assert metric.average_rating == Decimal("5.0000")
        assert metric.source_photo_marker_count == 1
        assert metric.profile_labeled_review_count == 1
        assert metric.weight_sum == Decimal("0.000000")
        assert metric.effective_sample_size == Decimal("0.000000")
        assert metric.confidence == Decimal("0.000000")
        assert metric.review_quality_score == Decimal("0.500000")
        assert session.scalar(
            select(func.count(ProductReviewSegmentMetric.id)).where(
                ProductReviewSegmentMetric.product_id == product_id
            )
        ) == 0


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
