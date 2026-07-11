# Review API Contract

리뷰 공개 API는 사전 집계된 `product_review_metrics`와 `PUBLISHED` 원문만 사용합니다. 내부 Bayesian/quality 점수, 출처 리뷰 ID, 내부 사용자 ID와 source metadata는 공개하지 않습니다.

## 상품 상세 요약

`GET /api/products/{product_id}` 응답에 `review_summary`가 추가됩니다.

```json
{
  "review_summary": {
    "review_count": 120,
    "average_rating": 4.62,
    "rating_distribution": {"1": 1, "2": 2, "3": 7, "4": 22, "5": 88},
    "general_review_count": 40,
    "month_use_review_count": 80,
    "repurchase_known_count": 120,
    "repurchase_review_count": 52,
    "repurchase_rate": 0.433333,
    "profile_labeled_review_count": 74,
    "last_reviewed_at": "2026-07-11T00:00:00Z"
  }
}
```

리뷰가 없거나 아직 rollup 전이면 count는 0, 평균·비율·마지막 작성일은 `null`입니다. `review_quality_score`, `bayesian_rating`, `confidence`는 포함하지 않습니다.

## 리뷰 목록

```text
GET /api/products/{product_id}/reviews
```

Query parameter:

| 이름 | 값 |
| --- | --- |
| `cursor` | 이전 응답의 opaque `next_cursor` |
| `limit` | 기본 20, 최대 50 |
| `sort` | `latest`, `helpful`, `rating_high`, `rating_low` |
| `rating` | 1~5 |
| `review_type` | `GENERAL`, `MONTH_USE` |
| `repurchase` | `true`, `false` |
| `skin_type` | 정규화 코드. 예: `dry`, `oily`, `combination`, `normal` |
| `sensitivity` | 정규화 코드. 예: `high` |
| `skin_tone` | 정규화 코드. 예: `summer_cool` |
| `concern` | 정규화 고민 코드. 예: `concern_sensitive` |

모든 정렬은 마지막에 내부 row `id`를 tie-breaker로 사용하는 keyset cursor 방식입니다. cursor는 같은 `sort`에서만 재사용할 수 있습니다.

```json
{
  "product_id": "prod_oy_a000000144177",
  "sort": "latest",
  "limit": 20,
  "items": [
    {
      "review_id": "rev_oy_xxx",
      "rating": 5,
      "review_text": "한 달 사용 후기",
      "reviewed_at": "2026-07-01T00:00:00Z",
      "option_text": "기본",
      "review_type": "MONTH_USE",
      "is_repurchase_review": true,
      "verified_purchase": null,
      "helpful_count": 3,
      "badges": ["한달사용"],
      "author": null,
      "profile_labels": [
        {"dimension": "SKIN_TYPE", "value_code": "dry", "display_label": "건성"}
      ],
      "media": []
    }
  ],
  "next_cursor": null,
  "has_next": false
}
```

외부 seed에는 작성자와 구매 인증을 증명할 정보가 없으므로 `author`, `verified_purchase`는 `null`입니다. 원본에 사진 존재 표식만 있고 실제 URL이 없으므로 `media=[]`이며 사진 리뷰 필터를 제공하지 않습니다.
