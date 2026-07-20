# 관리자 재고·가격 API 계약

작성일: 2026-07-18  
상태: **Chunk 1~4 구현 완료 / 다음: Chunk 5 프론트 연결**

이 문서는 사입 자사몰의 관리자 재고·가격 API 계약이다. 모든 엔드포인트는 관리자 세션 인증을 요구하며, M-Auth 도입 전에는 역할 계층 조건을 추가하지 않는다.

## 가격 변경

```text
PATCH /api/admin/inventory/{product_code}/price
```

### 요청

```json
{
  "price": 21900
}
```

| 필드 | 규칙 |
| --- | --- |
| `price` | KRW 정수, 1 이상 100,000,000 이하 |

가격 변경 사유는 받지 않는다. 가격 이력 저장은 M4 범위 밖이다.

### 성공 응답

```json
{
  "changed": true,
  "product_code": "prod_mwbl_example",
  "price": 21900,
  "currency": "KRW",
  "is_lowest": true,
  "collected_at": "2026-07-18T12:00:00Z",
  "updated_at": "2026-07-18T12:00:00Z"
}
```

- `changed=true`: 가격이 실제로 바뀌었거나 가격 행이 없어 새로 생성됐다. `ProductPrice.collected_at`과 `Product.updated_at`을 함께 갱신한다.
- `changed=false`: 현재 자사 가격과 요청 가격이 같다. 재시도 성공으로 취급하며 가격 행·`Product.updated_at`·ES 재색인을 바꾸지 않는다.
- 자사 가격 행은 `mall_name=자사 운영몰 표시명`, `currency=KRW`, `is_lowest=true`로 유지한다. 가격 행이 없는 예외 상품은 같은 규칙으로 생성한다.

### 오류

| HTTP | 코드 | 상황 |
| ---: | --- | --- |
| 400 | `INVALID_PRICE` | `price`가 정수가 아니거나 1~100,000,000 범위를 벗어남 |
| 401 | `INVALID_SESSION` | 관리자 세션이 없음 또는 만료됨 |
| 404 | `PRODUCT_NOT_FOUND` | `product_code`에 해당하는 상품이 없음 |
| 409 | `PRODUCT_PRICE_INCONSISTENT` | 같은 상품·자사 운영몰 가격 행이 둘 이상 존재함 |

기존 `PATCH /api/admin/products/{product_code}`의 `price` 필드도 같은 1~100,000,000 규칙을 적용한다. 다만 기존 API의 가격 검증 실패 응답 코드는 호환성을 위해 `INVALID_PRODUCT_FIELD`를 유지한다.

## 판매 시작

```text
POST /api/admin/inventory/{product_code}/sale-start
```

요청 본문은 없다. 판매 시작은 일반 필드 수정이 아니라 `HIDDEN → ON_SALE` 상태 전환 액션이다.

### 성공 응답

```json
{
  "product_code": "prod_mwbl_example",
  "sales_status": "ON_SALE",
  "is_active": true,
  "started_at": "2026-07-19T10:00:00Z"
}
```

### 검증과 처리 순서

1. 상품과 재고 행을 각각 `FOR UPDATE`로 조회한다.
2. 재고 행이 없거나 가용 재고(`stock_quantity - reserved_quantity - safety_stock`)가 0 이하이면 판매를 시작하지 않는다.
3. 재고 행의 `sales_status`가 `HIDDEN`이 아니면(`ON_SALE`, `SOLD_OUT` 포함) 판매를 시작하지 않는다.
4. 자사 운영몰 가격 행이 있고 가격이 양수인지 확인한다.
5. 상품이 이미 연결한 브랜드·카테고리가 현재 활성 상태인지 확인한다.
6. 같은 트랜잭션에서 `Inventory.sales_status=ON_SALE`, `Product.is_active=true`, `Product.updated_at`을 갱신하고 flush한다. 라우트가 commit한 뒤 ES 신규 색인을 best-effort로 실행한다.

M3-A의 `PRODUCT_NOT_READY_FOR_ACTIVATION` 코드 경로를 호출하지 않는다. Chunk 4의 위 조건은 가격·가용 재고·현재 분류 활성 상태까지 직접 확인하므로, 준비되지 않은 상품을 판매하지 못하게 한다는 기존 게이트의 목적을 더 강하게 자체 충족한다.

| HTTP | 코드 | 상황 |
| ---: | --- | --- |
| 401 | `INVALID_SESSION` | 관리자 세션이 없거나 만료됨 |
| 404 | `PRODUCT_NOT_FOUND` | 해당 `product_code` 상품이 없음 |
| 409 | `PRODUCT_NOT_HIDDEN` | `ON_SALE` 또는 `SOLD_OUT` 등 HIDDEN이 아닌 상품에 요청함 |
| 409 | `PRICE_NOT_READY` | 자사 가격 행이 없거나 가격이 양수가 아님 |
| 409 | `INSUFFICIENT_STOCK_FOR_SALE` | 재고 행이 없거나 가용 재고가 0 이하 |
| 409 | `BRAND_INACTIVE` | 현재 연결된 브랜드가 비활성 상태 |
| 409 | `CATEGORY_INACTIVE` | 현재 연결된 카테고리가 비활성 상태 |

브랜드·카테고리 활성 확인은 2026-07-18 로컬 데이터에서 직접 걸리는 HIDDEN 상품이 0건이고, 이를 비활성화하는 관리자 API도 아직 없는 상태다. 재시드·CSV 갱신·향후 비활성화 기능으로 인한 잘못된 판매 시작을 막기 위한 방어 규칙으로 유지한다.

## ES 동기화

가격 변경이 commit된 뒤 다음 규칙으로 best-effort 카탈로그 재색인을 수행한다.

| 상태 | 재색인 |
| --- | --- |
| `ON_SALE` 또는 `SOLD_OUT`, `changed=true` | 실행 |
| `HIDDEN` 또는 `changed=false` | 생략 |
| 판매 시작 성공 (`HIDDEN → ON_SALE`) | 실행 |

재색인 실패는 DB 가격 변경을 롤백하지 않는다. 운영 로그에만 남긴다.

## 유일성 제약 유예

현재 `product_prices`에는 `(product_id, mall_name)` UNIQUE 제약이 없다. 공용 가격 헬퍼는 기존 중복을 `PRODUCT_PRICE_INCONSISTENT`로 감지하지만, 동시 생성 자체를 막을 수는 없다.

2026-07-18 로컬 DB에서는 자사 가격 행 누락과 `(product_id, mall_name)` 중복이 모두 0건이었다. 다중 관리자 계정을 실제 도입하기 전, 데이터 재검증과 UNIQUE 제약 migration을 별도 게이트로 수행한다.
