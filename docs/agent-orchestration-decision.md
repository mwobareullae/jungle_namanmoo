# AI Agent 오케스트레이션 결정 기록

> 상태: **제안 단계**. 이 문서는 다음 Agent 구조의 선택 근거와 검증 계획을 기록한다.
> 2단계 구조가 구현되었거나 더 빠르다는 뜻은 아니다.

## 1. 결정 요약

현재 커머스 Agent는 OpenAI Agents SDK `Agent` 하나가 현재 화면에서 허용된
도구를 선택하고, 백엔드 도구가 만든 UI payload를 그대로 반환하는 구조다.

다음 단계에서는 **코드 오케스트레이션 기반의 2단계 구조**를 평가한다.

1. 작은 Router Agent가 요청 작업 종류만 분류한다.
2. 백엔드 코드가 분류 결과를 검증하고 작업 전용 Specialist Agent를 선택한다.
3. Specialist Agent는 짧은 지시문과 관련 도구만 받고, 최대 하나의 도구를 호출한다.
4. 기존 dispatcher, 권한 정책, 확인 절차, 도메인 서비스 검증은 계속 백엔드가 담당한다.

첫 구현은 OpenAI Agents SDK의 **Structured Output**과 `function_tool`을 사용한다.
이번 범위에서는 Agent 간 Handoff, Manager Agent, 별도 오케스트레이션 프레임워크는
도입하지 않는다.

## 2. 문제 맥락

하나의 떠 있는 Agent 입력창은 추천, 상품 탐색, 장바구니·찜, 주문·결제 준비,
리뷰·클레임을 모두 처리한다. 기능적으로는 유용하지만 단일 Agent가 매 요청마다
모든 경로의 공통 지시문과 현재 페이지에서 허용되는 도구 스키마를 함께 읽는다.

추천 요청의 로컬 trace에서 관찰한 입력 규모는 다음과 같다.

| 입력 항목 | 관찰 크기 |
| --- | ---: |
| 공통 Agent 지시문 | 6,581 B |
| 선택된 도구 스키마 | 5,073 B |
| 사용자·화면 문맥 JSON | 340 B |
| 실제 모델 입력 | 2,546 tokens |

문제는 사용자의 한 문장이 길어서가 아니다. 단순한 요청도 관계없는 경로의 설명과
도구 스키마를 읽은 뒤에 도구를 선택해야 한다는 점이다. 특히 작은 모델은 이러한
도구 선택의 모호성에 더 민감할 수 있다.

## 3. 목표

- 요청별 불필요한 프롬프트와 도구 스키마 입력을 줄인다.
- 모델이 ID, 가격, 재고, 결제 결과, 주문 권한을 만들어 내지 못하도록 기존 안전 경계를 유지한다.
- 좁고 정형화된 커머스 요청에 빠른 모델을 평가할 수 있게 만든다.
- 지연 시간, 토큰, 모델 비용, 경로 정확도, 도구 선택, 최종 실행 성공률을 측정한다.
- 단일 Agent 경로를 평가 기간의 명시적 fallback으로 남겨 되돌릴 수 있게 한다.

## 4. 범위 제외

- 추천·점수화 엔진을 LLM으로 바꾸는 일
- Agent에 직접 SQL, 결제, 재고, 주문 쓰기 권한을 주는 일
- 일괄 찜, 장바구니 구성, 취소, 주문 생성의 기존 확인 정책 변경
- 장기 자율 계획이나 여러 Agent가 이어서 대화하는 구조
- 측정 전에 지연 시간 또는 비용이 개선됐다고 주장하는 일

## 5. 현재 이미 활용하는 Agents SDK 기능

현재 구조는 커머스 tool workflow에 필요한 SDK 기반을 이미 갖고 있다.

| SDK/백엔드 기능 | 현재 역할 | 다음 구조에서도 유지 |
| --- | --- | --- |
| `Agent`, `Runner.run` | 하나의 커머스 Agent 실행 | 유지 |
| `function_tool` | 타입이 있는 백엔드 도구 노출 | 유지 |
| `RunContext` | DB 세션, 사용자, 요청 문맥을 도구에 전달 | 유지 |
| `tool_choice="auto"`, `stop_on_first_tool` | 한 턴에 하나의 도구 선택 | 유지 |
| SDK `trace` | 모델·도구 workflow 추적 | 단계별 계측으로 확장 |
| backend policy/dispatcher | 인자·권한·확인 절차 재검증 | 계속 최종 권한 보유 |

다음 단계에서 가장 가치가 큰 SDK 기능은 **경로 분류용 Structured Output**이다.
Router는 대화 문장이 아니라 제한된 Pydantic 모델을 반환해야 한다.

## 6. 제안 구조

```text
요청
  |
  +-- 결정론적 빠른 경로
  |     - 주소 형식 파싱
  |     - 단순 추천 결과 조건 필터
  |     - 정형화된 일괄 찜 요청
  |
  +-- Router Agent: 짧은 모델 1회, function tool 없음
  |     입력: 사용자 문장 + 최소 화면/경로 문맥
  |     출력: RouteDecision JSON
  |
  +-- 백엔드: 경로·신뢰도·페이지·권한 검증 및 fallback 결정
  |
  +-- Specialist Agent: 짧은 모델 1회, 관련 function tool 1~3개
  |     입력: 사용자 문장 + 작업별로 필터링한 문맥
  |     출력: 도구 1회 호출 또는 짧은 추가 질문
  |
  +-- 기존 dispatcher -> policy -> domain service -> UI payload
```

### 6.1 Router 반환 계약

Router에는 커머스 도구를 주지 않는다. 아래처럼 작고 검증 가능한 결정만 반환한다.

```python
class RouteDecision(BaseModel):
    route: Literal[
        "recommendation",
        "product",
        "cart_commerce",
        "order_checkout",
        "post_purchase",
        "clarify",
    ]
    confidence: Literal["high", "medium", "low"]
```

Router는 상품·성분 ID, 가격, 수량, 주문 결정을 만들지 않는다. 신뢰도가 낮거나 현재
페이지와 맞지 않는 경로는 짧은 추가 질문 또는 기존 단일 Agent fallback으로 처리하며,
검증되지 않은 쓰기 도구를 호출하지 않는다.

### 6.2 Specialist 책임 경계

| 경로 | 주로 노출할 도구 | Specialist 책임 |
| --- | --- | --- |
| `recommendation` | `create_recommendation`, `refine_product_results` | 고민과 명시 조건을 추천 필드로 해석 |
| `product` | `find_similar_products`, `compare_products` | 현재·선택 상품 참조 해석 |
| `cart_commerce` | `get_cart`, `add_to_cart`, `bulk_wishlist_by_popular_ingredient`, `compose_cart` | 상품 참조를 해석하고 장바구니·찜 작업 준비 |
| `order_checkout` | checkout, 주소, 주문 조회·취소 도구 | 제한된 주문·결제 준비 흐름 진행 |
| `post_purchase` | `prepare_review_draft`, `prepare_claim_draft` | 리뷰·클레임 초안만 준비 |
| `clarify` | 없음 | 최소한의 추가 질문 1개 반환 |

페이지 allowlist, 인증 필요 여부, 확인 필요 여부, 항목 제한, 모든 도메인 검증은
백엔드 코드가 계속 강제한다. Specialist Agent는 언어 해석을 좁히는 역할만 하며,
커머스 사실 또는 실행 권한의 출처가 되지 않는다.

## 7. Handoff 대신 코드 오케스트레이션을 선택하는 이유

OpenAI Agents SDK의 다중 Agent 방식은 크게 두 가지다.

- **Handoff**: triage Agent가 대화의 제어권을 다른 Agent에게 넘긴다.
- **코드 오케스트레이션**: 애플리케이션 코드가 다음 Specialist를 선택하고 제어권을 유지한다.

Handoff는 전문 Agent가 긴 대화를 이어서 맡아야 할 때 유리하다. 현재 커머스 Agent는
대부분 하나의 검증된 tool call이 필요하고, 백엔드가 확인·권한·UI payload를 통제한다.
따라서 코드가 다음 Agent를 선택하는 편이 경로 fallback, 페이지 호환성 확인, 모델 선택,
성능 계측을 결정론적으로 관리하기 쉽다.

Handoff도 Router 추론과 Specialist 추론을 모두 필요로 하므로, 2단계의 지연 위험을
없애 주지는 않는다.

- [OpenAI Agents SDK: multi-agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [OpenAI Agents SDK: handoffs](https://openai.github.io/openai-agents-python/handoffs/)

## 8. 시간·비용·정확도 트레이드오프

2단계 모델 호출은 provider 추론을 한 번 더 수행하므로 단일 Agent보다 느리고 비쌀 수
있다. Router와 Specialist의 프롬프트·도구 스키마 축소가 그 추가 비용보다 충분히 큰
토큰, 시간, 오선택 감소를 만들 때만 채택할 가치가 있다.

| 관점 | 기대 효과 | 위험 | 반드시 측정할 값 |
| --- | --- | --- | --- |
| 시간 | Specialist 문맥과 도구 수 축소 | 모델 호출 1회 추가 | 전체 p50/p95, Router/Specialist 단계 시간 |
| 비용 | Specialist별 입력 token 절감 | Router 입출력 token 추가 | 요청별 token, 추정 비용 |
| 정확성 | 좁은 도구 집합으로 선택 모호성 감소 | Router 오분류 | route/tool/인자/실행 성공률 |
| 안전성 | 코드가 도구 노출 전 경로 검증 | fallback 오류 | 권한·확인 회귀 테스트 |
| 운영 | 경로별 trace로 실패 원인 분리 | 설정·평가 경우 증가 | 로그, trace, 고정 평가셋 |

nano Router와 nano Specialist가 단순 경로에서 빠르고 저렴할 가능성은 있지만,
복합 한국어 커머스 요청은 더 강한 Specialist 또는 fallback이 필요할 수 있다.
모델 이름·가격·제한은 구현 시점의 OpenAI 공식 문서로 다시 확인한다.

## 9. 평가 계획

기본 경로를 바꾸기 전에 고정 Agent 평가셋으로 기존 단일 Agent와 2단계 구조를 비교한다.
평가셋에는 추천 고민, 가격·카테고리 필터, 유사 상품, 주문·checkout 이어가기, 일괄 찜,
리뷰·클레임 경로가 포함돼야 한다.

각 문장마다 아래 값을 남긴다.

1. 기대 경로와 실제 경로
2. 기대 도구와 실제 도구
3. Pydantic 인자 검증 결과
4. 도구 실행·확인 정책 결과
5. 전체, Router, Specialist, 도구, 응답 저장 시간
6. 입력·출력 token, 모델명, 추정 비용
7. 최종 UI payload 정확성 및 오류 유형

채택 기준은 구현 전에 합의한다. 최소한 2단계 기본 경로는 고정 평가셋의 tool 실행
성공률과 권한·확인 정책을 떨어뜨리면 안 되며, 의도한 경로에서 반복 가능한 시간 또는
비용 이득을 보여야 한다.

## 10. 관측 계약

기존 Agent trace와 구조화 성능 로그를 대체하지 않고, 경로별 필드를 추가한다.

```text
agent_router_model_ms
agent_router_route
agent_router_confidence
agent_specialist_model_ms
agent_specialist_route
agent_specialist_tool_count
agent_input_tokens
agent_output_tokens
agent_estimated_cost
agent_fallback_reason
```

Redis 전역 workflow lease는 Router와 Specialist를 합친 사용자 요청 전체에 한 번만
획득한다. 두 단계가 각각 slot을 잡으면 하나의 요청을 두 번 세어 동시성 동작을 왜곡한다.

## 11. 구현 순서

1. `RouteDecision` schema와 Structured Output Router를 추가한다.
2. 현재 공통 지시문에서 경로별 지시문·도구 부분집합을 분리한다. 기존 도메인 tool 계약은 바꾸지 않는다.
3. 코드 오케스트레이션, 페이지·권한 호환성 검증, 단일 Agent fallback flag를 추가한다.
4. 단계별 trace, token·비용 로그, 고정 평가셋 테스트를 추가한다.
5. 모델과 경로별 A/B를 수행한 뒤에만 기본 경로를 선택하고, 측정 결과를 README·성능 보고서에 기록한다.

## 12. README용 선택 근거

> AI 커머스 Agent는 작업 분류와 작업 실행을 분리한다. 작은 Structured Router가
> 제한된 Specialist를 선택하고, 백엔드는 모든 도구 인자·권한·확인 절차를 다시 검증한다.
> 이 구조는 빠른 모델을 평가할 수 있을 만큼 문맥을 줄이면서도 커머스 실행의 안전성을
> 코드에 남긴다. 실제 채택은 기존 단일 Agent 대비 지연 시간, token 비용, 경로 정확도,
> 도구 실행 성공률을 측정한 뒤에만 결정한다.
