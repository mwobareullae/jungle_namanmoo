# Popularity Ranking Score

## Purpose

This document defines the MVP v1 popularity score used by `product_popularity_metrics` and `GET /api/products/popular`.

The goal is not to rank products by raw exposure or raw sales only. The score should prefer products that receive meaningful user reactions after being shown: product views, wishlist adds, cart adds, checkout starts, paid orders, and click-through rates from home/search surfaces.

## Core Principle

Do not add impression counts directly to the score.

Bad:

```text
score += impression_count * weight
```

This makes already-exposed products more likely to stay exposed. Impression counts are used as denominators for CTR, not as direct positive points.

Good:

```text
home CTR = home click count / home impression count
search CTR = search click count / search impression count
```

In short:

```text
많이 노출된 상품이 아니라, 노출됐을 때 실제 반응이 좋은 상품을 올린다.
```

## MVP v1 Formula

Korean formula:

```text
인기점수 =
  로그보정(상품상세조회수) * 1.0
  + 로그보정(찜추가수) * 2.5
  + 로그보정(장바구니담기수) * 4.0
  + 로그보정(결제진입수) * 6.0
  + 로그보정(결제완료수) * 10.0
  + 상한처리된 장바구니전환율 * 30
  + 상한처리된 구매전환율 * 60
  + 상한처리된 홈 클릭률 * 20
  + 상한처리된 검색 클릭률 * 15
```

Expanded Korean formula:

```text
인기점수 =
  log(1 + 상품상세조회수) * 1.0
  + log(1 + 찜추가수) * 2.5
  + log(1 + 장바구니담기수) * 4.0
  + log(1 + 결제진입수) * 6.0
  + log(1 + 결제완료수) * 10.0
  + min((장바구니담기수 + 0.9) / (상품상세조회수 + 30), 1.0) * 30
  + min((결제완료수 + 0.15) / (상품상세조회수 + 30), 1.0) * 60
  + min((홈상품클릭수 + 1) / (홈상품노출수 + 50), 1.0) * 20
  + min((검색결과클릭수 + 1) / (검색결과노출수 + 50), 1.0) * 15
```

English/code formula:

```python
popularity_score = (
    math.log1p(product_view_count) * 1.0
    + math.log1p(wishlist_add_count) * 2.5
    + math.log1p(cart_add_count) * 4.0
    + math.log1p(checkout_start_count) * 6.0
    + math.log1p(paid_order_count) * 10.0
    + min((cart_add_count + 0.9) / (product_view_count + 30), 1.0) * 30
    + min((paid_order_count + 0.15) / (product_view_count + 30), 1.0) * 60
    + min((home_product_click_count + 1) / (home_product_impression_count + 50), 1.0) * 20
    + min((search_result_click_count + 1) / (search_result_impression_count + 50), 1.0) * 15
)
```

## Metric Meaning

| Metric | Meaning |
|---|---|
| `product_view_count` | Product detail views. |
| `wishlist_add_count` | Wishlist add events. |
| `cart_add_count` | Cart add events. |
| `checkout_start_count` | Checkout preview/start events. |
| `paid_order_count` | Paid/completed order events. |
| `home_product_impression_count` | Real home product impressions sent by frontend visibility tracking. |
| `home_product_click_count` | Home product clicks. |
| `search_result_impression_count` | Real search result impressions sent by frontend visibility tracking. |
| `search_result_click_count` | Search result clicks. |

## Event Mapping

| Metric | Event source |
|---|---|
| `product_view_count` | `event_logs.event_name = 'product_viewed'` |
| `wishlist_add_count` | `event_logs.event_name = 'wishlist_added'` |
| `cart_add_count` | `event_logs.event_name = 'cart_added'` |
| `checkout_start_count` | `event_logs.event_name = 'checkout_started'` |
| `paid_order_count` | `event_logs.event_name = 'order_completed'` |
| `home_product_impression_count` | `event_logs.event_name = 'home_product_impression'` |
| `home_product_click_count` | `event_logs.event_name = 'home_product_click'` |
| `search_result_impression_count` | `event_logs.event_name = 'search_result_impression'` |
| `search_result_click_count` | `event_logs.event_name = 'search_result_click'` |

## Smoothing Constants

The formula uses Bayesian-style smoothing so products with tiny samples do not jump to the top.

| Term | Formula | Meaning |
|---|---|---|
| Cart conversion prior | `0.9 / 30 = 3%` | Assumes cart conversion starts near 3% until enough views exist. |
| Purchase conversion prior | `0.15 / 30 = 0.5%` | Assumes purchase conversion starts near 0.5% until enough views exist. |
| Home CTR prior | `1 / 50 = 2%` | Assumes home CTR starts near 2% until enough impressions exist. |
| Search CTR prior | `1 / 50 = 2%` | Assumes search CTR starts near 2% until enough impressions exist. |

These are MVP defaults. After real traffic exists, tune them using actual service averages.

## Cap Rule

All ratio terms must be capped at `1.0`.

Reason:

- duplicate events can happen
- click count may exceed impression count because of inconsistent collection windows
- cart/order counts can exceed view counts when sources differ
- tiny denominators can produce unrealistic ratios

Required cap examples:

```python
cart_rate = min((cart_add_count + 0.9) / (product_view_count + 30), 1.0)
purchase_rate = min((paid_order_count + 0.15) / (product_view_count + 30), 1.0)
home_ctr = min((home_product_click_count + 1) / (home_product_impression_count + 50), 1.0)
search_ctr = min((search_result_click_count + 1) / (search_result_impression_count + 50), 1.0)
```

## Window Policy

MVP should support rolling windows.

Initial recommendation:

```text
window_days = 7
```

Recommended table design should allow:

```text
7-day score
30-day score
all-time score if needed
```

Future combined score may use:

```text
final_score = score_7d * 0.7 + score_30d * 0.3
```

Do not overbuild time decay in MVP. A 7-day rolling window is enough for the first working version.

## Candidate Filters

Business filters must run outside the score formula.

Exclude or strongly block products that are not sellable:

- inactive product
- inactive brand
- inactive category
- hidden/sold out/not on sale inventory status
- no usable price
- no usable thumbnail for UI
- no stock or unavailable stock

These are not score penalties. They are eligibility filters.

## Store But Do Not Score Yet

The following signals should be aggregated and stored for analysis, but not included in MVP v1 score yet:

| Metric | Reason not scored in MVP v1 |
|---|---|
| `wishlist_remove_count` | Removal may mean user cleanup, not product dislike. |
| `cart_remove_count` | Removal may mean quantity cleanup, shipping fee issue, or comparison behavior. |
| `cart_quantity_change_count` | Useful operational signal but ambiguous for popularity. |
| `payment_failed_count` | Can be user payment issue, provider issue, or test payment failure. |
| `order_cancel_count` | Can be user convenience issue, inventory issue, payment issue, or test behavior. |

These should remain visible in `product_popularity_metrics` or a related analysis table so later tuning can use them.

## Future Enhancements

Do not include these in MVP v1 unless there is enough data and a clear product reason.

### Negative Signal Penalties

Possible future formula:

```text
score -= log(1 + 장바구니삭제수) * 2.0
score -= log(1 + 찜삭제수) * 1.5
score -= log(1 + 결제실패수) * 3.0
score -= log(1 + 주문취소수) * 4.0
```

This should wait until real logs prove that these signals are reliable product-quality indicators.

### New Product Boost

New products have little behavior data. A weak temporary boost can help exploration.

Example:

```text
new_product_boost = max(0, 1 - days_since_created / 14) * 3
```

Only apply this if product creation/import dates are reliable.

### Review And Rating

Future score may include:

- review count
- average rating
- review recency
- rating confidence smoothing

Do not add raw `average_rating` without review-count smoothing.

### Position Bias Correction

Home/search clicks are affected by position.

Future correction may use:

- `rank`
- `section_id`
- `page`
- `source`
- category-level average CTR
- slot-level average CTR

MVP v1 only stores enough context to analyze this later.

### Diversity Rules

Popularity score alone can produce boring lists. Later home sections may apply:

- max products per brand
- max products per category
- dedupe across sections
- exploration slot for new/underexposed products

These should be ranking post-processing rules, not part of `popularity_score`.

## Current Decision

MVP v1 score includes:

- positive action counts with log smoothing
- cart conversion rate
- purchase conversion rate
- home CTR
- search CTR
- ratio caps
- sellable-product filters
- rolling window support

MVP v1 does not include:

- direct impression count as score
- negative event penalties
- new product boost
- review/rating score
- position-bias correction
- diversity post-processing
