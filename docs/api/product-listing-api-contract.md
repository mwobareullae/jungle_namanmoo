# Product Listing API Contract

## Purpose

상품 검색과 별도로, 검색어 없이 카탈로그를 탐색하는 화면을 위한 API입니다. 카테고리 전체상품, 브랜드별 상품, 신상품, 가격·평점·리뷰순 목록이 같은 응답 계약을 사용합니다.

상품 카드 재고 필드는 [`product-card-availability-contract.md`](./product-card-availability-contract.md)를 따릅니다.

추천 후보 여부인 `is_recommendable`은 이 API의 노출 조건이 아닙니다. 활성 상품 중 숨김 상품은 제외하고, 품절 상품은 응답에 남기되 정렬에서 판매 가능 상품 뒤로 보냅니다.

## Product listing

```http
GET /api/products?page=1&page_size=20&category_group=skincare&sort=popular
```

Query parameters:

| Param | Meaning |
| --- | --- |
| `page`, `page_size` | 페이지 번호와 크기. 기본 1, 20이며 최대 100 |
| `brand_code` | 반복 가능한 브랜드 코드 필터 |
| `category_code` | 반복 가능한 실제 카테고리 코드 필터 |
| `category_group` | 반복 가능한 서버 관리 대분류 필터. 예: `skincare` |
| `min_price`, `max_price` | 최저 판매가 범위 |
| `min_rating` | 최소 평균 평점 |
| `in_stock` | `true`는 구매 가능한 상품만, `false`는 구매 불가 상품만 |
| `sort` | `popular`, `newest`, `price_low`, `price_high`, `rating`, `review_count` |

`newest`는 `released_at`을 우선 사용하고 값이 없으면 DB 등록 시각 `created_at`을 보조 기준으로 사용합니다. 동점은 `product_code` 오름차순으로 고정합니다.

```json
{
  "items": [
    {
      "product_id": "prod_001",
      "brand_code": "roundlab",
      "brand": "라운드랩",
      "name": "자작나무 수분 크림",
      "category_code": "cream",
      "category_group": "skincare",
      "category_name": "크림",
      "thumbnail_url": "products/prod_001/thumbnail.jpg",
      "lowest_price": 19900,
      "rating": 4.8,
      "review_count": 120,
      "sales_status": "ON_SALE",
      "stock_status": "IN_STOCK",
      "available_quantity": 12,
      "in_stock": true,
      "released_at": "2026-07-12T00:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1,
    "has_next": false,
    "has_prev": false
  },
  "applied_filters": {
    "brand_codes": [],
    "category_codes": [],
    "category_groups": ["skincare"],
    "min_price": null,
    "max_price": null,
    "min_rating": null,
    "in_stock": null
  },
  "sort": "popular"
}
```

`thumbnail_url` 값은 CDN URL이 아닌 `storage_key`입니다.

## Category metadata

```http
GET /api/categories
```

각 실제 카테고리에 서버 관리 대분류와 목록 노출 기준 상품 수를 함께 반환합니다.

```json
{
  "items": [
    {
      "code": "toner",
      "name": "토너",
      "group": "skincare",
      "group_name": "스킨케어",
      "product_count": 123
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `code` | 실제 하위 카테고리 식별자. 상품 목록의 반복 `category_code` 필터 값으로 사용한다. |
| `name` | 화면에 표시할 하위 카테고리명이다. URL이나 필터 식별자로 사용하지 않는다. |
| `group` | 실제 대분류 식별자. 상품 목록의 반복 `category_group` 필터 및 카테고리 URL에 사용한다. |
| `group_name` | 화면에 표시할 대분류명이다. URL이나 필터 식별자로 사용하지 않는다. |
| `product_count` | 목록 노출 기준을 만족하는 상품 수다. |

### Frontend category URL convention

카테고리 화면은 `/api/categories` 응답을 단일 기준으로 사용하며, 프론트에 표시명-코드 정적 매핑을 두지 않습니다.

- 대분류 전체: `/category/{group}` — 예: `/category/skincare`
- 하위 카테고리: `/category/{group}?subcategory={code}` — 예: `/category/mask_pack?subcategory=mask`
- URL의 `subcategory` 값은 API 요청 시 `category_code` 필터로 변환한다. 값은 반드시 해당 `group`에 속한 응답 항목이어야 하며, 일치하지 않거나 존재하지 않는 값은 카테고리를 찾을 수 없는 상태로 처리한다.
- `group`과 `code`는 URL·링크·분석 식별자로 사용되므로, 값 변경이나 삭제가 필요하면 프론트 링크와 관련 분석 설정의 교체·폐기 계획을 함께 수립합니다.

## Brand metadata

```http
GET /api/brands?q=라운&page=1&page_size=50
```

브랜드 코드, 표시명, 목록 노출 기준 상품 수를 페이지네이션으로 반환합니다. 프론트 URL이나 목록 필터에는 표시명 대신 `code`를 사용합니다.

## Operations

`released_at`을 새로 제공하거나 수정한 뒤에는 아래 순서로 반영합니다.

```bash
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python -m app.cli.seed_data --data-dir /data
docker compose exec -T backend python -m app.cli.index_catalog_products_to_elasticsearch --full
```

ES 재색인은 일반 검색의 `sort=newest`가 같은 출시일 기준을 쓰도록 필요합니다. 임베딩 재생성은 필요하지 않습니다.
