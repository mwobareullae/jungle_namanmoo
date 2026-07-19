# 관리자 운영 대시보드 집계 API 계약

상태: 구현 완료 (M5 Chunk 1, 2026-07-19)

## 엔드포인트

`GET /api/admin/dashboard/summary`

관리자 공통 인증이 필요하다. 역할별 권한 조건은 M-Auth 범위다.

## 응답

```json
{
  "order_summary": {
    "pending_payment_count": 0,
    "preparing_shipment_count": 0,
    "cancel_requested_count": 0,
    "reserved_quantity_total": 0
  },
  "ingredient_review_summary": {
    "pending_count": 0,
    "held_count": 0,
    "needs_review_count": 0,
    "unclassified_count": 0,
    "approved_count": 0,
    "rejected_count": 0
  },
  "product_stats": {
    "total_count": 0,
    "recommendable_count": 0,
    "image_missing_count": 0
  },
  "stock_status_breakdown": {
    "in_stock_count": 0,
    "low_stock_count": 0,
    "sold_out_count": 0,
    "hidden_count": 0,
    "unknown_count": 0
  }
}
```

- `order_summary`는 기존 `AdminOrderSummary`를 그대로 사용한다. 날짜 범위를 적용한
  오늘 집계가 아니라 주문 상태별 현재 전체 건수다.
- `ingredient_review_summary`는 기존 `IngredientMappingSummary`를 그대로 사용한다.
- `image_missing_count`는 `ProductImage`가 하나도 없는 상품 수다.
- 재고 상태는 M4 `build_product_availability`와 같은 우선순위로 계산한다.
  `UNKNOWN`은 재고 행이 없는 예외 상품을 위한 상태다.

## 제외

업로드 실행 이력, 상품명 중복 후보, 검색 색인·임베딩 관측은 이 API에 포함하지 않는다.
