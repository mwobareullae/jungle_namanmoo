# AI Agent 코드 오케스트레이션 결정 기록

> 상태: 구현 및 로컬 live 평가 완료. 기본 실행 모드는 아직 `single`이며,
> `router_specialist`는 환경변수로 명시적으로 켜는 opt-in 경로다.

## 1. 결정 요약

기존에는 하나의 긴 OpenAI Agent가 화면별 허용 도구와 공통 지시문을 함께 읽고
작업을 선택했다. 현재는 기존 경로를 제거하지 않고 아래 두 실행 모드를 공존시킨다.

| 모드 | 역할 | 기본값 |
| --- | --- | --- |
| `single` | 기존 긴 공통 prompt와 기존 Agent 실행 경로 | 기본 |
| `router_specialist` | Fast Path → Router → 서버 검증 → Specialist | 명시적 opt-in |

~~~text
사용자 요청
  ├─ 결정론적 Fast Path
  │    └─ 서버가 완전히 해석·검증 가능한 요청만 즉시 처리
  └─ Router Agent (tool 없음, route + confidence만 Structured Output)
       └─ 서버 코드: page/auth/context/허용 tool 검증
            └─ Specialist Agent (새 prompt + 실제 선택 tool 1~2개)
                 └─ 기존 Dispatcher / Policy / Domain Service
                      └─ UI payload
~~~

Router가 추론한 결과는 실행 권한이 아니다. 도구 인자, 인증, 권한, confirmation,
도메인 검증은 기존처럼 서버가 최종 판단한다.

## 2. 왜 구조를 바꿨는가

단일 Agent의 로컬 trace에서 단순 요청에도 다음 입력이 매번 함께 전달됐다.

| 입력 항목 | 관찰 크기 |
| --- | ---: |
| 공통 Agent 지시문 | 6,581 B |
| 선택된 도구 스키마 | 5,073 B |
| 사용자·화면 문맥 JSON | 340 B |
| 실제 모델 입력 | 2,546 tokens |

사용자 문장 자체보다 관계없는 업무 규칙과 도구 선택지가 모델 입력을 크게 만들었다.
작업 분류와 작업 실행을 분리해, 각 모델이 판단해야 하는 범위를 작게 만들었다.

## 3. prompt, context, tool 분리

기존 `AGENT_INSTRUCTIONS`를 축약해 재사용하지 않았다. `single` 호환 모드에서만
기존 prompt를 유지하고, `router_specialist`는 처음부터 새 prompt profile을 사용한다.

| 이전 공통 규칙 | 새 위치 | 이유 |
| --- | --- | --- |
| 요청 종류 판단 | Router prompt | route만 결정 |
| 추천·상품·주문별 자연어 해석 | route별 Specialist prompt | 해당 경로에만 전달 |
| 인증·권한·confirmation·도메인 검증 | Dispatcher / Policy / Domain Service | LLM이 실행 권한을 갖지 않음 |
| 완전히 정형화된 안전 요청 | Fast Path | 모델 호출 없이 빠르게 처리 |

Router에는 사용자 메시지, 현재 page/route, 로그인 여부와 참조 가능 여부의 boolean만
전달한다. 상품·성분·주문·배송지 ID, 전체 도구 schema, 전체 상품 payload, 다른 route의
업무 규칙은 Router 입력에서 제외한다.

Specialist는 아래 7개 route 중 하나의 신규 지시문만 받고, 서버가 현재 메시지와
페이지 allowlist를 보고 다시 좁힌 실제 도구만 받는다.

| route | 책임 | 실제 노출 범위 |
| --- | --- | --- |
| `recommendation` | 피부 고민·성분·가격 조건 해석 | `create_recommendation` |
| `recommendation_refinement` | 현재 결과 필터 | `refine_product_results` |
| `product_reference` | 유사·비교·현재 상품 행동 | 메시지에 맞는 1개 |
| `cart_checkout` | 장바구니·주소·checkout 준비 | 메시지에 맞는 1~2개 |
| `order_after_sales` | 주문 조회·취소·리뷰·클레임 | 메시지에 맞는 1개 |
| `bulk_wishlist` | 인기 순위 조건 일괄 찜 미리보기 | `bulk_wishlist_by_popular_ingredient` |
| `clarification` | 진짜 모호한 요청의 추가 질문 | tool 없음 |

## 4. 설정과 fallback

~~~env
OPENAI_AGENT_EXECUTION_MODE=single
OPENAI_AGENT_ROUTER_MODEL=gpt-5.4-nano-2026-03-17
OPENAI_AGENT_SPECIALIST_MODEL=gpt-5.4-nano-2026-03-17
OPENAI_AGENT_SPECIALIST_FALLBACK_ENABLED=false
OPENAI_AGENT_SPECIALIST_FALLBACK_MODEL=gpt-5.5
~~~

fallback은 기본적으로 꺼져 있다. 켠 경우에도 Router나 legacy single Agent로 되돌아가지
않고, 같은 route·같은 prompt·같은 최소 context·같은 tool subset의 Specialist를
최대 한 번만 다시 호출한다. Router, Specialist, fallback은 하나의 Redis global lease,
로컬 queue slot, 전체 deadline을 공유한다.

Router가 `clarification`을 선택했거나, Fast Path가 처리했거나, 서버 policy가
authentication/validation/confirmation 응답을 반환했거나, deadline이 부족하면 fallback을
허용하지 않는다.

## 5. Fast Path와 확장한 계약

Fast Path는 모델 호출을 줄이기 위한 일반 자연어 regex 엔진이 아니다. 서버가 해석과
안전성을 모두 보장할 수 있는 경로만 Router보다 먼저 처리한다. 넓은 일괄 찜 또는
multi-action 정규식으로 자연어 조건을 잘라내지 않고, 복합 요청은 Specialist가 구조화한
뒤 서버가 검증한다.

### 배송지 자연어 입력

cart/checkout 경로는 라벨 유무와 입력 순서에 관계없이 수령인, 연락처, 우편번호, 기본 주소,
상세 주소, 요청사항을 구조화할 수 있다. 서버는 전화번호·우편번호·필수 필드를 최종 검증하며,
빠진 필드만 추가로 요청한다. Agent는 주소나 우편번호를 추측하지 않는다.

### 복합 일괄 찜

일괄 찜 계약은 인기 순위 1~50, 단일·복수 성분, `all`/`any`, 카테고리,
최소·최대 가격을 표현한다. 요청 rank가 50을 넘으면 자동 절삭하지 않고 명시적으로
거절한다. preview와 confirmation 정책은 기존 서버 정책을 유지하며, 실제 쓰기는
confirmation 이후에만 가능하다.

## 6. 왜 Handoff/LangGraph가 아닌 코드 오케스트레이션인가

Handoff와 LangGraph는 긴 대화 상태를 여러 Agent가 이어받거나, 복잡한 graph 상태 전이가
필요할 때 유용하다. 이 서비스의 한 요청은 대부분 하나의 검증된 tool call로 끝나고,
페이지·권한·confirmation·UI payload의 제어권이 서버에 있어야 한다.

따라서 애플리케이션 코드가 다음 Specialist를 고르면 다음 장점이 있다.

- Router 결과를 page/auth/context와 결정론적으로 대조할 수 있다.
- Specialist에 전달하는 tool scope를 서버가 강제한다.
- fallback, timeout, Redis lease, 비용·시간 계측을 한 workflow로 관리할 수 있다.
- Handoff가 추가하는 대화 제어권 이전 없이 기존 Dispatcher/Policy 계약을 유지한다.

OpenAI Agents SDK의 `Agent`, `Runner`, Structured Output, `function_tool`은
그대로 사용한다. 별도 multi-agent framework는 도입하지 않았다.

## 7. 관측과 개인정보 경계

기존 aggregate Agent timing metric을 유지하면서 아래 단계별 값도 구조화 로그와
local trace에 남긴다.

~~~text
agent_execution_mode
agent_fast_path_name
agent_router_model / agent_router_ms / agent_router_route / agent_router_confidence
agent_specialist_name / agent_specialist_model / agent_specialist_tool_count
agent_fallback_enabled / agent_fallback_used / agent_fallback_reason / agent_fallback_ms
agent_tool_validation_failed / agent_tool_execution_ms / agent_final_response_ms
각 단계의 input/output token, estimated cost, input bytes, tool schema bytes
~~~

원문 prompt, 요청, 응답, tool argument는 명시적으로 켠 local trace에만 남긴다.
일반 application log와 OpenAI metadata에는 새 원문 개인정보를 추가하지 않는다.
raw local trace와 `docs/agent-evals/results/`는 Git에 커밋하지 않는다.

## 8. 실제 local live 평가 결과

평가는 localhost backend와 실제 OpenAI API를 사용했다. 주문·찜은 preview까지만
생성했고, confirmation endpoint와 실제 결제·주문·취소는 호출하지 않았다.

### 비교 기준

기존 기준선은 17개 scenario, 모델별 5회 반복으로 수집했다.

| 모델 | 추천 HTTP 성공 | 추천 구조 검증 | 추천 p95 |
| --- | ---: | ---: | ---: |
| `gpt-5.5` single | 59/60 | 91.5% | 9.31초 |
| `gpt-5.4-nano-2026-03-17` single | 60/60 | 43.3% | 3.68초 |

Nano 단일 Agent는 빠르지만 일반 피부 고민에서 tool 호출 대신 clarification을 내는 문제가
확인됐다. 이것이 Router/Specialist 평가를 추가한 이유다.

### 최종 A/B/C 비교

`router-specialist-v1-full-final-r4`은 base 17개 + 주소 5개 + 복합 일괄 찜 8개,
총 30개 fixture에 A/B/C profile을 각각 4회 실행한 결과다.

| profile | 추천 HTTP 성공 | 추천 구조 검증 | 추천 p95 | 추천 그룹 추정 비용 |
| --- | ---: | ---: | ---: | ---: |
| single + `gpt-5.5` | 48/48 | 91.7% | 10.40초 | $0.582338 |
| Router nano + Specialist nano | 48/48 | 97.9% | 4.95초 | $0.018811 |
| Router nano + Specialist nano + fallback on | 48/48 | 100.0% | 5.68초 | $0.019006 |

- 완료 sample: 360개, provider model call: 444회
- 전체 응답 p50/p95: 3,727.42 / 7,232.49ms
- Router p50/p95: 780.25 / 1,249.30ms
- Specialist p50/p95: 2,326.66 / 5,440.85ms
- 전체 route/tool/safety 검증: 100.0% / 98.9% / 100.0%
- 주소 Fast Path: 20/20 HTTP 성공, provider 호출 0회

최종 run의 7건 strict validation 실패는 숨기지 않았다. 단일 gpt-5.5의 일반 고민 tool
미호출 4건, Router nano의 성분명 variant 1건, 단일 성분 `any`/`all` 표현 차이 2건이다.
후자의 두 계약 원인은 서버 정규화와 Specialist 지시문으로 수정했다.

수정 후 `router-specialist-v1-contract-retest-r6`에서 해당 추천·일괄 찜 fixture를
Router nano와 fallback-on profile로 각각 6회 실행했다.

| 범위 | sample | provider 호출 | route/tool/safety |
| --- | ---: | ---: | ---: |
| 성분명 보존 + 단일 성분 계약 재검증 | 24 | 48 | 100.0% / 100.0% / 100.0% |

Router/Specialist 구현 검증을 위해 생성한 router-specialist-v1 run만 합산하면
826 sample, provider model call 1,023회, 로컬 토큰 단가 기준 추정 비용 $2.143182이다.
목표로 잡았던 약 1,000회 수준의 live 검증 범위 안에서 반복 평가했다. 기존 single-Agent
기준선 run까지 함께 합치면 1,030 sample, 1,215 provider call, $3.358460이지만,
그 기준선은 구조 구현 전의 비교 데이터이므로 구현 검증 호출 수와 구분한다.
추정 비용은 OpenAI Usage의 실제 청구액과 완전히 같다고 주장하지 않는다.

## 9. 해석과 한계

- Router/Specialist가 모든 경로에서 더 빠르거나 더 싸다고 일반화하지 않는다.
  위 수치는 로컬 backend, 고정 fixture, 순차 실행의 관찰값이다.
- fallback-on 비교에서 실제 fallback은 0회였다. 불필요한 fallback이 없었다는 점은
  확인했지만, provider 오류 상황에서 fallback 성공률을 live로 입증한 것은 아니다.
  그 경로는 단위 테스트로 같은 Specialist scope·최대 1회 재시도를 검증한다.
- 추천 결과의 제품 적합성은 `manual-review.csv`를 통한 사람 검토 대상이다.
  구조적 tool/argument 성공이 추천 품질의 완전한 보증은 아니다.
- 기본 배포 모드는 여전히 `single`이다. 실제 운영 채택은 프로덕션 데이터와
  사용자 요청 분포에서 별도 비교한 뒤 결정한다.

## 10. 재현과 참고

- 고정 fixture: `docs/agent-evals/fixtures/router-specialist-v1.json`
- 실행기: `scripts/agent/evaluate_agent_models.py`
- 실행 방법과 결과 해석: `docs/agent-evals/README.md`
- raw 결과와 trace는 local only이며 Git에 포함하지 않는다.
