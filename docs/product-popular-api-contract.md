# Product Popular API Contract

## Purpose

`GET /api/products/popular` returns products ranked by persisted popularity metrics.

This API does not calculate popularity from raw event/order/review tables on every request. It reads `product_popularity_metrics`, a read model prepared for fast home and best-seller screens.

`data/product_market_signals.csv` is not trusted as real service behavior data. It is only a mock/sample signal file unless a separate import decision is made.

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
- product click events -> `click_count`
- cart add events or cart item history -> `cart_add_count`
- `order_items` after paid/completed order -> `order_count`, `units_sold`
- reviews table -> `review_count`, `average_rating`
