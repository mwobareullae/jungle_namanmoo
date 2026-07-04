# Home Sections API Contract

## Purpose

P2 home uses one endpoint for both cold-start visitors and logged-in users:

```text
GET /api/home/sections
```

Frontend should not hard-code product lists. It renders the sections returned by this endpoint.

R4 owns the ranking policy and candidate generation logic. Backend owns DB/API implementation. Frontend owns display.

## Modes

| User state | API mode | Section copy | Source |
|---|---|---|---|
| Non-login | `cold_start` | `추천 예시` | `home_cold_start_p2_candidates.csv` or equivalent DB query |
| Login, no skin profile | `cold_start` + profile CTA | `추천 예시` | Same as non-login |
| Login, skin profile exists | `member` | `내 피부 기준 추천` | user profile + product/effect/concentration data |

`market_popular` is available only when `product_popularity_metrics` rows exist for the requested window. Do not fabricate popularity from price, image availability, ingredient score, or inventory mock data.

## Request

P2 minimum:

```http
GET /api/home/sections?limit_per_section=5
```

Optional query params for local preview and QA:

| Param | Meaning |
|---|---|
| `skin_type` | Used only when auth/profile is not wired yet |
| `sensitivity` | Used only when auth/profile is not wired yet |
| `category_code` | Optional category narrowing; not required for P2 home |
| `limit_per_section` | Default 5 |

In production, login state and saved profile should come from auth/session, not from user-controlled query params.

## Response

```json
{
  "mode": "member",
  "skin_type": "수부지",
  "sensitivity": "보통",
  "category_code": null,
  "sections": [
    {
      "section_id": "profile_focus",
      "title": "내 피부 기준 추천",
      "subtitle": "피부 고민, 피부 타입, 민감도, 성분 근거, 함량, 가격을 함께 본 종합 추천입니다.",
      "section_type": "member_home_personalized",
      "algorithm": "member_home_profile_v1",
      "products": [
        {
          "product_id": "prod_oy_a000000203792",
          "brand": "도미나스",
          "name": "[기미잡티 개선] 도미나스 앳클리닉 트라넥삼산 스팟 샷 기미잡티 앰플 30ML",
          "category_code": "serum",
          "category_name": "serum",
          "thumbnail_url": "https://...",
          "lowest_price": 30400,
          "original_price": null,
          "discount_rate": null,
          "purchase_url": null,
          "badges": ["내 피부 기준"],
          "tags": ["트라넥사믹애씨드", "나이아신아마이드", "비사보롤"],
          "reason_summary": "수부지·보통 피부 조건과 미백·톤 고민을 종합해 봤어요.",
          "display_score": 88.29
        }
      ]
    }
  ]
}
```

## Cold-start Sections

Cold-start means the user has not provided skin concern/profile yet. These are examples, not personalization.

| `section_id` | Title | Product count | Copy | Availability |
|---|---|---:|---|---|
| `market_popular` | 지금 인기 있는 제품 | 5 | `인기 상품` | Only when `product_market_signals.csv` or equivalent DB fields exist |
| `moisture_barrier` | 보습·장벽 예시 | 5 | `추천 예시` | P2 |
| `calming` | 진정 예시 | 5 | `추천 예시` | P2 |
| `brightening` | 미백·톤 예시 | 5 | `추천 예시` | P2 |

Do not expose acne/sebum, wrinkle, or exfoliation cold-start sections in P2.

## Member Sections

Member home uses saved profile and concern/effect state. The three sections must represent different decision criteria, not duplicate the same score under different names.

| `section_id` | Title | Product count | Criterion | Availability |
|---|---|---:|---|---|
| `profile_focus` | 내 피부 기준 추천 | 5 | Overall personalized score | P2 |
| `market_popular` | 지금 인기 있는 제품 | 5 | Market popularity score | Only when market signal data exists |
| `evidence_confident` | 근거가 뚜렷한 추천 | 5 | Stronger evidence/concentration signal | P2 |
| `price_value` | 가격까지 좋은 추천 | 5 | Personalized candidates with better price accessibility | P2 |

Do not create a separate `민감도 고려` section for P2. Sensitivity is already part of `profile_focus` through `sensitivity_fit_score` and `risk_penalty`.

## Ranking Inputs

| Signal | Meaning |
|---|---|
| `axis_score` | Ingredient-effect match score for the target effect axis |
| `coverage_score` | Concentration coverage signal from `concentration_coverage_estimates.csv` |
| `profile_fit_score` | Product fit for the user's skin type |
| `sensitivity_fit_score` | Product fit for sensitive skin |
| `price_score` | P2 home price accessibility |
| `risk_penalty` | Risk flag penalty; stronger for sensitive users |
| `market_popularity_score` | Review/rating/sales/recent-signal based popularity score |

## Market Popularity Inputs

Runtime home API reads `product_popularity_metrics` through the same service used by `GET /api/products/popular`.

`data/product_market_signals.csv` is mock/sample input unless the team explicitly decides to import it. It must not be treated as real service behavior data by default.

Source metric schema:

| Column | Meaning |
|---|---|
| `product_id` | FK to products |
| `window_days` | Popularity window, for example 7 or 14 |
| `view_count` | Product view count |
| `click_count` | Product click count |
| `cart_add_count` | Cart-add count |
| `order_count` | Order count |
| `units_sold` | Sold quantity |
| `review_count` | Review volume |
| `average_rating` | Average rating, expected 0-5 scale |
| `popularity_score` | Precomputed final popularity score |
| `score_version` | Popularity score formula version |
| `computed_at` | Metric snapshot timestamp |

Runtime rule:

```text
home API orders by product_popularity_metrics.popularity_score desc
```

Rules:

- `popularity_score` is precomputed before API reads it.
- Count-like values should use log normalization when the batch calculation is implemented so one viral product does not dominate the whole section.
- Rating should use Bayesian adjustment so a product with very few reviews and 5.0 rating does not outrank established products too easily.
- Recent behavior should use the metric row's `window_days`.
- `product_inventory.csv` is not a market signal because current inventory is `AUTO_SEED` mock data.

## Member Score Weights

All components are normalized to a 0-100 scale before weighting.

```text
profile_focus =
  axis_score * 0.45
  + coverage_score * 0.18
  + profile_fit_score * 0.25
  + sensitivity_fit_score * 0.05
  + price_score * 0.07
  - risk_penalty

evidence_confident =
  axis_score * 0.35
  + coverage_score * 0.35
  + profile_fit_score * 0.15
  + sensitivity_fit_score * 0.05
  + price_score * 0.10
  - risk_penalty

price_value =
  axis_score * 0.30
  + coverage_score * 0.12
  + profile_fit_score * 0.20
  + sensitivity_fit_score * 0.08
  + price_score * 0.30
  - risk_penalty
```

## Display Contract

Frontend renders both cold-start and member sections with the same readable rail pattern.

| Rule | Required behavior |
|---|---|
| Product count | API returns up to 5 products per section |
| Desktop visible count | Show 4 readable cards at once |
| Fifth product | Keep it in the same horizontal rail via scroll |
| Section equality | Do not make one home section visually larger or ranked like a best-seller block |
| Cold-start badge | `추천 예시` |
| Member badge | `내 피부 기준` or equivalent |
| Product click | Goes to product detail |

## Data Regeneration

```bash
python data/scripts/build_concentration_coverage_estimates.py
python data/scripts/build_home_cold_start_candidates.py
python data/scripts/build_home_personalized_candidates.py
```

Current generated snapshots:

| File | Use |
|---|---|
| `data/reconciliation/home_cold_start_p2_candidates.csv` | P2 non-login home fixture |
| `data/reconciliation/home_personalized_profile_candidates.csv` | P2 member home profile fixture |

These CSVs are deterministic snapshots for the current data version. Later, backend can replace them with DB queries or materialized tables using the same section IDs and score logic.
