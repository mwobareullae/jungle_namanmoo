# 관리자 재고·가격 API 계약

작성일: 2026-07-18  
상태: **Chunk 1~3 구현 완료 / 다음: Chunk 4 판매 시작 API**

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

## ES 동기화

가격 변경이 commit된 뒤 다음 규칙으로 best-effort 카탈로그 재색인을 수행한다.

| 상태 | 재색인 |
| --- | --- |
| `ON_SALE` 또는 `SOLD_OUT`, `changed=true` | 실행 |
| `HIDDEN` 또는 `changed=false` | 생략 |

재색인 실패는 DB 가격 변경을 롤백하지 않는다. 운영 로그에만 남긴다.

## 유일성 제약 유예

현재 `product_prices`에는 `(product_id, mall_name)` UNIQUE 제약이 없다. 공용 가격 헬퍼는 기존 중복을 `PRODUCT_PRICE_INCONSISTENT`로 감지하지만, 동시 생성 자체를 막을 수는 없다.

2026-07-18 로컬 DB에서는 자사 가격 행 누락과 `(product_id, mall_name)` 중복이 모두 0건이었다. 다중 관리자 계정을 실제 도입하기 전, 데이터 재검증과 UNIQUE 제약 migration을 별도 게이트로 수행한다.
