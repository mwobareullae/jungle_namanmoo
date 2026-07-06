# 액션 에이전트 결정 기록

작성일: 2026-07-06

이 문서는 뭐바를래 액션 에이전트를 구현하기 전에 합의한 기준을 남긴다. 목적은 구현 중 방향이 흔들리지 않게 하고, 프론트/백엔드/API/로그가 같은 전제를 보게 하는 것이다.

## 목표

액션 에이전트는 단순 검색 챗봇이 아니다. 사용자가 채팅으로 요청하면 백엔드가 주문/상품/결제 전 단계 같은 실제 커머스 업무를 대신 준비하거나, 확인이 필요한 작업은 확인 요청 상태로 만든다.

예시:

- "방금 결제했던 거 취소해줘"
- "배송 상태 알려줘"
- "이 상품이랑 비슷한 거 보여줘"
- "이 후보들 비교해줘"
- "이 중에서 2만원 이하만 다시 보여줘"

말로 하는 음성 에이전트가 아니라 채팅 기반 에이전트로 만든다.

## MVP 범위

1차 구현에 포함한다.

- 주문 상태 조회
- 최근 주문 취소 요청 준비
- 유사 상품 찾기
- 상품 비교
- 현재 후보군 조건 재탐색
- 프론트가 화면 전환에 쓸 수 있는 `ui_action` 응답
- tool 실행 기록과 확인 대기 상태 저장

1차 구현에서 제외하거나 뒤로 미룬다.

- 음성/realtime agent
- 에이전트가 브라우저 화면을 직접 조작하는 방식
- 결제/환불을 에이전트가 즉시 최종 실행하는 방식
- 여러 전문 agent 간 handoff
- 전체 상품 지식베이스/RAG 고도화
- 키워드 기반 가짜 fallback 답변

## 기술 선택

기본 런타임은 OpenAI Agents SDK를 사용한다.

선택 이유:

- LLM이 tool을 선택하고 인자를 만들기 좋다.
- tool schema와 structured output을 명확히 잡을 수 있다.
- 나중에 guardrail, tracing, eval, multi-agent 확장으로 넘어가기 쉽다.
- FastAPI 서비스 안에서 시작하기 좋고, 현재 백엔드 구조를 크게 흔들지 않는다.

지금 쓰지 않는 선택지:

- Raw function calling만 직접 구현: 단순하지만 agent loop, tracing, 확장 구조를 직접 많이 만들어야 한다.
- LangChain/LangGraph: 복잡한 장기 workflow에는 좋지만 지금은 구현면이 넓고, 주문/상품 tool 중심 MVP에는 과하다.
- AWS Bedrock/AgentCore: AWS 운영, IAM, Knowledge Base, 관리형 guardrail에는 장점이 있지만 지금 당장 기존 FastAPI/DB/tool 구조와 붙이기에는 의사결정과 설정이 커진다.

단, AWS 배포 환경이 커지고 Knowledge Base, IAM, 관리형 guardrail이 중요해지면 Bedrock 계열은 다시 비교한다.

## 데이터 접근 원칙

LLM은 DB를 직접 알지 못하고, 직접 SQL을 만들지도 않는다.

에이전트는 백엔드 tool을 통해서만 데이터를 본다.

- 주문 tool은 현재 로그인한 사용자의 주문만 조회한다.
- 취소 tool은 서버의 주문/결제/재고 서비스를 호출한다.
- 상품 tool은 product/search/recommendation service를 호출한다.
- 가격, 재고, 주문 상태는 프론트 context를 믿지 않고 DB에서 다시 읽는다.

전체 상품 지식은 1차에 LLM prompt에 모두 넣지 않는다. 필요하면 기존 DB 검색, 추천 후보, `search_documents`/pgvector 기반 검색을 tool로 노출한다.

## API 기준

1차 API는 두 개로 둔다.

```text
POST /api/agent/chat
POST /api/agent/tool-calls/{tool_call_id}/confirm
```

`POST /api/agent/chat`은 사용자 메시지와 현재 화면 context를 받아 에이전트 응답을 만든다.

`POST /api/agent/tool-calls/{tool_call_id}/confirm`은 이미 만들어진 확인 대기 tool call을 실행한다. 이 API는 OpenAI 호출 없이 DB와 기존 서비스만으로 동작해야 한다.

## 프론트가 보내는 context

프론트는 채팅 요청마다 현재 화면 맥락을 보낸다. 단, 이 값은 편의 정보일 뿐이고 보안 판단의 기준은 아니다.

```json
{
  "message": "이 상품이랑 비슷한 거 보여줘",
  "conversation_id": "optional-conversation-id",
  "context": {
    "page": "product_detail",
    "route": "/products/prod_001",
    "current_product_id": "prod_001",
    "visible_product_ids": ["prod_001", "prod_002"],
    "selected_product_ids": ["prod_001", "prod_002"],
    "recommendation_id": "optional-recommendation-id",
    "search_query": "수분 세럼",
    "filters": {
      "max_price": 20000
    },
    "order_code": "optional-order-code"
  }
}
```

로그인 사용자는 session cookie로 식별한다. `user_id`를 body로 받지 않는다.

## 응답 기준

에이전트 응답은 텍스트와 화면 액션을 분리한다.

```json
{
  "conversation_id": "conv_...",
  "message": "최근 주문 1건을 찾았어요. 결제 전 주문이라 바로 취소할 수 있습니다.",
  "requires_confirmation": true,
  "tool_call_id": "tool_...",
  "ui_action": {
    "type": "open_modal",
    "target": "order_cancel_confirm",
    "payload": {
      "order_id": "..."
    }
  },
  "items": []
}
```

프론트는 `ui_action`을 보고 화면 이동, 모달 열기, 후보 목록 표시를 수행한다. 백엔드는 브라우저를 직접 조작하지 않는다.

## Tool 정책

읽기 tool은 즉시 실행할 수 있다.

- 주문 상태 조회
- 유사 상품 찾기
- 상품 비교
- 조건 기반 재탐색

쓰기/파괴적 tool은 반드시 확인을 거친다.

- 주문 취소
- 환불/반품/교환
- 결제 진행
- 장바구니 대량 변경

주문 취소는 1차에서 다음 기준으로 둔다.

- `PENDING_PAYMENT` 주문: 확인 후 취소 가능, 재고 예약 해제
- `PAID` 주문: 확인 후 바로 환불하지 않고 취소 요청 상태로 전환
- 배송 이후 상태: 1차에서는 안내 또는 별도 CS/반품 흐름으로 넘김

## 저장 기준

`agent_tool_calls`는 tool 실행과 확인 대기 상태를 남기는 audit 테이블이다.

주요 필드:

- `tool_call_id`
- `conversation_id`
- `user_id`
- `anonymous_user_id`
- `session_id`
- `request_id`
- `tool_name`
- `status`
- `confirmation_required`
- `confirmed_at`
- `executed_at`
- `expires_at`
- `input_json`
- `output_json`
- `error_code`
- `error_message`
- `latency_ms`

상태값:

- `PROPOSED`
- `AWAITING_CONFIRMATION`
- `CONFIRMED`
- `EXECUTED`
- `REJECTED`
- `EXPIRED`
- `FAILED`

확인 대기 만료 시간은 10분을 기본값으로 둔다.

## 원문 저장 정책

1차에서는 아래 원문을 기본 저장하지 않는다.

- LLM prompt 전문
- LLM response 전문
- 사용자 고민/채팅 원문 전체

대신 저장한다.

- tool 이름
- 의도 분류
- redacted preview
- hash
- token/cost/latency
- error code
- 선택된 상품/주문 ID

나중에 디버깅 품질이 부족하면 `agent_messages` 또는 `agent_debug_logs` 같은 별도 테이블을 만들고, 보관 기간/마스킹/접근 권한을 정한 뒤 제한적으로 저장한다.

## Guardrail 기준

1차부터 최소 guardrail을 넣는다.

- 로그인 필요한 tool은 session 기반 인증을 확인한다.
- 주문 tool은 본인 주문만 접근한다.
- 쓰기/파괴적 tool은 확인 API를 거친다.
- tool input은 Pydantic schema로 검증한다.
- `ui_action.type`과 `ui_action.target`은 allowlist로 제한한다.
- prompt/response/개인정보 원문은 로그에 저장하지 않는다.
- 결제/환불 최종 실행은 1차에서 직접 수행하지 않는다.

## 실패 처리

키워드 기반으로 대충 흉내 내는 fallback은 만들지 않는다.

OpenAI 호출이 불가능하면 명확히 실패 응답을 준다.

```json
{
  "error_code": "AGENT_TEMPORARILY_UNAVAILABLE",
  "message": "지금은 에이전트 응답을 만들 수 없습니다. 잠시 후 다시 시도해 주세요."
}
```

단, 확인 API는 OpenAI 없이 실행되어야 한다. 이미 확인 대기 상태로 저장된 주문 취소 같은 작업은 LLM 장애와 무관하게 처리 가능해야 한다.

## 속도 기준

에이전트는 사용자가 채팅으로 쓰는 기능이므로 느리면 안 된다. 1차 구현은 정확한 품질보다도 "쓸 수 있는 응답 속도"를 강하게 의식한다.

설계 기준:

- 단순 주문 조회/취소 준비는 가능하면 2~3초 안에 응답하는 것을 목표로 한다.
- 일반 agent 응답은 5초 이내를 목표로 한다.
- OpenAI 호출 timeout은 짧게 둔다.
- 한 요청에서 tool 호출 수를 제한한다.
- multi-agent handoff는 1차에 쓰지 않는다.
- 전체 상품 정보를 prompt에 넣지 않는다.
- 상품 후보는 DB/tool에서 제한된 개수만 가져온다.
- 확인 API는 OpenAI를 호출하지 않는다.

속도가 부족하면 우선순위는 다음과 같다.

1. tool 호출 수 줄이기
2. DB query/index 확인
3. 후보 개수 제한
4. 모델 변경
5. streaming 도입
6. RAG/vector/cache 고도화

## 구현 전에 필요한 env

현재 구현과 테스트에 반드시 필요한 값은 하나다.

```env
OPENAI_API_KEY=sk-...
```

모델은 현재 `.env.example`에 있는 `OPENAI_MODEL`을 우선 사용한다.

```env
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
```

처음부터 env를 많이 늘리지 않는다. agent 전용 모델 분리가 필요해지면 그때 아래 값을 추가한다.

```env
OPENAI_AGENT_MODEL=gpt-5.4-mini-2026-03-17
```

처음 구현에서는 timeout, tool 호출 제한, 확인 만료 시간은 코드의 기본값으로 둔다. 운영 중 자주 바꿔야 하는 값으로 확인되면 그때 env로 승격한다.

## 구현 순서

1. 결정 기록 문서화
2. agent request/response schema 작성
3. `agent_tool_calls` 모델과 migration 작성
4. tool policy와 allowlist 작성
5. 주문 조회 tool 작성
6. 주문 취소 확인 대기 tool 작성
7. confirm API 작성
8. 상품 유사/비교 tool 작성
9. `/api/agent/chat` 연결
10. 최소 테스트 작성
11. 프론트 전달용 API 계약 정리

## 프론트 협업 메모

프론트가 맞춰야 할 부분:

- 채팅 요청마다 현재 화면 context를 보낸다.
- `ui_action`을 해석해서 화면 이동/모달/상품 목록 표시를 한다.
- 쓰기 작업은 confirm API 호출 전 사용자에게 명확히 보여준다.
- 프론트가 보내는 가격/재고/주문 상태는 표시용 힌트일 뿐이다.

백엔드가 보장해야 할 부분:

- 인증/소유권/상태 검증은 서버에서 다시 한다.
- 주문 취소, 재고 복원, 결제 상태 변경은 기존 transaction 정책을 따른다.
- 실패 응답은 프론트가 안내하기 쉬운 `error_code`를 포함한다.
