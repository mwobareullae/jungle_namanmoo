# 반품·교환·환불 신청 API 초안

이 문서는 프론트의 주문 상세 → 신청 페이지 UI가 사용하는 데이터 기준으로 작성한 백엔드 협의용 초안이다. 현재 프론트는 신청 내용을 전송하지 않으며, 백엔드 계약 확정 후 연결한다.

## POST `/api/orders/{order_code}/return-requests`

인증된 사용자가 배송 완료 주문의 상품에 대해 반품·교환·환불 신청을 생성한다.

### 인증·검증

- 인증: 로그인 필수
- 주문 소유자: 현재 사용자 주문만 허용
- 주문 상태: `DELIVERED`에서만 허용(정책상 허용 기간은 백엔드 설정)
- `order_item_id`: 해당 주문에 포함된 상품이어야 함
- 중복 신청: 같은 주문 상품에 처리 중인 신청이 있으면 거절

### 요청 JSON

```json
{
  "order_code": "ORD-20260713-0001",
  "order_item_id": 123,
  "request_type": "RETURN",
  "reason": "DEFECTIVE",
  "detail": "펌프가 눌리지 않습니다.",
  "images": ["return-requests/2026/07/abc.jpg"]
}
```

| 필드 | 타입 | 필수 | 허용값/비고 |
| --- | --- | --- | --- |
| `order_code` | string | O | 주문번호(경로의 주문번호와 일치해야 함) |
| `order_item_id` | integer | O | 주문 상세 상품 ID |
| `request_type` | string | O | `RETURN`, `EXCHANGE`, `REFUND` |
| `reason` | string | O | `CHANGE_OF_MIND`, `DEFECTIVE`, `WRONG_ITEM`, `OTHER` |
| `detail` | string | X | 최대 1,000자 |
| `images` | string[] | X | 업로드 완료 후 반환된 이미지 키, 최대 개수/용량은 백엔드 정책 |

### 성공 응답 `201`

```json
{
  "request_id": "rr_01J...",
  "order_code": "ORD-20260713-0001",
  "order_item_id": 123,
  "request_type": "RETURN",
  "reason": "DEFECTIVE",
  "status": "REQUESTED",
  "created_at": "2026-07-13T01:20:00Z"
}
```

### 오류

- `401`: 로그인 필요
- `403`: 주문 소유자가 아니거나 신청 불가 상태
- `404`: 주문 또는 주문 상품 없음
- `409`: 이미 처리 중인 신청 존재
- `422`: 필드 검증 실패

### 결제·환불 처리 기준

신청 생성과 Toss 환불 실행은 분리한다. 신청 API는 먼저 `REQUESTED` 상태를 저장하고,
검수·회수 확인 이후 백엔드 작업자가 환불을 실행한다.

- 결제 수단이 `MOCK`이면 결제/주문/재고 상태만 내부 트랜잭션으로 처리한다.
- 결제 수단이 `TOSS`이면 저장된 `provider_payment_key`를 사용해 서버에서 Toss 취소 API를 호출한다. 브라우저가 Toss secret key를 직접 사용하지 않는다.
- 전액 환불은 결제 잔액 전체를 취소하고, 부분 환불은 `cancelAmount`와 환불 사유를 함께 전달한다.
- Toss 응답의 `paymentKey`, `status`, 취소 금액을 검증한 뒤 `REFUND_REQUESTED` → `REFUNDED` 또는 `PARTIALLY_REFUNDED`로 전이한다.
- 네트워크 오류·응답 불일치·중복 요청은 `UNKNOWN`/재처리 대상으로 남기고, 동일 신청에 대한 중복 환불을 멱등키로 차단한다.
- 교환은 환불 완료 전에 대체 배송 가능 여부와 추가 결제 금액을 먼저 확정해야 하며, 회수·재배송 자동화는 별도 작업이다.

## GET `/api/orders/{order_code}/return-requests`

주문 상세 화면에서 기존 신청 상태를 표시할 때 사용한다. 응답은 `request_id`, `order_item_id`, `request_type`, `reason`, `status`, `created_at`, `updated_at`를 포함한다.
