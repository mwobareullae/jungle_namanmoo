# P2 Home Cold-start Candidate Handoff

## Purpose

This handoff is for the first home screen shown before a user enters a skin concern or skin profile.

These products are **recommendation examples**, not personalized recommendations.

Use the label `추천 예시` or equivalent copy. Do not call them `맞춤 추천` until the user submits concern/profile input and the recommendation API responds.

## Files

| File | Use |
|---|---|
| `data/reconciliation/home_cold_start_p2_candidates.csv` | Final P2 home candidate list for frontend display |
| `data/reconciliation/home_cold_start_candidates.csv` | 6-axis analysis draft; acne/sebum and wrinkle are analysis-only, exfoliation currently has no safe candidates |
| `data/reconciliation/concentration_coverage_estimates.csv` | Ingredient concentration coverage layer used during candidate scoring |
| `docs/home-cold-start-ranking.md` | Ranking policy and caveats |

## Regeneration

`home_cold_start_p2_candidates.csv` is a generated snapshot, not a hand-picked fixed list.

When catalog/crawling data changes, regenerate it from the current `data/` files:

```bash
python data/scripts/build_concentration_coverage_estimates.py
python data/scripts/build_home_cold_start_candidates.py
```

For P2, frontend can read the generated CSV as a stable handoff file. Later this should become a batch/CI-generated materialized candidate set after catalog imports.

The output is deterministic for the same input data and script version. Ties are resolved by:

1. higher `home_example_score`
2. higher `axis_score`
3. higher `coverage_score`
4. lower `risk_penalty`
5. lower `price`
6. `category`
7. `brand`
8. `product_id`

## P2 Sections

Expose only these 3 sections in P2:

| Section | Rows | Status |
|---|---:|---|
| `moisture_barrier` / 보습·장벽 예시 | 5 | OK |
| `calming` / 진정 예시 | 5 | OK |
| `brightening` / 미백·톤 예시 | 5 | Strongest coverage |

Do not expose these sections in P2:

| Section | Reason |
|---|---|
| `acne_sebum` | Still overly dependent on phytosphingosine; needs BHA, Zinc PCA, Tea Tree anchors |
| `wrinkle` | Retinol/adenosine candidates exist, but risk and positioning need a separate UX decision |
| `exfoliation` | No safe candidates after excluding retinol; needs AHA/BHA/PHA-specific logic |

## Candidate Rules Already Applied

- `products.is_recommendable=true`
- price exists
- thumbnail exists
- ingredient data exists
- global product dedupe across the 3 P2 sections
- max 1 product per brand per section
- max 2 products per category per section
- product-position keyword filter per section
- niacinamide excluded as representative evidence for moisture and calming
- glycerin excluded as representative evidence
- concentration coverage signal added from `concentration_coverage_estimates.csv`

Note: `data/product_inventory.csv` is `AUTO_SEED` mock inventory for P2 cart/checkout/admin testing. It is not real marketplace inventory and is intentionally not used for this home candidate ranking.

## Concentration Coverage Caveat

The coverage layer follows the v2 concentration coverage strategy:

- `exact`, `range`, `regulatory_anchor` are meaningful signals for home ranking.
- `legal_upper_bound`, `marker_upper_bound`, `lower_bound`, `prior_estimate` are not actual concentrations.
- `marker_upper_bound` and `prior_estimate` are internal weak signals only.
- If a parsed `exact` value exceeds 1% after a 1% marker ingredient, it is treated as parsing noise and is not used as exact coverage.

The brightening section has the strongest public concentration evidence.
Moisture and calming sections have weaker public concentration evidence because skincare products often do not disclose moisture/calming ingredient percentages.

## Frontend Display Contract

Recommended columns for UI:

| Column | Meaning |
|---|---|
| `section_label` | Section title |
| `rank` | Display order inside section |
| `product_id` | Product detail link key |
| `brand` | Brand label |
| `name` | Product name |
| `category` | Product category |
| `price` | Display price |
| `thumbnail_url` | Product image |
| `matched_ingredients` | Evidence ingredient badges |
| `coverage_types` | Internal/debug only; do not show raw values to users |
| `reason_summary` | Short rationale seed |

Do not expose `coverage_basis` directly to users. It contains internal/legal/heuristic notes.

## Suggested User-facing Copy

Section helper copy:

```text
아직 개인화 전이지만, 성분 근거와 함량 정보가 확인된 범위를 함께 본 추천 예시입니다.
```

Product badge:

```text
추천 예시
```

Do not use:

```text
맞춤 추천
내 피부에 딱 맞는 상품
```

until a user has submitted concern/profile input.
