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

### Customer frontend category menu URL convention

`GET /api/categories`는 유지하지만, 고객 프론트의 카테고리 패널과 목록 화면은 이 응답을 호출하거나 메뉴 기준으로 사용하지 않습니다. 고객 화면의 메뉴 문구·순서·URL·상품 코드 매핑의 단일 기준은 `apps/frontend/src/constants/categoryMenu.ts`입니다.

- 대분류 전체: `/category/{group}` — 예: `/category/skincare`, `/category/focus-care`, `/category/body-hair`
- 하위 카테고리: `/category/{group}?subcategory={screen-slug}` — 예: `/category/skincare?subcategory=mask-pack`, `/category/focus-care?subcategory=eye-neck-care`
- 화면 URL의 `group`, `subcategory`는 실제 상품 코드와 다를 수 있습니다. 프론트는 고정 설정으로 이를 하나 이상의 반복 `category_code` 필터로 변환해 `GET /api/products`를 호출합니다. 예를 들어 `mask-pack`은 `mask`, `mask_pack`을 함께 조회합니다.
- `hair_body`는 메뉴에서 제외하며, 상품 데이터나 API 필터 값은 삭제하지 않습니다.
- 기존 분류 URL의 리다이렉트·호환 처리는 제공하지 않습니다. 고정 설정과 일치하지 않는 URL은 카테고리를 찾을 수 없는 상태로 처리합니다.
- 메뉴 URL 값 변경·삭제는 고객 링크와 관련 분석 설정에 영향을 주므로, 프론트 설정과 관련 문서를 함께 갱신합니다.

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
