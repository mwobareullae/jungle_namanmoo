from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path


SIGNALS_FILENAME = "product_market_signals.csv"
RECENT_SIGNAL_WINDOW_DAYS = 14
BAYESIAN_RATING_CONFIDENCE_REVIEWS = 50.0

MARKET_POPULARITY_WEIGHTS = {
    "review_count": 0.30,
    "rating": 0.25,
    "sales": 0.30,
    "recent_signal": 0.15,
}


@dataclass(frozen=True)
class MarketPopularityScore:
    total: float
    review_count_score: float
    rating_score: float
    sales_score: float
    recent_signal_score: float


@dataclass(frozen=True)
class MarketPopularityContext:
    signals: dict[str, dict[str, str]]
    max_review_count: float
    max_sales_count: float
    max_recent_signal: float
    max_sales_rank: float
    global_rating: float

    @property
    def available(self) -> bool:
        return bool(self.signals)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or "")
    except (TypeError, ValueError):
        return default


def load_market_popularity_context(data_dir: Path) -> MarketPopularityContext:
    path = data_dir / SIGNALS_FILENAME
    if not path.exists():
        return MarketPopularityContext({}, 0.0, 0.0, 0.0, 0.0, 4.0)

    rows = [
        row
        for row in read_csv(path)
        if row.get("product_id") and has_any_market_signal(row)
    ]
    signals = {row["product_id"]: row for row in rows}
    review_counts = [to_float(row.get("review_count")) for row in rows]
    sales_counts = [to_float(row.get("sales_count")) for row in rows]
    sales_ranks = [to_float(row.get("sales_rank")) for row in rows if to_float(row.get("sales_rank")) > 0]
    recent_signals = [recent_signal_value(row) for row in rows]
    weighted_ratings = [
        (to_float(row.get("average_rating")), to_float(row.get("review_count")))
        for row in rows
        if to_float(row.get("average_rating")) > 0 and to_float(row.get("review_count")) > 0
    ]
    rating_weight = sum(weight for _, weight in weighted_ratings)
    global_rating = (
        sum(rating * weight for rating, weight in weighted_ratings) / rating_weight
        if rating_weight
        else 4.0
    )

    return MarketPopularityContext(
        signals=signals,
        max_review_count=max(review_counts, default=0.0),
        max_sales_count=max(sales_counts, default=0.0),
        max_recent_signal=max(recent_signals, default=0.0),
        max_sales_rank=max(sales_ranks, default=0.0),
        global_rating=global_rating,
    )


def has_any_market_signal(row: dict[str, str]) -> bool:
    signal_columns = (
        "review_count",
        "average_rating",
        "sales_count",
        "sales_rank",
        "recent_view_count",
        "wishlist_count",
        "cart_add_count",
    )
    return any(to_float(row.get(column)) > 0 for column in signal_columns)


def score_market_popularity(
    product_id: str,
    context: MarketPopularityContext,
) -> MarketPopularityScore | None:
    row = context.signals.get(product_id)
    if row is None:
        return None

    review_count_score = log_normalized_score(to_float(row.get("review_count")), context.max_review_count)
    rating_score = bayesian_rating_score(
        rating=to_float(row.get("average_rating")),
        review_count=to_float(row.get("review_count")),
        global_rating=context.global_rating,
    )
    sales_score = sales_signal_score(row, context)
    recent_signal_score = log_normalized_score(recent_signal_value(row), context.max_recent_signal)
    total = weighted_available_score(
        [
            (
                review_count_score,
                MARKET_POPULARITY_WEIGHTS["review_count"],
                to_float(row.get("review_count")) > 0,
            ),
            (rating_score, MARKET_POPULARITY_WEIGHTS["rating"], to_float(row.get("average_rating")) > 0),
            (
                sales_score,
                MARKET_POPULARITY_WEIGHTS["sales"],
                to_float(row.get("sales_count")) > 0 or to_float(row.get("sales_rank")) > 0,
            ),
            (
                recent_signal_score,
                MARKET_POPULARITY_WEIGHTS["recent_signal"],
                recent_signal_value(row) > 0,
            ),
        ]
    )

    return MarketPopularityScore(
        total=round(total, 2),
        review_count_score=round(review_count_score, 2),
        rating_score=round(rating_score, 2),
        sales_score=round(sales_score, 2),
        recent_signal_score=round(recent_signal_score, 2),
    )


def log_normalized_score(value: float, max_value: float) -> float:
    if value <= 0 or max_value <= 0:
        return 0.0
    return 100.0 * math.log1p(value) / math.log1p(max_value)


def bayesian_rating_score(
    *,
    rating: float,
    review_count: float,
    global_rating: float,
    confidence_reviews: float = BAYESIAN_RATING_CONFIDENCE_REVIEWS,
) -> float:
    if rating <= 0:
        return 0.0
    clipped_rating = min(5.0, max(0.0, rating))
    adjusted = (
        review_count / (review_count + confidence_reviews) * clipped_rating
        + confidence_reviews / (review_count + confidence_reviews) * global_rating
    )
    return adjusted / 5.0 * 100.0


def sales_signal_score(row: dict[str, str], context: MarketPopularityContext) -> float:
    sales_count = to_float(row.get("sales_count"))
    if sales_count > 0:
        return log_normalized_score(sales_count, context.max_sales_count)

    sales_rank = to_float(row.get("sales_rank"))
    if sales_rank <= 0:
        return 0.0
    if context.max_sales_rank <= 1:
        return 100.0
    rank_score = 100.0 * (
        1.0 - (math.log1p(sales_rank - 1.0) / math.log1p(context.max_sales_rank - 1.0))
    )
    return min(100.0, max(0.0, rank_score))


def recent_signal_value(row: dict[str, str]) -> float:
    return (
        to_float(row.get("recent_view_count"))
        + to_float(row.get("wishlist_count")) * 3.0
        + to_float(row.get("cart_add_count")) * 5.0
    )


def weighted_available_score(scores: list[tuple[float, float, bool]]) -> float:
    available = [(score, weight) for score, weight, is_available in scores if is_available]
    weight_sum = sum(weight for _, weight in available)
    if weight_sum <= 0:
        return 0.0
    return sum(score * weight for score, weight in available) / weight_sum
