from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models.catalog import Product
from app.db.models.commerce import OrderItem, ProductPopularityMetric
from app.db.models.events import EventLog
from app.services.popularity_score import POPULARITY_SCORE_VERSION, calculate_product_popularity_score


DIRECT_PRODUCT_EVENT_FIELDS: dict[str, str] = {
    "product_viewed": "view_count",
    "recommendation_product_click": "click_count",
    "home_product_click": "home_product_click_count",
    "search_result_click": "search_result_click_count",
    "cart_added": "cart_add_count",
    "wishlist_added": "wishlist_add_count",
    "home_product_impression": "home_product_impression_count",
    "search_result_impression": "search_result_impression_count",
    "wishlist_removed": "wishlist_remove_count",
    "cart_removed": "cart_remove_count",
    "cart_quantity_changed": "cart_quantity_change_count",
}

ORDER_EVENT_FIELDS: dict[str, str] = {
    "order_completed": "paid_order_count",
    "payment_failed": "payment_failed_count",
    "order_cancelled": "order_cancel_count",
}


@dataclass
class ProductPopularityRollupResult:
    window_days: int
    touched_products: int
    updated_metrics: int
    computed_at: datetime
    score_version: str = POPULARITY_SCORE_VERSION


def rollup_product_popularity_metrics(
    session: Session,
    *,
    window_days: int = 7,
    computed_at: datetime | None = None,
) -> ProductPopularityRollupResult:
    normalized_window_days = max(0, int(window_days))
    now = computed_at or datetime.now(UTC)
    product_code_to_id = _load_product_code_to_id(session)
    counters: dict[int, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))

    _collect_direct_product_event_counts(session, counters, product_code_to_id, normalized_window_days, now)
    _collect_checkout_started_counts(session, counters, product_code_to_id, normalized_window_days, now)
    _collect_order_event_counts(session, counters, normalized_window_days, now)

    existing_metrics = _load_existing_metrics(session, normalized_window_days)
    product_ids_to_update = set(existing_metrics) | set(counters)
    for product_id in sorted(product_ids_to_update):
        metric = existing_metrics.get(product_id)
        if metric is None:
            metric = ProductPopularityMetric(product_id=product_id, window_days=normalized_window_days)
            session.add(metric)

        product_counts = counters.get(product_id, defaultdict(int))
        _apply_counts(metric, product_counts, now)

    session.flush()
    return ProductPopularityRollupResult(
        window_days=normalized_window_days,
        touched_products=len(counters),
        updated_metrics=len(product_ids_to_update),
        computed_at=now,
    )


def _load_product_code_to_id(session: Session) -> dict[str, int]:
    rows = session.execute(select(Product.product_code, Product.id)).all()
    return {str(product_code): int(product_id) for product_code, product_id in rows}


def _load_existing_metrics(session: Session, window_days: int) -> dict[int, ProductPopularityMetric]:
    rows = session.execute(
        select(ProductPopularityMetric).where(ProductPopularityMetric.window_days == window_days)
    ).scalars()
    return {int(row.product_id): row for row in rows}


def _collect_direct_product_event_counts(
    session: Session,
    counters: dict[int, defaultdict[str, int]],
    product_code_to_id: dict[str, int],
    window_days: int,
    computed_at: datetime,
) -> None:
    statement = (
        select(EventLog.product_id, EventLog.event_name, func.count(EventLog.id))
        .where(
            EventLog.product_id.is_not(None),
            EventLog.event_name.in_(DIRECT_PRODUCT_EVENT_FIELDS.keys()),
            EventLog.occurred_at <= computed_at,
        )
        .group_by(EventLog.product_id, EventLog.event_name)
    )
    statement = _apply_window(statement, window_days, computed_at)

    for product_code, event_name, count in session.execute(statement).all():
        product_id = product_code_to_id.get(str(product_code))
        if product_id is None:
            continue
        field_name = DIRECT_PRODUCT_EVENT_FIELDS[str(event_name)]
        counters[product_id][field_name] += int(count)
        if event_name in {"home_product_click", "search_result_click"}:
            counters[product_id]["click_count"] += int(count)


def _collect_checkout_started_counts(
    session: Session,
    counters: dict[int, defaultdict[str, int]],
    product_code_to_id: dict[str, int],
    window_days: int,
    computed_at: datetime,
) -> None:
    statement = (
        select(EventLog.metadata_json)
        .where(
            EventLog.event_name == "checkout_started",
            EventLog.occurred_at <= computed_at,
        )
    )
    statement = _apply_window(statement, window_days, computed_at)

    for (metadata_json,) in session.execute(statement).all():
        for product_code in _extract_product_codes(metadata_json):
            product_id = product_code_to_id.get(product_code)
            if product_id is not None:
                counters[product_id]["checkout_start_count"] += 1


def _collect_order_event_counts(
    session: Session,
    counters: dict[int, defaultdict[str, int]],
    window_days: int,
    computed_at: datetime,
) -> None:
    statement = (
        select(
            EventLog.event_name,
            OrderItem.product_id,
            func.count(distinct(EventLog.id)),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        )
        .join(OrderItem, EventLog.order_id == OrderItem.order_id)
        .where(
            EventLog.order_id.is_not(None),
            EventLog.event_name.in_(ORDER_EVENT_FIELDS.keys()),
            EventLog.occurred_at <= computed_at,
        )
        .group_by(EventLog.event_name, OrderItem.product_id)
    )
    statement = _apply_window(statement, window_days, computed_at)

    for event_name, product_id, event_count, quantity_sum in session.execute(statement).all():
        field_name = ORDER_EVENT_FIELDS[str(event_name)]
        normalized_product_id = int(product_id)
        counters[normalized_product_id][field_name] += int(event_count)
        if event_name == "order_completed":
            counters[normalized_product_id]["order_count"] += int(event_count)
            counters[normalized_product_id]["units_sold"] += int(quantity_sum or 0)


def _apply_counts(
    metric: ProductPopularityMetric,
    counts: defaultdict[str, int],
    computed_at: datetime,
) -> None:
    metric.view_count = counts["view_count"]
    metric.click_count = counts["click_count"]
    metric.cart_add_count = counts["cart_add_count"]
    metric.order_count = counts["order_count"]
    metric.units_sold = counts["units_sold"]
    metric.wishlist_add_count = counts["wishlist_add_count"]
    metric.checkout_start_count = counts["checkout_start_count"]
    metric.paid_order_count = counts["paid_order_count"]
    metric.home_product_impression_count = counts["home_product_impression_count"]
    metric.home_product_click_count = counts["home_product_click_count"]
    metric.search_result_impression_count = counts["search_result_impression_count"]
    metric.search_result_click_count = counts["search_result_click_count"]
    metric.wishlist_remove_count = counts["wishlist_remove_count"]
    metric.cart_remove_count = counts["cart_remove_count"]
    metric.cart_quantity_change_count = counts["cart_quantity_change_count"]
    metric.payment_failed_count = counts["payment_failed_count"]
    metric.order_cancel_count = counts["order_cancel_count"]
    metric.popularity_score = Decimal(
        str(
            round(
                calculate_product_popularity_score(
                    view_count=metric.view_count,
                    wishlist_add_count=metric.wishlist_add_count,
                    cart_add_count=metric.cart_add_count,
                    checkout_start_count=metric.checkout_start_count,
                    paid_order_count=metric.paid_order_count,
                    home_product_impression_count=metric.home_product_impression_count,
                    home_product_click_count=metric.home_product_click_count,
                    search_result_impression_count=metric.search_result_impression_count,
                    search_result_click_count=metric.search_result_click_count,
                ),
                4,
            )
        )
    )
    metric.score_version = POPULARITY_SCORE_VERSION
    metric.computed_at = computed_at
    metric.updated_at = computed_at


def _apply_window(statement: Any, window_days: int, computed_at: datetime) -> Any:
    if window_days <= 0:
        return statement
    return statement.where(EventLog.occurred_at >= computed_at - timedelta(days=window_days))


def _extract_product_codes(metadata_json: Any) -> list[str]:
    if not isinstance(metadata_json, dict):
        return []
    product_ids = metadata_json.get("product_ids")
    if not isinstance(product_ids, list):
        return []

    normalized_codes: list[str] = []
    seen: set[str] = set()
    for value in product_ids:
        if not isinstance(value, str):
            continue
        product_code = value.strip()
        if product_code and product_code not in seen:
            normalized_codes.append(product_code)
            seen.add(product_code)
    return normalized_codes
