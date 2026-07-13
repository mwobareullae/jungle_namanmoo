# 커머스 액션 에이전트 API 계약

기준일: 2026-07-14

## 목적과 책임 경계

커머스 액션 에이전트는 사용자의 자연어 요청을 서버의 허용된 tool로 변환한다. LLM이 DB나 결제사에 직접 접근하지 않으며, 가격·재고·주소·주문 소유권은 기존 백엔드 서비스가 다시 검증한다.

브라우저를 임의 조작하는 구조가 아니다. 백엔드는 허용 목록에 포함된 `ui_action`을 반환하고 프론트가 해당 화면 동작을 수행한다. 결제 승인은 에이전트가 대신하지 않으며 사용자가 Toss 결제창에서 최종 승인한다.

## API

```text
POST /api/agent/chat
POST /api/agent/tool-calls/{tool_call_id}/confirm
```

두 API 모두 로그인 세션 쿠키를 기준으로 사용자를 식별한다. body의 화면 context는 편의 정보이며 인증·가격·재고 판단의 근거로 신뢰하지 않는다.

### 대화 요청

```json
{
  "message": "장바구니 상품 주문해줘",
  "conversation_id": "conv_optional",
  "context": {
    "page": "cart",
    "route": "/cart",
    "cart_item_ids": [12, 15],
    "address_id": 3
  },
  "recent_messages": [
    {"role": "user", "content": "비슷한 상품 보여줘"},
    {"role": "assistant", "content": "두 상품을 찾았어요."}
  ],
  "last_tool_result": {
    "action_type": "show_products",
    "target": "similar_products",
    "items": [
      {"item_type": "product", "id": "prod_001", "title": "첫 번째 상품"},
      {"item_type": "product", "id": "prod_002", "title": "두 번째 상품"}
    ]
  }
}
```

`recent_messages`는 현재 대화 스레드의 최근 메시지 최대 8개만 전달한다. `last_tool_result`는 직전 결과의 상품·주문 식별자와 표시명만 담으며 가격, 재고, 주소, 결제정보 같은 민감하거나 변동 가능한 값은 포함하지 않는다. 이 값들은 "그거", "두 번째", "아까 상품" 같은 참조 해석에만 사용하며 실제 실행 전 기존 백엔드 서비스가 가격·재고·소유권을 다시 검증한다.

### 확인 요청

```json
{
  "action": "confirm"
}
```

거절할 때는 `action`을 `reject`로 보낸다. 확인 대기 tool call의 기본 만료 시간은 10분이다. 다른 사용자 소유의 tool call, 만료되거나 이미 처리된 tool call은 실행할 수 없다.

## 커머스 Tool

| tool | 동작 | 확인 | 대표 `ui_action` |
| --- | --- | --- | --- |
| `get_cart` | 로그인 사용자의 실제 장바구니 조회 | 없음 | `show_cart` |
| `add_to_cart` | 상품 한 종류를 실제 장바구니에 추가 | 없음 | `show_cart` |
| `compose_cart` | 카테고리·총예산·피부 조건으로 복수 상품 구성안 생성 후 일괄 추가 | 필수 | `open_modal/agent_confirmation`, `show_cart` |
| `prepare_checkout` | 선택 상품과 배송지로 금액·재고 재검증 | 없음 | `show_checkout_preview` |
| `prepare_order` | 주문 내용을 고정하고 확인 대기 상태 생성 | 필수 | `open_modal/order_create_confirm` |

개별 장바구니 추가는 즉시 실행한다. `compose_cart`는 실제 DB의 카테고리, 최저가, 판매·재고 상태, 상품 피부 적합도와 사용자 피부 프로필의 제외 성분을 검증해 총예산 안의 조합을 제안한다. 구성안 조회만으로 장바구니를 바꾸지 않으며 사용자가 확인 API로 승인한 뒤에만 각 상품을 1개씩 같은 요청 트랜잭션에서 추가한다. 기존 장바구니 상품은 삭제하지 않는다. 주문 생성도 반드시 별도의 확인 API를 거친다.

```text
"민감성 피부용 토너와 크림을 5만원 안으로 구성해줘"
→ compose_cart(categories=["toner", "cream"], max_budget=50000)
→ 피부 프로필·제외 성분·가격·재고 재조회
→ 구성 상품과 총액 표시, AWAITING_CONFIRMATION
→ 사용자가 confirm
→ 실제 장바구니 일괄 반영
→ show_cart 반환 및 장바구니 화면 이동
```

## 주문과 Toss 결제 흐름

```text
사용자 주문 요청
→ prepare_checkout 및 장바구니 화면을 거쳐 주문서 이동
→ 주문서에서 사용자가 주문 진행 요청
→ prepare_order
→ 서버가 장바구니·주소·가격·재고 재조회
→ AWAITING_CONFIRMATION 및 주문 확인 모달
→ 사용자가 confirm
→ 기존 order service가 TOSS 주문 생성 및 재고 예약
→ open_payment/toss_payment 반환
→ 프론트가 Toss 결제창 호출
→ 사용자가 Toss에서 최종 승인
→ /payments/toss/confirm에서 금액과 주문을 다시 검증
```

확인 성공 응답의 결제 액션 예시는 다음과 같다.

```json
{
  "tool_call_id": "tool_example",
  "status": "EXECUTED",
  "message": "주문이 생성됐어요. Toss 결제창에서 결제를 완료해 주세요.",
  "ui_action": {
    "type": "open_payment",
    "target": "toss_payment",
    "payload": {
      "order_code": "ord_20260713_example",
      "payment_code": "pay_20260713_example",
      "amount": 32000,
      "currency": "KRW",
      "payment_provider": "TOSS"
    }
  }
}
```

주문 생성의 멱등성 키는 `agent:{tool_call_id}`다. 같은 확인 요청이 재전송돼도 별도 주문을 중복 생성하지 않는다.

## Mock 금지 기준

- 에이전트는 `TOSS` 주문만 만든다.
- 프론트는 Mock 결제 API를 호출하지 않는다.
- 기존 `/api/payments/{payment_code}/mock/confirm` 및 `/mock/fail` 경로는 호환을 위해 URL만 유지하고 항상 `410 MOCK_PAYMENT_DISABLED`를 반환한다.
- DB enum, migration, 과거 주문 조회에 남아 있는 `MOCK` 값은 기존 데이터 호환용이며 신규 결제 수단이 아니다.

## 오류 및 감사 기록

대표 오류는 로그인 필요, 빈 장바구니, 배송지 필요, checkout 불가, 확인 만료, 소유권 불일치다. API 오류는 공통 `error.code`/`error.message` 구조를 따른다.

tool 실행은 `agent_tool_calls`에 사용자, conversation, tool 이름, 입력·출력, 확인 여부, 만료 시각과 최종 상태를 기록한다. 사용자 채팅 원문 전체와 결제 비밀키는 저장하지 않는다.
