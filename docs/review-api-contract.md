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
      "updated_at": "2026-07-01T00:00:00Z",
      "is_mine": false,
      "can_edit": false,
      "can_delete": false,
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

로그인 사용자가 작성한 자사몰 리뷰는 마스킹한 작성자 이름을 노출합니다. 현재 사용자의 리뷰이면 `is_mine=true`이며 공개 상태의 자사몰 리뷰에만 `can_edit`, `can_delete` 권한을 반환합니다.

## 구매 리뷰 작성

```text
POST /api/products/{product_id}/reviews
```

로그인이 필요하며 본인 주문의 `OrderItem.status=DELIVERED`인 상품만 작성할 수 있습니다. 주문 상품과 경로의 상품 ID가 일치해야 하며 주문 상품 하나당 `GENERAL` 리뷰 하나만 활성화할 수 있습니다.

```json
{
  "order_item_id": 123,
  "rating": 5,
  "review_text": "촉촉하고 자극이 적었어요.",
  "is_repurchase_review": true
}
```

- `rating`: 필수, 1~5
- `review_text`: 필수, 공백 제거 후 1~2,000자
- `is_repurchase_review`: 선택, `true`, `false`, `null`
- 서버 설정값: `source=mubarelle`, `review_type=GENERAL`, `status=PUBLISHED`, `verified_purchase=true`
- 작성 당시 저장된 피부 타입·민감도·피부 고민을 프로필 라벨로 snapshot합니다.
- 삭제된 동일 주문 상품 리뷰가 있으면 새 행을 만들지 않고 tombstone을 재활성화합니다.

성공 응답은 `201`이며 작성된 리뷰와 최신 `review_summary`를 반환합니다. 로그인 실패는 `401`, 주문 상품을 찾을 수 없으면 `404`, 배송완료 전이거나 이미 활성 리뷰가 있으면 `409`입니다.

## 구매 리뷰 수정·삭제

```text
PATCH  /api/reviews/{review_id}
DELETE /api/reviews/{review_id}
```

수정과 삭제는 로그인 사용자가 작성한 `source=mubarelle` 리뷰에만 허용합니다. 존재하지 않는 리뷰와 다른 사용자의 리뷰는 모두 `404`로 응답합니다.

PATCH는 `rating`, `review_text`, `is_repurchase_review` 중 하나 이상을 받습니다. 상품·주문 상품·작성자·리뷰 유형·구매 인증 여부는 변경할 수 없으며 수정해도 최초 `reviewed_at`은 유지합니다.

DELETE는 물리 삭제하지 않고 즉시 tombstone으로 전환합니다.

```text
status=DELETED
deleted_at=현재 시각
rating/review_text/option/재구매/구매인증/source metadata=null
프로필 라벨 삭제
```

삭제 즉시 공개 목록에서 제외하고 해당 상품 리뷰 지표를 다시 계산합니다. 동일 사용자가 DELETE를 반복하면 동일한 삭제 결과를 반환합니다.

## 내 리뷰와 작성 가능 주문 상품

```text
GET /api/me/reviews?page=1&page_size=20
GET /api/me/reviewable-order-items?page=1&page_size=20
```

`page_size`는 기본 20, 최대 50입니다. 내 리뷰 목록은 삭제되지 않은 자사몰 리뷰와 상품 snapshot을 반환합니다. 작성 가능 주문 상품 목록은 본인의 `DELIVERED` 주문 상품을 반환하며 활성 리뷰가 없거나 `DELETED`이면 `can_write=true`입니다.

## 집계와 검색 동기화

작성·수정·삭제 transaction 안에서 해당 상품 단위 review rollup을 실행하므로 상품 상세와 추천 점수는 commit 즉시 새 지표를 사용합니다. commit 이후 일반 검색 Elasticsearch 문서를 상품 단위로 best-effort 재색인합니다. ES 동기화 실패는 리뷰 transaction을 되돌리지 않으며 성능 로그를 남긴 뒤 운영 full reindex로 복구합니다.
