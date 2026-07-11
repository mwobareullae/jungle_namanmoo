from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product
from app.db.models.review import (
    ProductReview,
    ProductReviewMetric,
    ProductReviewProfileLabel,
)
from app.schemas.common import ApiError
from app.schemas.review import (
    ProductReviewItem,
    ProductReviewProfileLabel as ProductReviewProfileLabelSchema,
    ProductReviewsResponse,
    ProductReviewSummary,
)


ReviewSort = Literal["latest", "helpful", "rating_high", "rating_low"]
REVIEW_SORT_VALUES = {"latest", "helpful", "rating_high", "rating_low"}
DEFAULT_REVIEW_LIMIT = 20
MAX_REVIEW_LIMIT = 50
_CURSOR_VERSION = 1
_NULL_REVIEWED_AT = datetime(1970, 1, 1, tzinfo=UTC)


def get_product_reviews_response(
    session: Session,
    *,
    product_code: str,
    cursor: str | None,
    limit: int = DEFAULT_REVIEW_LIMIT,
    sort: ReviewSort = "latest",
    rating: int | None = None,
    review_type: str | None = None,
    repurchase: bool | None = None,
    skin_type: str | None = None,
    sensitivity: str | None = None,
    skin_tone: str | None = None,
    concern: str | None = None,
) -> ProductReviewsResponse:
    product_id = _resolve_product_id(session, product_code)
    normalized_sort = _normalize_sort(sort)
    normalized_limit = max(1, min(int(limit), MAX_REVIEW_LIMIT))
    cursor_payload = _decode_cursor(cursor, normalized_sort) if cursor else None

    reviewed_at_key = func.coalesce(ProductReview.reviewed_at, _NULL_REVIEWED_AT)
    helpful_key = func.coalesce(ProductReview.helpful_count, 0)
    rating_high_key = func.coalesce(ProductReview.rating, 0)
    rating_low_key = func.coalesce(ProductReview.rating, 6)
    statement = select(ProductReview).where(
        ProductReview.product_id == product_id,
        ProductReview.status == "PUBLISHED",
    )
    if rating is not None:
        statement = statement.where(ProductReview.rating == int(rating))
    if review_type is not None:
        statement = statement.where(ProductReview.review_type == review_type)
    if repurchase is not None:
        statement = statement.where(ProductReview.is_repurchase_review.is_(repurchase))
    statement = _apply_profile_filter(statement, "SKIN_TYPE", skin_type)
    statement = _apply_profile_filter(statement, "SENSITIVITY", sensitivity)
    statement = _apply_profile_filter(statement, "SKIN_TONE", skin_tone)
    statement = _apply_profile_filter(statement, "SKIN_CONCERN", concern)
    if cursor_payload is not None:
        statement = statement.where(
            _cursor_condition(
                normalized_sort,
                cursor_payload,
                reviewed_at_key=reviewed_at_key,
                helpful_key=helpful_key,
                rating_high_key=rating_high_key,
                rating_low_key=rating_low_key,
            )
        )
    statement = statement.order_by(
        *_sort_expressions(
            normalized_sort,
            reviewed_at_key=reviewed_at_key,
            helpful_key=helpful_key,
            rating_high_key=rating_high_key,
            rating_low_key=rating_low_key,
        )
    ).limit(normalized_limit + 1)

    rows = list(session.execute(statement).scalars())
    has_next = len(rows) > normalized_limit
    visible_rows = rows[:normalized_limit]
    labels_by_review_id = _load_profile_labels(
        session,
        [int(review.id) for review in visible_rows],
    )
    items = [
        _to_review_item(review, labels_by_review_id.get(int(review.id), []))
        for review in visible_rows
    ]
    next_cursor = (
        _encode_cursor(normalized_sort, visible_rows[-1])
        if has_next and visible_rows
        else None
    )
    return ProductReviewsResponse(
        product_id=product_code,
        sort=normalized_sort,
        limit=normalized_limit,
        items=items,
        next_cursor=next_cursor,
        has_next=has_next,
    )


def get_product_review_summary(
    session: Session,
    product_id: int,
) -> ProductReviewSummary:
    metric = session.scalar(
        select(ProductReviewMetric).where(ProductReviewMetric.product_id == product_id)
    )
    if metric is None:
        return ProductReviewSummary(
            review_count=0,
            average_rating=None,
            rating_distribution={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            general_review_count=0,
            month_use_review_count=0,
            repurchase_known_count=0,
            repurchase_review_count=0,
            repurchase_rate=None,
            profile_labeled_review_count=0,
            last_reviewed_at=None,
        )
    return ProductReviewSummary(
        review_count=int(metric.review_count),
        average_rating=(
            float(metric.average_rating) if metric.average_rating is not None else None
        ),
        rating_distribution={
            1: int(metric.rating_1_count),
            2: int(metric.rating_2_count),
            3: int(metric.rating_3_count),
            4: int(metric.rating_4_count),
            5: int(metric.rating_5_count),
        },
        general_review_count=int(metric.general_review_count),
        month_use_review_count=int(metric.month_use_review_count),
        repurchase_known_count=int(metric.repurchase_known_count),
        repurchase_review_count=int(metric.repurchase_review_count),
        repurchase_rate=(
            float(metric.repurchase_rate) if metric.repurchase_rate is not None else None
        ),
        profile_labeled_review_count=int(metric.profile_labeled_review_count),
        last_reviewed_at=_as_utc(metric.last_reviewed_at),
    )


def _resolve_product_id(session: Session, product_code: str) -> int:
    product_id = session.scalar(
        select(Product.id).where(Product.product_code == product_code)
    )
    if product_id is None:
        raise ApiError(404, "NOT_FOUND", "상품을 찾을 수 없습니다.")
    return int(product_id)


def _normalize_sort(value: str) -> ReviewSort:
    if value not in REVIEW_SORT_VALUES:
        raise ApiError(400, "INVALID_REVIEW_SORT", "지원하지 않는 리뷰 정렬 방식입니다.")
    return value  # type: ignore[return-value]


def _apply_profile_filter(statement, dimension: str, value_code: str | None):
    if value_code is None:
        return statement
    review_ids = select(ProductReviewProfileLabel.review_id).where(
        ProductReviewProfileLabel.dimension == dimension,
        ProductReviewProfileLabel.value_code == value_code,
    )
    return statement.where(ProductReview.id.in_(review_ids))


def _sort_expressions(
    sort: ReviewSort,
    *,
    reviewed_at_key,
    helpful_key,
    rating_high_key,
    rating_low_key,
) -> tuple:
    if sort == "helpful":
        return helpful_key.desc(), reviewed_at_key.desc(), ProductReview.id.desc()
    if sort == "rating_high":
        return rating_high_key.desc(), reviewed_at_key.desc(), ProductReview.id.desc()
    if sort == "rating_low":
        return rating_low_key.asc(), reviewed_at_key.desc(), ProductReview.id.desc()
    return reviewed_at_key.desc(), ProductReview.id.desc()


def _cursor_condition(
    sort: ReviewSort,
    payload: dict,
    *,
    reviewed_at_key,
    helpful_key,
    rating_high_key,
    rating_low_key,
):
    cursor_id = int(payload["id"])
    reviewed_at = _parse_cursor_datetime(payload["reviewed_at"])
    reviewed_tail = or_(
        reviewed_at_key < reviewed_at,
        and_(reviewed_at_key == reviewed_at, ProductReview.id < cursor_id),
    )
    if sort == "latest":
        return reviewed_tail

    primary = int(payload["primary"])
    primary_key = helpful_key
    primary_after = primary_key < primary
    if sort == "rating_high":
        primary_key = rating_high_key
        primary_after = primary_key < primary
    elif sort == "rating_low":
        primary_key = rating_low_key
        primary_after = primary_key > primary
    return or_(
        primary_after,
        and_(primary_key == primary, reviewed_tail),
    )


def _encode_cursor(sort: ReviewSort, review: ProductReview) -> str:
    reviewed_at = _as_utc(review.reviewed_at) or _NULL_REVIEWED_AT
    payload: dict[str, object] = {
        "v": _CURSOR_VERSION,
        "sort": sort,
        "reviewed_at": reviewed_at.isoformat(),
        "id": int(review.id),
    }
    if sort == "helpful":
        payload["primary"] = int(review.helpful_count or 0)
    elif sort == "rating_high":
        payload["primary"] = int(review.rating or 0)
    elif sort == "rating_low":
        payload["primary"] = int(review.rating if review.rating is not None else 6)
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, sort: ReviewSort) -> dict:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get("v") != _CURSOR_VERSION or payload.get("sort") != sort:
            raise ValueError
        int(payload["id"])
        _parse_cursor_datetime(payload["reviewed_at"])
        if sort != "latest":
            int(payload["primary"])
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError(400, "INVALID_CURSOR", "유효하지 않은 리뷰 cursor입니다.") from exc
    return payload


def _parse_cursor_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value)
    return _as_utc(parsed) or _NULL_REVIEWED_AT


def _load_profile_labels(
    session: Session,
    review_ids: list[int],
) -> dict[int, list[ProductReviewProfileLabelSchema]]:
    if not review_ids:
        return {}
    rows = session.execute(
        select(ProductReviewProfileLabel)
        .where(ProductReviewProfileLabel.review_id.in_(review_ids))
        .order_by(
            ProductReviewProfileLabel.review_id,
            ProductReviewProfileLabel.dimension,
            ProductReviewProfileLabel.value_code,
        )
    ).scalars()
    result: dict[int, list[ProductReviewProfileLabelSchema]] = {}
    for row in rows:
        result.setdefault(int(row.review_id), []).append(
            ProductReviewProfileLabelSchema(
                dimension=row.dimension,
                value_code=row.value_code,
                display_label=row.source_label,
            )
        )
    return result


def _to_review_item(
    review: ProductReview,
    profile_labels: list[ProductReviewProfileLabelSchema],
) -> ProductReviewItem:
    badges = review.source_badge_labels_json
    return ProductReviewItem(
        review_id=review.review_code,
        rating=review.rating,
        review_text=review.review_text,
        reviewed_at=_as_utc(review.reviewed_at),
        option_text=review.option_text,
        review_type=review.review_type,
        is_repurchase_review=review.is_repurchase_review,
        verified_purchase=review.verified_purchase,
        helpful_count=int(review.helpful_count or 0),
        badges=[str(value) for value in badges] if isinstance(badges, list) else [],
        author=None,
        profile_labels=profile_labels,
        media=[],
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
