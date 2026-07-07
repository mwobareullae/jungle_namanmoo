# Product Popular API Contract

## Purpose

`GET /api/products/popular` returns products ranked by persisted popularity metrics.

This API does not calculate popularity from raw event/order/review tables on every request. It reads `product_popularity_metrics`, a read model prepared for fast home and best-seller screens.

`data/product_market_signals.csv` is not trusted as real service behavior data. For local/dev P2 demos, seed imports it into `product_popularity_metrics` with `score_version=mock_market_signals_v1`; later event/order/review aggregation should replace it.

Popularity scoring policy is defined in [`docs/popularity-ranking-score.md`](./popularity-ranking-score.md).

Frontend event contract is defined in [`docs/popularity-event-frontend-contract.md`](./popularity-event-frontend-contract.md).

Rollup operation guide is defined in [`docs/popularity-rollup-operations.md`](./popularity-rollup-operations.md).

## Endpoint

```http
GET /api/products/popular?window_days=7&limit=20
```

Optional params:

| Param | Meaning |
|---|---|
| `window_days` | Popularity window. `7` is the MVP default. `0` may mean all-time if a metric row exists. |
| `limit` | Max products, capped by backend. |
| `category_code` | Optional category narrowing. |

## Source Table

```text
product_popularity_metrics
- product_id
- window_days
- view_count
- click_count
- cart_add_count
- order_count
- units_sold
- wishlist_add_count
- checkout_start_count
- paid_order_count
- home_product_impression_count
- home_product_click_count
- search_result_impression_count
- search_result_click_count
- wishlist_remove_count
- cart_remove_count
- cart_quantity_change_count
- payment_failed_count
- order_cancel_count
- review_count
- average_rating
- popularity_score
- score_version
- computed_at
```

Uniqueness:

```text
UNIQUE(product_id, window_days)
```

## Response

```json
{
  "window_days": 7,
  "items": [
    {
      "product_id": "prod_001",
      "brand": "brand",
      "name": "product name",
      "category_code": "cream",
      "category_name": "cream",
      "thumbnail_url": "products/prod_001/thumbnail.jpg",
      "lowest_price": 19900,
      "purchase_url": "https://example.com/product",
      "popularity_score": 88.0,
      "score_version": "popular_v1",
      "computed_at": "2026-07-05T00:00:00+09:00",
      "metrics": {
        "view_count": 100,
        "click_count": 30,
        "cart_add_count": 10,
        "order_count": 5,
        "units_sold": 6,
        "wishlist_add_count": 8,
        "checkout_start_count": 4,
        "paid_order_count": 3,
        "home_product_impression_count": 300,
        "home_product_click_count": 24,
        "search_result_impression_count": 120,
        "search_result_click_count": 15,
        "wishlist_remove_count": 1,
        "cart_remove_count": 1,
        "cart_quantity_change_count": 2,
        "payment_failed_count": 0,
        "order_cancel_count": 0,
        "review_count": 20,
        "average_rating": 4.5
      }
    }
  ]
}
```

`thumbnail_url` keeps the existing backend response field name, but the value is a `storage_key`, not a CDN absolute URL.

## Home Integration

`GET /api/home/sections` uses the same popularity service.

When metric rows exist, home may include:

```text
section_id: market_popular
algorithm: product_popularity_metrics_v1
```

When metric rows do not exist, backend must not fabricate a popular section from price, image existence, ingredient score, or inventory mock data.

## Later Aggregation

Future cart/order/review/event work should aggregate into `product_popularity_metrics`.

Examples:

- `event_logs.product_viewed` -> `view_count`
- `event_logs.home_product_impression` -> `home_product_impression_count`
- `event_logs.home_product_click` -> `home_product_click_count`, `click_count`
- `event_logs.search_result_impression` -> `search_result_impression_count`
- `event_logs.search_result_click` -> `search_result_click_count`, `click_count`
- `event_logs.wishlist_added` -> `wishlist_add_count`
- `event_logs.cart_added` -> `cart_add_count`
- `event_logs.checkout_started` with `metadata_json.product_ids` -> `checkout_start_count`
- `event_logs.order_completed` joined with `order_items` -> `paid_order_count`, `order_count`, `units_sold`
- reviews table -> `review_count`, `average_rating`

Current manual rollup entrypoint:

```bash
python -m app.cli.rollup_product_popularity --window-days 7
```

Shell wrapper for scheduler/ops use:

```bash
apps/backend/scripts/rollup_product_popularity.sh
```
