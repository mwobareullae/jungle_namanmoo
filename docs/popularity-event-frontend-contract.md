# Popularity Event Frontend Contract

This document defines the frontend events needed to make `GET /api/products/popular` and the home `market_popular` section use real behavior data.

The backend already accepts these events and can roll them up into `product_popularity_metrics`.

## Endpoint

Use batch sending for impressions.

```http
POST /api/events/batch
```

Use single event sending for simple click actions if batching is not convenient.

```http
POST /api/events
```

Required identity headers on every request:

```http
X-MWBL-Anonymous-User-Id: anon_xxx
X-MWBL-Session-Id: sess_xxx
```

Logged-in requests may also be tied to the backend session cookie. The headers should still be sent so pre-login and post-login behavior can be connected later.

## Events Required For Popular Products

| Event | When to send | Required fields |
|---|---|---|
| `home_product_impression` | A home product card is actually visible | `event_id`, `product_id`, `rank`, `page`, `source`, `metadata.section_id` |
| `home_product_click` | User clicks a home product card | `event_id`, `product_id`, `rank`, `page`, `source`, `metadata.section_id` |
| `search_result_impression` | A search/recommendation result card is actually visible | `event_id`, `product_id`, `rank`, `page`, `source`, `metadata.section_id` |
| `search_result_click` | User clicks a search/recommendation result card | `event_id`, `product_id`, `rank`, `page`, `source`, `metadata.section_id` |

Recommended values:

| Field | Home popular section | Search/recommendation result |
|---|---|---|
| `page` | `home` | `search` or `recommendation_result` |
| `source` | `market_popular` | `search_result` or `recommendation_result` |
| `metadata.section_id` | `market_popular` | `search_results` or `recommendation_results` |

## Impression Rule

Do not send impression events when cards are merely rendered in the DOM.

Send an impression when:

- at least 50% of the product card is visible
- visibility lasts at least 0.5 seconds
- the same product/section/page/session/rank combination has not already been sent

Frontend implementation recommendation:

```text
IntersectionObserver
-> visible ratio >= 0.5
-> timer 500ms
-> dedupe key = session_id + page + section_id + product_id + rank
-> POST /api/events/batch
```

Batch size should be 50 or fewer events because the backend limit is 50.

## Payload Examples

Home impression batch:

```json
{
  "events": [
    {
      "event_id": "home-popular-prod-001-1",
      "event_name": "home_product_impression",
      "product_id": "prod_001",
      "rank": 1,
      "page": "home",
      "source": "market_popular",
      "metadata": {
        "section_id": "market_popular"
      }
    }
  ]
}
```

Home click:

```json
{
  "event_id": "home-popular-prod-001-click-1",
  "event_name": "home_product_click",
  "product_id": "prod_001",
  "rank": 1,
  "page": "home",
  "source": "market_popular",
  "metadata": {
    "section_id": "market_popular"
  }
}
```

Search result click:

```json
{
  "event_id": "search-prod-001-click-1",
  "event_name": "search_result_click",
  "product_id": "prod_001",
  "rank": 3,
  "page": "search",
  "source": "search_result",
  "metadata": {
    "section_id": "search_results",
    "query_id": "optional_query_id"
  }
}
```

## Do Not Send

Do not include sensitive or raw personal data in event metadata.

Forbidden examples:

- email
- phone
- address
- password/token
- raw user concern text
- raw LLM prompt/response
- payment/card information

## Backend Usage

Backend rollup maps events as follows:

| Event | Metric |
|---|---|
| `home_product_impression` | `home_product_impression_count` |
| `home_product_click` | `home_product_click_count`, `click_count` |
| `search_result_impression` | `search_result_impression_count` |
| `search_result_click` | `search_result_click_count`, `click_count` |

The rollup result affects `product_popularity_metrics.popularity_score`, which is used by:

- `GET /api/products/popular`
- `GET /api/home/sections` when the `market_popular` section exists
