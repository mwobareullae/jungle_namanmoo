# Popularity Rollup Operations

This document defines how to run product popularity rollup until a scheduler/worker is attached.

## Purpose

`event_logs` stores raw behavior events. `product_popularity_metrics` is the read model used by home and popular product APIs.

The rollup job converts raw behavior logs into product-level counts and `popularity_score`.

```text
event_logs + order_items
-> rollup_product_popularity
-> product_popularity_metrics
-> GET /api/products/popular
-> GET /api/home/sections market_popular
```

## Manual Command

Run from the backend container/app context:

```bash
python -m app.cli.rollup_product_popularity --window-days 7
```

Dry run:

```bash
python -m app.cli.rollup_product_popularity --window-days 7 --dry-run
```

Shell wrapper:

```bash
apps/backend/scripts/rollup_product_popularity.sh
```

Environment variables supported by the wrapper:

```text
POPULARITY_ROLLUP_WINDOW_DAYS=7
POPULARITY_ROLLUP_DRY_RUN=false
POPULARITY_ROLLUP_COMPUTED_AT=2026-07-06T12:00:00+09:00
```

## Recommended Schedule

MVP recommendation:

```text
manual run during local/dev verification
7-day popularity: every 1 hour
30-day popularity: once per day, for example 03:00 KST
```

Recommended scheduler commands:

```bash
# every hour
python -m app.cli.rollup_product_popularity --window-days 7

# once per day
python -m app.cli.rollup_product_popularity --window-days 30
```

`window_days` is the aggregation range, not the execution interval.

Examples:

| API use | Rollup command | Recommended execution |
|---|---|---|
| Recent popular products | `--window-days 7` | Every 1 hour |
| Steady popular products | `--window-days 30` | Once per day |

The job is idempotent for a given `window_days` and event set. It rewrites the metric row for each product/window pair.

## Success Output

The CLI prints JSON:

```json
{
  "window_days": 7,
  "touched_products": 4,
  "updated_metrics": 36,
  "computed_at": "2026-07-06T14:23:03.156142+00:00",
  "score_version": "behavior_popularity_v1"
}
```

Meaning:

| Field | Meaning |
|---|---|
| `window_days` | Aggregation window. |
| `touched_products` | Products that had behavior in the current window. |
| `updated_metrics` | Metric rows created or refreshed. Existing rows with no current events are reset to zero. |
| `computed_at` | Rollup execution time used as the window end. |
| `score_version` | Popularity scoring formula version. |

## Verification

After running rollup:

1. Check `product_popularity_metrics` rows for `score_version = behavior_popularity_v1`.
2. Call `GET /api/products/popular?window_days=7&limit=10`.
3. Confirm `metrics.home_product_impression_count`, `metrics.home_product_click_count`, and `popularity_score` changed from event data.
4. Confirm `GET /api/home/sections` includes `market_popular` when metric rows exist.

## Current Limitations

- Scheduler/worker attachment is not included yet.
- Review count/rating rollup is not implemented yet.
- Position-bias correction is not implemented yet.
- Frontend must send real visibility-based impression events for high-quality ranking.
