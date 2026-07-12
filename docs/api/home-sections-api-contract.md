# Home Section APIs Contract

## Purpose

Home sections are loaded through separate APIs so the frontend can lazy-load each rail and infra can measure each section independently.

The old bundled endpoint is removed:

```text
GET /api/home/sections
```

This is not a ranking rewrite. The existing `market_popular` and `evidence_picks` logic must stay intact; the change is API separation. Only `for_you` is upgraded into a personalized section.

## Endpoints

```text
GET /api/home/layout
GET /api/home/market-popular
GET /api/home/evidence-picks
GET /api/home/for-you
```

## Layout

`GET /api/home/layout` returns only section metadata and endpoint URLs. It must not load or rank products.
The section order is `market_popular`, `for_you`, then `evidence_picks`.

```json
{
  "sections": [
    {
      "section_id": "market_popular",
      "title": "지금 인기있는 제품",
      "subtitle": "최근 행동, 구매, 리뷰 신호를 함께 본 인기 상품",
      "section_type": "market_popular",
      "endpoint": "/api/home/market-popular",
      "lazy_load": true
    }
  ]
}
```

## Product Section Response

`market-popular`, `evidence-picks`, and `for-you` return the same section-level shape:

```json
{
  "section_id": "for_you",
  "title": "너를 위한 추천",
  "subtitle": "피부 프로필과 행동 신호를 함께 본 맞춤 후보",
  "section_type": "personalized_rank",
  "algorithm": "home_v1_for_you_personalized",
  "category_code": null,
  "limit": 8,
  "skin_type": "건성",
  "sensitivity": "높음",
  "personalization_sources": ["manual_skin_profile", "skin_test_context"],
  "products": [
    {
      "product_id": "prod_001",
      "brand": "brand",
      "name": "product",
      "category_code": "serum",
      "category_name": "serum",
      "thumbnail_url": "products/prod_001/thumbnail.jpg",
      "lowest_price": 19900,
      "original_price": null,
      "discount_rate": null,
      "purchase_url": null,
      "badges": ["추천"],
      "tags": ["보습"],
      "reason_summary": "추천 이유",
      "display_score": 88
    }
  ]
}
```

## Market Popular

```text
GET /api/home/market-popular?limit=8&category_code=serum
```

Rules:

- Reuses `get_popular_product_items()`.
- Reads `product_popularity_metrics`.
- Sorts by the existing popularity service order.
- Does not fabricate popularity from price, image availability, ingredient score, or inventory mock data.

Algorithm:

```text
product_popularity_metrics_v1
```

## Evidence Picks

```text
GET /api/home/evidence-picks?limit=8&category_code=serum
```

This preserves the existing evidence ranking formula:

```text
evidence_picks_score =
  evidence_score * 0.50
+ effect_score   * 0.35
+ quality_score  * 0.15
```

Algorithm:

```text
home_v0_ingredient_evidence
```

## For You

```text
GET /api/home/for-you?limit=8&category_code=serum&skin_type=dry&sensitivity=high&concern=moisture&effect=barrier
```

Personalization priority:

```text
request-selected context
> saved manual SkinProfile
> latest skin-test soft context
> fallback
```

Scoring:

```text
for_you_score =
  manual_profile_fit      * 0.22
+ behavior_affinity       * 0.22
+ selected_context_fit    * 0.16
+ skin_test_context_fit   * 0.12
+ ingredient_effect_score * 0.10
+ evidence_score          * 0.08
+ popularity_score        * 0.06
+ price_score             * 0.04
```

Missing components are excluded and the remaining weights are normalized.

Personalization sources:

| Source | Meaning |
|---|---|
| `request_context` | User selected query values such as skin type, sensitivity, concern, or effect. |
| `manual_skin_profile` | Logged-in user's saved manual `SkinProfile`. |
| `skin_test_context` | Latest skin-test result, applied as soft context. |
| `behavior_affinity` | Wishlist, recent view, cart, purchase, or click-derived preference profile. |
| `fallback` | No usable request/user context exists. |

## Logging

Each endpoint emits its own performance event:

| Event | API |
|---|---|
| `home_layout_completed` | `GET /api/home/layout` |
| `home_market_popular_completed` | `GET /api/home/market-popular` |
| `home_evidence_picks_completed` | `GET /api/home/evidence-picks` |
| `home_for_you_completed` | `GET /api/home/for-you` |
