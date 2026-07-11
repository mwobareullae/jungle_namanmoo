# 일반 상품 검색 API 계약 v1

상태: 구현 계약 확정
작성일: 2026-07-11
범위: 일반 상품 검색과 검색어 제안. 피부 고민 추천 API는 변경하지 않는다.

## 1. API 경계

- 상품을 알고 있거나 브랜드·카테고리·가격 조건을 직접 입력하면 일반 상품 검색을 사용한다.
- 무엇을 선택해야 하는지 도움을 요청하면 기존 `POST /api/recommendations`를 사용한다.
- 일반 검색은 로그인 여부와 무관하게 동일한 기본 결과를 반환한다.
- 일반 검색에는 LLM, embedding, pgvector, 피부 프로필, 행동 개인화를 사용하지 않는다.
- 신규 API 검증 후 기존 `GET /api/products/search`는 제거하며 호환 adapter를 두지 않는다.

## 2. 상품 검색

```http
GET /api/search/products
```

### Query parameters

| 이름 | 형식 | 기본값 | 제한 | 의미 |
| --- | --- | --- | --- | --- |
| `q` | string | 필수 | 1~200자 | 사용자 검색 원문 |
| `page` | integer | `1` | 1 이상 | 페이지 번호 |
| `page_size` | integer | `20` | 1~50 | 페이지당 상품 수 |
| `brand` | string[] | 없음 | 반복 가능 | 브랜드 코드 또는 정규화 별칭 |
| `category` | string[] | 없음 | 반복 가능 | 원본 카테고리 코드 또는 통합 그룹 코드 |
| `min_price` | integer | 없음 | 0 이상 | 최소 가격, KRW |
| `max_price` | integer | 없음 | 0 이상 | 최대 가격, KRW |
| `min_rating` | number | 없음 | 0~5 | 최소 평균 평점 |
| `in_stock` | boolean | 없음 | - | `true`면 구매 가능한 재고만 조회 |
| `sort` | enum | `relevance` | 아래 표 참고 | 결과 정렬 |

브랜드와 카테고리는 같은 파라미터를 반복해서 전달한다.

```http
GET /api/search/products?q=수분크림&brand=토리든&brand=라운드랩&category=skincare&max_price=30000
```

API 파라미터로 전달된 필터는 검색어에서 추출한 조건보다 우선한다. `min_price > max_price`는 `400 INVALID_SEARCH_FILTER`로 거절한다.

### Sort

| 값 | 정렬 기준 |
| --- | --- |
| `relevance` | 관련도, 제한된 인기도·평점 보정, 품절 감점 |
| `popular` | 인기도 내림차순, 관련도와 상품 ID로 안정 정렬 |
| `newest` | 상품 생성일 내림차순 |
| `price_asc` | 최저 가격 오름차순, 가격 없음은 마지막 |
| `price_desc` | 최저 가격 내림차순, 가격 없음은 마지막 |
| `rating` | 평균 평점, 리뷰 수 내림차순, 평점 없음은 마지막 |

### Response

```json
{
  "query": "토리든 토너",
  "corrected_query": null,
  "items": [
    {
      "product_id": "prod_oy_a000000256045",
      "brand": "토리든",
      "name": "토리든 다이브인 저분자 히알루론산 토너 500ml",
      "category_code": "toner",
      "category_group": "skincare",
      "category_name": "토너",
      "thumbnail_url": "https://example.com/product.jpg",
      "lowest_price": 19900,
      "rating": 4.72,
      "review_count": 1200,
      "sales_status": "ON_SALE"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 23,
    "total_pages": 2,
    "has_next": true,
    "has_prev": false
  },
  "facets": {
    "brands": [{"value": "토리든", "label": "토리든", "count": 12}],
    "categories": [{"value": "skincare", "label": "스킨케어", "count": 20}],
    "price_ranges": [{"value": "10000_19999", "label": "1~2만원", "count": 8}],
    "availability": [
      {"value": "in_stock", "label": "판매 가능", "count": 18},
      {"value": "sold_out", "label": "품절", "count": 5}
    ]
  },
  "applied_filters": {
    "brands": [],
    "categories": [],
    "min_price": null,
    "max_price": null,
    "min_rating": null,
    "in_stock": null
  },
  "sort": "relevance"
}
```

`lowest_price`와 `rating`은 데이터가 없으면 `null`이다. `review_count`는 집계가 없으면 `0`이다. 재고 행이 없으면 `sales_status=UNKNOWN`으로 반환하며 `in_stock=true` 결과에는 포함하지 않는다.

내부 Elasticsearch 점수, match source, Elasticsearch 실패 사유는 공개 응답에 포함하지 않는다.

## 3. Facet 계약

가격 구간은 다음 값으로 고정한다.

| value | label | 범위 |
| --- | --- | --- |
| `under_10000` | `1만원 미만` | `0 <= price < 10000` |
| `10000_19999` | `1~2만원` | `10000 <= price < 20000` |
| `20000_29999` | `2~3만원` | `20000 <= price < 30000` |
| `30000_49999` | `3~5만원` | `30000 <= price < 50000` |
| `50000_plus` | `5만원 이상` | `price >= 50000` |

통합 카테고리 그룹은 `skincare`, `cleansing`, `bodycare`, `haircare`, `beauty_tool`, `mask_pack`, `suncare`, `makeup`, `nail`, `fragrance`, `men`, `other`를 사용한다. 원본 코드 `unknown`, `accessory`는 `other`, `men_allinone`은 `men`으로 매핑한다.

## 4. 검색어 제안

```http
GET /api/search/suggestions?q=토리&limit=8
```

`q`는 1~100자, `limit`은 기본 8, 최대 20이다.

```json
{
  "query": "토리",
  "items": [
    {"text": "토리든", "type": "BRAND", "product_id": null},
    {
      "text": "토리든 다이브인 저분자 히알루론산 토너 500ml",
      "type": "PRODUCT",
      "product_id": "prod_oy_a000000256045"
    }
  ]
}
```

`type`은 `PRODUCT`, `BRAND`, `CATEGORY`, `CORRECTION` 중 하나다. 제안은 인기 상품을 임의로 섞지 않고 입력 prefix, compact 표기, 초성, 확정 alias에 일치하는 항목만 반환한다.

## 5. 검색 복구와 무결과

- 원 검색 결과가 3건 이상이면 복구 검색을 실행하지 않는다.
- 결과가 0건이면 제한된 복구 검색을 실행한다.
- 결과가 1~2건이면 원 결과를 유지하고 복구 결과를 낮은 우선순위로 보충한다.
- 1~2글자에는 fuzzy 검색을 적용하지 않는다.
- 확실하지 않은 교정은 자동 대체하지 않고 `corrected_query`로만 제안한다.
- 검색 결과가 없을 때 무관한 인기 상품을 `items`에 넣지 않는다.
- 필터 충돌은 필터를 자동 해제하지 않고 빈 결과를 반환한다.

## 6. 검색 대상과 장애

- 활성 상품, 활성 브랜드, 활성 카테고리를 대상으로 한다.
- `HIDDEN`은 제외하고 `SOLD_OUT`은 포함하되 관련도 정렬에서 후순위로 내린다.
- `is_recommendable`은 일반 검색 필터와 점수에 사용하지 않는다.
- Elasticsearch 장애 시 상품코드·상품명·브랜드·카테고리만 지원하는 제한 DB fallback을 사용한다.
- 제한 fallback도 실패하면 `503 SEARCH_UNAVAILABLE`을 반환한다.
- 추천, LLM, embedding, pgvector 결과로 검색 상품을 채우지 않는다.

## 7. Error response

```json
{
  "error": {
    "code": "SEARCH_UNAVAILABLE",
    "message": "상품 검색을 일시적으로 사용할 수 없습니다."
  }
}
```

| HTTP | code | 조건 |
| ---: | --- | --- |
| `400` | `INVALID_SEARCH_FILTER` | 가격 범위 등 필터 조합이 잘못됨 |
| `422` | FastAPI validation | 개별 파라미터 형식·범위가 잘못됨 |
| `503` | `SEARCH_UNAVAILABLE` | Elasticsearch와 제한 DB fallback 모두 실패 |

## 8. 로그와 구매 경계

성능 로그에는 검색어 원문을 저장하지 않는다. 검색어 길이, 결과 수, 교정·자판·초성 사용 여부, fallback 여부, 처리 시간만 기록한다.

검색 결과의 가격·재고는 조회 시 PostgreSQL로 다시 확인한다. 상품 상세, 장바구니, 주문은 기존 transaction 규칙으로 구매 가능 여부를 최종 검증한다.
