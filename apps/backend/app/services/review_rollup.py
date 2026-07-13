from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.performance_logging import current_time, elapsed_ms, log_performance_event
from app.db.models.catalog import Product
from app.db.models.review import (
    ProductReview,
    ProductReviewMetric,
    ProductReviewProfileLabel,
    ProductReviewSegmentMetric,
)


REVIEW_SCORE_VERSION = "review_quality_v2"
REVIEW_PRIOR_STRENGTH = 20.0
SEGMENT_MIN_EFFECTIVE_SAMPLE_SIZE = 5.0
REVIEW_STREAM_BATCH_SIZE = 5000

_SCORE_QUANTUM = Decimal("0.000001")
_RATING_QUANTUM = Decimal("0.0001")
_WEIGHT_QUANTUM = Decimal("0.000001")
_PRIOR_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class ProductReviewRollupResult:
    scope: str
    product_id: int | None
    reviews_scanned: int
    reviews_rolled_up: int
    products_updated: int
    segments_updated: int
    score_version: str
    computed_at: datetime
    duration_seconds: float


@dataclass
class _ReviewAccumulator:
    review_count: int = 0
    rating_count: int = 0
    rating_counts: list[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    rating_sum: float = 0.0
    rating_weighted_sum: float = 0.0
    rating_weight_sum: float = 0.0
    rating_weight_square_sum: float = 0.0
    general_review_count: int = 0
    general_rating_count: int = 0
    general_rating_sum: float = 0.0
    general_rating_weighted_sum: float = 0.0
    general_rating_weight_sum: float = 0.0
    month_use_review_count: int = 0
    month_rating_count: int = 0
    month_rating_sum: float = 0.0
    month_rating_weighted_sum: float = 0.0
    month_rating_weight_sum: float = 0.0
    month_weight_sum: float = 0.0
    month_weight_square_sum: float = 0.0
    repurchase_known_count: int = 0
    repurchase_review_count: int = 0
    repurchase_weighted_sum: float = 0.0
    repurchase_weight_sum: float = 0.0
    repurchase_weight_square_sum: float = 0.0
    profile_labeled_review_count: int = 0
    source_photo_marker_count: int = 0
    photo_known_count: int = 0
    photo_weighted_sum: float = 0.0
    photo_weight_sum: float = 0.0
    photo_weight_square_sum: float = 0.0
    helpful_count_sum: int = 0
    weight_sum: float = 0.0
    weight_square_sum: float = 0.0
    last_reviewed_at: datetime | None = None

    def add(
        self,
        *,
        weight: float,
        rating: int | None,
        review_type: str | None,
        is_repurchase_review: bool | None,
        helpful_count: int | None,
        source_has_photo: bool | None,
        reviewed_at: datetime | None,
    ) -> None:
        self.review_count += 1
        self.weight_sum += weight
        self.weight_square_sum += weight * weight
        self.helpful_count_sum += max(0, int(helpful_count or 0))
        if source_has_photo is True:
            self.source_photo_marker_count += 1

        normalized_reviewed_at = _as_utc(reviewed_at)
        if normalized_reviewed_at is not None and (
            self.last_reviewed_at is None or normalized_reviewed_at > self.last_reviewed_at
        ):
            self.last_reviewed_at = normalized_reviewed_at

        is_month_use = review_type == "MONTH_USE"
        if is_month_use:
            self.month_use_review_count += 1
            self.month_weight_sum += weight
            self.month_weight_square_sum += weight * weight
        elif review_type == "GENERAL":
            self.general_review_count += 1

        if rating is not None:
            normalized_rating = int(rating)
            self.rating_count += 1
            self.rating_counts[normalized_rating] += 1
            self.rating_sum += normalized_rating
            self.rating_weighted_sum += weight * normalized_rating
            self.rating_weight_sum += weight
            self.rating_weight_square_sum += weight * weight
            if is_month_use:
                self.month_rating_count += 1
                self.month_rating_sum += normalized_rating
                self.month_rating_weighted_sum += weight * normalized_rating
                self.month_rating_weight_sum += weight
            elif review_type == "GENERAL":
                self.general_rating_count += 1
                self.general_rating_sum += normalized_rating
                self.general_rating_weighted_sum += weight * normalized_rating
                self.general_rating_weight_sum += weight

        if is_repurchase_review is not None:
            self.repurchase_known_count += 1
            self.repurchase_weight_sum += weight
            self.repurchase_weight_square_sum += weight * weight
            if is_repurchase_review:
                self.repurchase_review_count += 1
                self.repurchase_weighted_sum += weight

        if source_has_photo is not None:
            self.photo_known_count += 1
            self.photo_weight_sum += weight
            self.photo_weight_square_sum += weight * weight
            if source_has_photo:
                self.photo_weighted_sum += weight

    @property
    def average_rating(self) -> float | None:
        return _safe_divide(self.rating_sum, self.rating_count)

    @property
    def weighted_average_rating(self) -> float | None:
        return _safe_divide(self.rating_weighted_sum, self.rating_weight_sum)

    @property
    def general_average_rating(self) -> float | None:
        return _safe_divide(self.general_rating_sum, self.general_rating_count)

    @property
    def general_weighted_average_rating(self) -> float | None:
        return _safe_divide(
            self.general_rating_weighted_sum,
            self.general_rating_weight_sum,
        )

    @property
    def month_average_rating(self) -> float | None:
        return _safe_divide(self.month_rating_sum, self.month_rating_count)

    @property
    def month_weighted_average_rating(self) -> float | None:
        return _safe_divide(self.month_rating_weighted_sum, self.month_rating_weight_sum)

    @property
    def repurchase_rate(self) -> float | None:
        return _safe_divide(self.repurchase_review_count, self.repurchase_known_count)

    @property
    def weighted_repurchase_rate(self) -> float | None:
        return _safe_divide(self.repurchase_weighted_sum, self.repurchase_weight_sum)

    @property
    def weighted_photo_rate(self) -> float | None:
        return _safe_divide(self.photo_weighted_sum, self.photo_weight_sum)

    @property
    def photo_effective_sample_size(self) -> float:
        return kish_effective_sample_size(
            self.photo_weight_sum,
            self.photo_weight_square_sum,
        )

    @property
    def effective_sample_size(self) -> float:
        return kish_effective_sample_size(self.weight_sum, self.weight_square_sum)

    @property
    def rating_effective_sample_size(self) -> float:
        return kish_effective_sample_size(
            self.rating_weight_sum,
            self.rating_weight_square_sum,
        )

    @property
    def repurchase_effective_sample_size(self) -> float:
        return kish_effective_sample_size(
            self.repurchase_weight_sum,
            self.repurchase_weight_square_sum,
        )

    @property
    def month_effective_sample_size(self) -> float:
        return kish_effective_sample_size(
            self.month_weight_sum,
            self.month_weight_square_sum,
        )


@dataclass(frozen=True)
class _ProductScore:
    bayesian_rating: float | None
    bayesian_repurchase_rate: float | None


def rollup_product_review_metrics(
    session: Session,
    *,
    product_id: int | None = None,
    computed_at: datetime | None = None,
) -> ProductReviewRollupResult:
    started_at = perf_counter()
    total_started_at = current_time()
    now = _as_utc(computed_at) or datetime.now(UTC)
    stage_durations: dict[str, float] = {}

    stage_started_at = current_time()
    product_categories, target_category_id = _load_product_categories(session, product_id)
    _record_stage(stage_durations, "review_product_lookup_ms", stage_started_at)

    stage_started_at = current_time()
    product_accumulators, category_accumulators, reviews_scanned = _collect_product_reviews(
        session,
        target_product_id=product_id,
        target_category_id=target_category_id,
        computed_at=now,
    )
    _record_stage(stage_durations, "review_metric_read_ms", stage_started_at)

    stage_started_at = current_time()
    segment_accumulators = _collect_segment_reviews(
        session,
        product_accumulators=product_accumulators,
        computed_at=now,
    )
    _record_stage(stage_durations, "review_segment_read_ms", stage_started_at)

    stage_started_at = current_time()
    product_scores = _upsert_product_metrics(
        session,
        product_accumulators=product_accumulators,
        category_accumulators=category_accumulators,
        product_categories=product_categories,
        target_product_id=product_id,
        computed_at=now,
    )
    segment_count = _upsert_segment_metrics(
        session,
        segment_accumulators=segment_accumulators,
        product_scores=product_scores,
        target_product_id=product_id,
        computed_at=now,
    )
    _record_stage(stage_durations, "review_metric_calculation_ms", stage_started_at)

    stage_started_at = current_time()
    session.flush()
    _record_stage(stage_durations, "review_metric_flush_ms", stage_started_at)

    result = ProductReviewRollupResult(
        scope="product" if product_id is not None else "full",
        product_id=product_id,
        reviews_scanned=reviews_scanned,
        reviews_rolled_up=sum(item.review_count for item in product_accumulators.values()),
        products_updated=len(product_accumulators),
        segments_updated=segment_count,
        score_version=REVIEW_SCORE_VERSION,
        computed_at=now,
        duration_seconds=round(perf_counter() - started_at, 3),
    )
    log_performance_event(
        "product_review_rollup_completed",
        duration_ms=elapsed_ms(total_started_at),
        metadata={
            **stage_durations,
            "scope": result.scope,
            "product_id": result.product_id,
            "reviews_scanned": result.reviews_scanned,
            "reviews_rolled_up": result.reviews_rolled_up,
            "products_updated": result.products_updated,
            "segments_updated": result.segments_updated,
            "score_version": result.score_version,
        },
    )
    return result


def calculate_review_weight(
    *,
    source: str | None,
    review_type: str | None,
    verified_purchase: bool | None,
    helpful_count: int | None,
    reviewed_at: datetime | None,
    computed_at: datetime,
) -> float:
    # OliveYoung seed에서는 수집분 전량이 MONTH_USE이고 구매인증 원본값도 없어
    # 두 필드가 리뷰 간 신뢰도를 구분하지 못한다. 자사몰 구매 리뷰의
    # verified_purchase는 실제 주문 검증 신호이므로 기존 배율을 유지한다.
    source_weight = 1.0
    normalized_source = (source or "").strip().casefold()
    uses_nondiscriminating_seed_signals = normalized_source == "oliveyoung"
    month_use_weight = (
        1.0
        if uses_nondiscriminating_seed_signals
        else (1.15 if review_type == "MONTH_USE" else 1.0)
    )
    verified_weight = (
        1.0
        if uses_nondiscriminating_seed_signals
        else (1.10 if verified_purchase is True else 1.0)
    )
    normalized_helpful_count = max(0, int(helpful_count or 0))
    helpful_ratio = min(
        math.log1p(normalized_helpful_count) / math.log(21.0),
        1.0,
    )
    helpful_weight = 1.0 + (0.10 * helpful_ratio)
    recency_weight = calculate_review_recency_weight(reviewed_at, computed_at)
    return (
        source_weight
        * month_use_weight
        * verified_weight
        * helpful_weight
        * recency_weight
    )


def calculate_review_recency_weight(
    reviewed_at: datetime | None,
    computed_at: datetime,
) -> float:
    normalized_reviewed_at = _as_utc(reviewed_at)
    if normalized_reviewed_at is None:
        return 0.75
    normalized_computed_at = _as_utc(computed_at) or datetime.now(UTC)
    age_days = max(
        0.0,
        (normalized_computed_at - normalized_reviewed_at).total_seconds() / 86_400.0,
    )
    return 0.5 + (0.5 * math.pow(2.0, -age_days / 730.0))


def kish_effective_sample_size(weight_sum: float, weight_square_sum: float) -> float:
    if weight_sum <= 0.0 or weight_square_sum <= 0.0:
        return 0.0
    return (weight_sum * weight_sum) / weight_square_sum


def calculate_bayesian_mean(
    observed_value: float | None,
    effective_sample_size: float,
    prior_value: float | None,
    *,
    prior_strength: float = REVIEW_PRIOR_STRENGTH,
) -> float | None:
    if observed_value is None:
        return prior_value
    if prior_value is None:
        return observed_value
    normalized_sample_size = max(0.0, effective_sample_size)
    normalized_prior_strength = max(0.0, prior_strength)
    denominator = normalized_sample_size + normalized_prior_strength
    if denominator <= 0.0:
        return observed_value
    return (
        (observed_value * normalized_sample_size)
        + (prior_value * normalized_prior_strength)
    ) / denominator


def calculate_month_consistency_score(
    general_rating: float | None,
    month_use_rating: float | None,
) -> float | None:
    if general_rating is None or month_use_rating is None:
        return None
    return _clamp(1.0 - (abs(general_rating - month_use_rating) / 4.0))


def calculate_review_quality_score(
    *,
    rating_score: float | None,
    repurchase_score: float | None,
    photo_rate_score: float | None,
    effective_sample_size: float,
) -> tuple[float, float]:
    # review-scoring-revision 4.1: 일반후기 0건으로 일관성 축은 상시 None(G1)이라 제거하고,
    # 실존 신호인 사진리뷰율을 0.05로 신설. 일반후기 수집 재개 시 복원 재배분은 팀 논의 대상.
    quality_signal = _available_weighted_average(
        (
            (rating_score, 0.75),
            (repurchase_score, 0.20),
            (photo_rate_score, 0.05),
        ),
        default=0.5,
    )
    confidence = max(0.0, effective_sample_size) / (
        max(0.0, effective_sample_size) + REVIEW_PRIOR_STRENGTH
    )
    return _clamp(0.5 + (confidence * (quality_signal - 0.5))), confidence


def _load_product_categories(
    session: Session,
    product_id: int | None,
) -> tuple[dict[int, int], int | None]:
    rows = session.execute(select(Product.id, Product.category_id)).all()
    categories = {int(db_product_id): int(category_id) for db_product_id, category_id in rows}
    if product_id is None:
        return categories, None
    normalized_product_id = int(product_id)
    if normalized_product_id not in categories:
        raise ValueError(f"Product was not found: {normalized_product_id}")
    return categories, categories[normalized_product_id]


def _collect_product_reviews(
    session: Session,
    *,
    target_product_id: int | None,
    target_category_id: int | None,
    computed_at: datetime,
) -> tuple[dict[int, _ReviewAccumulator], dict[int, _ReviewAccumulator], int]:
    statement = (
        select(
            ProductReview.product_id,
            Product.category_id,
            ProductReview.source,
            ProductReview.review_type,
            ProductReview.rating,
            ProductReview.reviewed_at,
            ProductReview.is_repurchase_review,
            ProductReview.verified_purchase,
            ProductReview.helpful_count,
            ProductReview.source_has_photo,
        )
        .join(Product, Product.id == ProductReview.product_id)
        .where(ProductReview.status == "PUBLISHED")
        .order_by(ProductReview.id)
    )
    if target_category_id is not None:
        statement = statement.where(Product.category_id == target_category_id)

    product_accumulators: dict[int, _ReviewAccumulator] = {}
    category_accumulators: dict[int, _ReviewAccumulator] = {}
    reviews_scanned = 0
    result = session.execute(
        statement.execution_options(stream_results=True)
    ).yield_per(REVIEW_STREAM_BATCH_SIZE)
    for row in result:
        (
            db_product_id,
            category_id,
            source,
            review_type,
            rating,
            reviewed_at,
            is_repurchase_review,
            verified_purchase,
            helpful_count,
            source_has_photo,
        ) = row
        normalized_product_id = int(db_product_id)
        normalized_category_id = int(category_id)
        reviews_scanned += 1
        weight = calculate_review_weight(
            source=source,
            review_type=review_type,
            verified_purchase=verified_purchase,
            helpful_count=helpful_count,
            reviewed_at=reviewed_at,
            computed_at=computed_at,
        )
        category_accumulators.setdefault(
            normalized_category_id,
            _ReviewAccumulator(),
        ).add(
            weight=weight,
            rating=rating,
            review_type=review_type,
            is_repurchase_review=is_repurchase_review,
            helpful_count=helpful_count,
            source_has_photo=source_has_photo,
            reviewed_at=reviewed_at,
        )
        if target_product_id is not None and normalized_product_id != target_product_id:
            continue
        product_accumulators.setdefault(
            normalized_product_id,
            _ReviewAccumulator(),
        ).add(
            weight=weight,
            rating=rating,
            review_type=review_type,
            is_repurchase_review=is_repurchase_review,
            helpful_count=helpful_count,
            source_has_photo=source_has_photo,
            reviewed_at=reviewed_at,
        )

    return product_accumulators, category_accumulators, reviews_scanned


def _collect_segment_reviews(
    session: Session,
    *,
    product_accumulators: dict[int, _ReviewAccumulator],
    computed_at: datetime,
) -> dict[tuple[int, str, str], _ReviewAccumulator]:
    product_ids = sorted(product_accumulators)
    if not product_ids:
        return {}
    statement = (
        select(
            ProductReview.id,
            ProductReview.product_id,
            ProductReview.source,
            ProductReview.review_type,
            ProductReview.rating,
            ProductReview.reviewed_at,
            ProductReview.is_repurchase_review,
            ProductReview.verified_purchase,
            ProductReview.helpful_count,
            ProductReview.source_has_photo,
            ProductReviewProfileLabel.dimension,
            ProductReviewProfileLabel.value_code,
            ProductReviewProfileLabel.mapping_confidence,
        )
        .join(
            ProductReviewProfileLabel,
            ProductReviewProfileLabel.review_id == ProductReview.id,
        )
        .where(
            ProductReview.status == "PUBLISHED",
            ProductReview.product_id.in_(product_ids),
        )
        .order_by(ProductReview.product_id, ProductReview.id, ProductReviewProfileLabel.id)
    )
    segment_accumulators: dict[tuple[int, str, str], _ReviewAccumulator] = {}
    previous_review_key: tuple[int, int] | None = None
    result = session.execute(
        statement.execution_options(stream_results=True)
    ).yield_per(REVIEW_STREAM_BATCH_SIZE)
    for row in result:
        (
            review_id,
            db_product_id,
            source,
            review_type,
            rating,
            reviewed_at,
            is_repurchase_review,
            verified_purchase,
            helpful_count,
            source_has_photo,
            dimension,
            value_code,
            mapping_confidence,
        ) = row
        normalized_product_id = int(db_product_id)
        review_key = normalized_product_id, int(review_id)
        if review_key != previous_review_key:
            product_accumulators[normalized_product_id].profile_labeled_review_count += 1
            previous_review_key = review_key

        base_weight = calculate_review_weight(
            source=source,
            review_type=review_type,
            verified_purchase=verified_purchase,
            helpful_count=helpful_count,
            reviewed_at=reviewed_at,
            computed_at=computed_at,
        )
        segment_weight = base_weight * float(mapping_confidence)
        segment_key = normalized_product_id, str(dimension), str(value_code)
        segment_accumulators.setdefault(segment_key, _ReviewAccumulator()).add(
            weight=segment_weight,
            rating=rating,
            review_type=review_type,
            is_repurchase_review=is_repurchase_review,
            helpful_count=helpful_count,
            source_has_photo=source_has_photo,
            reviewed_at=reviewed_at,
        )
    return segment_accumulators


def _upsert_product_metrics(
    session: Session,
    *,
    product_accumulators: dict[int, _ReviewAccumulator],
    category_accumulators: dict[int, _ReviewAccumulator],
    product_categories: dict[int, int],
    target_product_id: int | None,
    computed_at: datetime,
) -> dict[int, _ProductScore]:
    statement = select(ProductReviewMetric)
    if target_product_id is not None:
        statement = statement.where(ProductReviewMetric.product_id == target_product_id)
    existing = {
        int(metric.product_id): metric
        for metric in session.execute(statement).scalars()
    }
    product_scores: dict[int, _ProductScore] = {}
    for db_product_id, accumulator in sorted(product_accumulators.items()):
        metric = existing.pop(db_product_id, None)
        if metric is None:
            metric = ProductReviewMetric(product_id=db_product_id)
            session.add(metric)
        category_accumulator = category_accumulators[product_categories[db_product_id]]
        product_scores[db_product_id] = _apply_product_metric(
            metric,
            accumulator=accumulator,
            category_accumulator=category_accumulator,
            computed_at=computed_at,
        )
    for stale_metric in existing.values():
        session.delete(stale_metric)
    return product_scores


def _apply_product_metric(
    metric: ProductReviewMetric,
    *,
    accumulator: _ReviewAccumulator,
    category_accumulator: _ReviewAccumulator,
    computed_at: datetime,
) -> _ProductScore:
    category_prior_rating = category_accumulator.weighted_average_rating
    category_prior_repurchase_rate = category_accumulator.weighted_repurchase_rate
    bayesian_rating = calculate_bayesian_mean(
        accumulator.weighted_average_rating,
        accumulator.rating_effective_sample_size,
        category_prior_rating,
    )
    bayesian_repurchase_rate = calculate_bayesian_mean(
        accumulator.weighted_repurchase_rate,
        accumulator.repurchase_effective_sample_size,
        category_prior_repurchase_rate,
    )
    rating_score = (
        _clamp((bayesian_rating - 3.0) / 2.0)
        if bayesian_rating is not None
        else 0.5
    )
    repurchase_score = (
        _clamp(bayesian_repurchase_rate)
        if bayesian_repurchase_rate is not None
        else 0.5
    )
    # 일관성 값 자체는 진단 지표로 컬럼에 계속 보존한다(품질점수 합성에서만 제외).
    month_consistency_score = calculate_month_consistency_score(
        accumulator.general_weighted_average_rating,
        accumulator.month_weighted_average_rating,
    )
    category_prior_photo_rate = category_accumulator.weighted_photo_rate
    bayesian_photo_rate = calculate_bayesian_mean(
        accumulator.weighted_photo_rate,
        accumulator.photo_effective_sample_size,
        category_prior_photo_rate,
    )
    photo_rate_score = (
        _clamp(bayesian_photo_rate)
        if bayesian_photo_rate is not None
        else None
    )
    review_quality_score, confidence = calculate_review_quality_score(
        rating_score=rating_score if accumulator.rating_count else None,
        repurchase_score=(
            repurchase_score if accumulator.repurchase_known_count else None
        ),
        photo_rate_score=(
            photo_rate_score if accumulator.photo_known_count else None
        ),
        effective_sample_size=accumulator.effective_sample_size,
    )

    metric.review_count = accumulator.review_count
    metric.rating_count = accumulator.rating_count
    metric.rating_1_count = accumulator.rating_counts[1]
    metric.rating_2_count = accumulator.rating_counts[2]
    metric.rating_3_count = accumulator.rating_counts[3]
    metric.rating_4_count = accumulator.rating_counts[4]
    metric.rating_5_count = accumulator.rating_counts[5]
    metric.average_rating = _rating_decimal(accumulator.average_rating)
    metric.weighted_average_rating = _rating_decimal(accumulator.weighted_average_rating)
    metric.bayesian_rating = _rating_decimal(bayesian_rating)
    metric.category_prior_rating = _rating_decimal(category_prior_rating)
    metric.general_review_count = accumulator.general_review_count
    metric.month_use_review_count = accumulator.month_use_review_count
    metric.general_average_rating = _rating_decimal(accumulator.general_average_rating)
    metric.month_use_average_rating = _rating_decimal(accumulator.month_average_rating)
    metric.repurchase_known_count = accumulator.repurchase_known_count
    metric.repurchase_review_count = accumulator.repurchase_review_count
    metric.repurchase_rate = _score_decimal(accumulator.repurchase_rate)
    metric.bayesian_repurchase_rate = _score_decimal(bayesian_repurchase_rate)
    metric.category_prior_repurchase_rate = _score_decimal(
        category_prior_repurchase_rate
    )
    metric.profile_labeled_review_count = accumulator.profile_labeled_review_count
    metric.source_photo_marker_count = accumulator.source_photo_marker_count
    metric.helpful_count_sum = accumulator.helpful_count_sum
    metric.weight_sum = _weight_decimal(accumulator.weight_sum)
    metric.weight_square_sum = _weight_decimal(accumulator.weight_square_sum)
    metric.rating_effective_sample_size = _weight_decimal(
        accumulator.rating_effective_sample_size
    )
    metric.repurchase_effective_sample_size = _weight_decimal(
        accumulator.repurchase_effective_sample_size
    )
    metric.month_use_effective_sample_size = _weight_decimal(
        accumulator.month_effective_sample_size
    )
    metric.effective_sample_size = _weight_decimal(accumulator.effective_sample_size)
    metric.prior_strength = _prior_decimal(REVIEW_PRIOR_STRENGTH)
    metric.rating_score = _score_decimal(rating_score)
    metric.repurchase_score = _score_decimal(repurchase_score)
    metric.month_consistency_score = _score_decimal(month_consistency_score)
    metric.bayesian_photo_rate = _score_decimal(bayesian_photo_rate)
    metric.photo_rate_score = _score_decimal(photo_rate_score)
    metric.confidence = _score_decimal(confidence)
    metric.review_quality_score = _score_decimal(review_quality_score)
    metric.last_reviewed_at = accumulator.last_reviewed_at
    metric.score_version = REVIEW_SCORE_VERSION
    metric.computed_at = computed_at
    metric.updated_at = computed_at
    return _ProductScore(
        bayesian_rating=bayesian_rating,
        bayesian_repurchase_rate=bayesian_repurchase_rate,
    )


def _upsert_segment_metrics(
    session: Session,
    *,
    segment_accumulators: dict[tuple[int, str, str], _ReviewAccumulator],
    product_scores: dict[int, _ProductScore],
    target_product_id: int | None,
    computed_at: datetime,
) -> int:
    statement = select(ProductReviewSegmentMetric)
    if target_product_id is not None:
        statement = statement.where(
            ProductReviewSegmentMetric.product_id == target_product_id
        )
    existing = {
        (int(metric.product_id), str(metric.dimension), str(metric.value_code)): metric
        for metric in session.execute(statement).scalars()
    }
    for segment_key, accumulator in sorted(segment_accumulators.items()):
        db_product_id, dimension, value_code = segment_key
        metric = existing.pop(segment_key, None)
        if metric is None:
            metric = ProductReviewSegmentMetric(
                product_id=db_product_id,
                dimension=dimension,
                value_code=value_code,
            )
            session.add(metric)
        _apply_segment_metric(
            metric,
            accumulator=accumulator,
            product_score=product_scores[db_product_id],
            computed_at=computed_at,
        )
    for stale_metric in existing.values():
        session.delete(stale_metric)
    return len(segment_accumulators)


def _apply_segment_metric(
    metric: ProductReviewSegmentMetric,
    *,
    accumulator: _ReviewAccumulator,
    product_score: _ProductScore,
    computed_at: datetime,
) -> None:
    bayesian_rating = calculate_bayesian_mean(
        accumulator.weighted_average_rating,
        accumulator.rating_effective_sample_size,
        product_score.bayesian_rating,
    )
    bayesian_repurchase_rate = calculate_bayesian_mean(
        accumulator.weighted_repurchase_rate,
        accumulator.repurchase_effective_sample_size,
        product_score.bayesian_repurchase_rate,
    )
    rating_affinity_score = (
        _clamp(
            0.5
            + ((bayesian_rating - product_score.bayesian_rating) / 4.0)
        )
        if bayesian_rating is not None and product_score.bayesian_rating is not None
        else 0.5
    )
    repurchase_affinity_score = (
        _clamp(
            0.5
            + (
                (bayesian_repurchase_rate - product_score.bayesian_repurchase_rate)
                / 2.0
            )
        )
        if (
            bayesian_repurchase_rate is not None
            and product_score.bayesian_repurchase_rate is not None
        )
        else 0.5
    )
    total_affinity_score = _available_weighted_average(
        (
            (
                rating_affinity_score if accumulator.rating_count else None,
                0.80,
            ),
            (
                repurchase_affinity_score
                if accumulator.repurchase_known_count
                else None,
                0.20,
            ),
        ),
        default=0.5,
    )
    confidence = accumulator.effective_sample_size / (
        accumulator.effective_sample_size + REVIEW_PRIOR_STRENGTH
    )

    metric.review_count = accumulator.review_count
    metric.rating_count = accumulator.rating_count
    metric.month_use_review_count = accumulator.month_use_review_count
    metric.repurchase_known_count = accumulator.repurchase_known_count
    metric.repurchase_review_count = accumulator.repurchase_review_count
    metric.average_rating = _rating_decimal(accumulator.average_rating)
    metric.weighted_average_rating = _rating_decimal(accumulator.weighted_average_rating)
    metric.bayesian_rating = _rating_decimal(bayesian_rating)
    metric.product_prior_rating = _rating_decimal(product_score.bayesian_rating)
    metric.repurchase_rate = _score_decimal(accumulator.repurchase_rate)
    metric.bayesian_repurchase_rate = _score_decimal(bayesian_repurchase_rate)
    metric.product_prior_repurchase_rate = _score_decimal(
        product_score.bayesian_repurchase_rate
    )
    metric.weight_sum = _weight_decimal(accumulator.weight_sum)
    metric.weight_square_sum = _weight_decimal(accumulator.weight_square_sum)
    metric.effective_sample_size = _weight_decimal(accumulator.effective_sample_size)
    metric.rating_effective_sample_size = _weight_decimal(
        accumulator.rating_effective_sample_size
    )
    metric.repurchase_effective_sample_size = _weight_decimal(
        accumulator.repurchase_effective_sample_size
    )
    metric.rating_affinity_score = _score_decimal(rating_affinity_score)
    metric.repurchase_affinity_score = _score_decimal(repurchase_affinity_score)
    metric.total_affinity_score = _score_decimal(total_affinity_score)
    metric.confidence = _score_decimal(confidence)
    metric.last_reviewed_at = accumulator.last_reviewed_at
    metric.score_version = REVIEW_SCORE_VERSION
    metric.computed_at = computed_at
    metric.updated_at = computed_at


def _available_weighted_average(
    values: tuple[tuple[float | None, float], ...],
    *,
    default: float,
) -> float:
    available = [(value, weight) for value, weight in values if value is not None]
    weight_sum = sum(weight for _, weight in available)
    if weight_sum <= 0.0:
        return default
    return sum(float(value) * weight for value, weight in available) / weight_sum


def _safe_divide(numerator: float, denominator: float | int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / float(denominator)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal(value: float | None, quantum: Decimal) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _score_decimal(value: float | None) -> Decimal | None:
    return _decimal(value, _SCORE_QUANTUM)


def _rating_decimal(value: float | None) -> Decimal | None:
    return _decimal(value, _RATING_QUANTUM)


def _weight_decimal(value: float) -> Decimal:
    return _decimal(value, _WEIGHT_QUANTUM) or Decimal("0")


def _prior_decimal(value: float) -> Decimal:
    return _decimal(value, _PRIOR_QUANTUM) or Decimal("0")


def _record_stage(stage_durations: dict[str, float], key: str, started_at: float) -> None:
    stage_durations[key] = round(elapsed_ms(started_at), 2)
