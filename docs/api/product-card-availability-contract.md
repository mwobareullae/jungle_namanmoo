# Product Card Availability Contract

상품 카드가 노출되는 API는 다음 가용성 필드를 공통으로 반환한다.

```json
{
  "sales_status": "ON_SALE",
  "stock_status": "IN_STOCK",
  "available_quantity": 12,
  "in_stock": true
}
```

적용 대상은 상품 목록, 일반 검색, 인기상품, 홈 섹션, 추천 결과, 찜한 상품, 최근 본 상품이다. 기존 필드는 유지하며 위 필드만 추가한다.

## 판정 기준

- `available_quantity = max(stock_quantity - reserved_quantity - safety_stock, 0)`
- `sales_status=HIDDEN`이면 `stock_status=HIDDEN`, `in_stock=false`
- `sales_status=SOLD_OUT` 또는 `available_quantity=0`이면 `stock_status=SOLD_OUT`, `in_stock=false`
- 판매 중이고 가용 재고가 `1~5`이면 `stock_status=LOW_STOCK`, `in_stock=true`
- 판매 중이고 가용 재고가 `6` 이상이면 `stock_status=IN_STOCK`, `in_stock=true`
- 재고 행이 없으면 `sales_status=UNKNOWN`, `stock_status=UNKNOWN`, `available_quantity=null`, `in_stock=false`

프론트는 `UNKNOWN`을 품절로 표시하지 않는다. 명시적인 `SOLD_OUT` 또는 확인된 `available_quantity <= 0`만 품절 UI로 처리한다.

## 품절 응답 예시

```json
{
  "sales_status": "SOLD_OUT",
  "stock_status": "SOLD_OUT",
  "available_quantity": 0,
  "in_stock": false
}
```
