# Router/Specialist v1 실측 인사이트

> 기준 실행: `router-specialist-v1-full-post-implementation-r5`
>
> 실행일: 2026-07-23, 로컬 `/api/agent/chat`, 실제 OpenAI API
>
> 범위: 30개 시나리오 × 3개 profile × 5회 = 450개 샘플
>
> 안전 경계: 주문·일괄 찜은 confirmation 이전 preview 계약만 검증했으며 실제 쓰기 동작은 실행하지 않았다.

## 한 줄 결론

`router-nano`는 단일 `gpt-5.5`보다 추천 경로의 p95를 절반가량 줄이고 비용을 크게 낮추면서, 자동 계약 검증을 100% 통과한 가장 균형 잡힌 후보였다.

다만 이는 “LLM을 두 번 호출하면 항상 더 빠르다”는 뜻이 아니다. 첫 호출에서 경로만 고르고, 두 번째 호출에는 해당 경로의 짧은 지시문과 필요한 도구만 전달해 전체 입력 크기와 도구 선택 난도를 낮춘 결과다.

## 측정 조건과 비교 대상

| 항목 | 내용 |
| --- | --- |
| 공통 시나리오 | 기존 추천·시연 Agent 경로 17개 |
| 확장 회귀 시나리오 | 자연어 주소 5개, 복합 일괄 찜 8개 |
| 반복 | profile별 각 5회 |
| 비교 profile | 기존 단일 `gpt-5.5`, 기존 단일 nano, 현행 `single-gpt55`, `router-nano`, `router-nano-fallback` |
| 자동 검증 | HTTP, route, tool, 필수 인자, 제약, confirmation/safety 계약 |
| 수동 검토 | 추천 적합도와 자연스러운 응답 품질 |

원본 실행 결과는 로컬의 [comparison-report.md](results/router-specialist-v1-full-post-implementation-r5/comparison-report.md)와 [report.md](results/router-specialist-v1-full-post-implementation-r5/report.md)에 남아 있다. 결과 디렉터리는 Git ignore 대상이다.

## 검증된 사실

### 1. Router/Specialist는 단일 `gpt-5.5`의 핵심 병목을 줄였다

17개 공통 시나리오에서 `router-nano`는 기존 단일 `gpt-5.5`보다 p95와 추정 비용을 모두 낮췄다.

| 지표 | 이전 단일 `gpt-5.5` | `router-nano` | 변화 |
| --- | ---: | ---: | ---: |
| HTTP 성공 | 84/85 (98.8%) | 85/85 (100.0%) | +1건 |
| 구조 계약 통과 | 94.0% | 100.0% | +6.0%p |
| p50 | 5.49s | 3.36s | -38.8% |
| p95 | 8.70s | 4.86s | -44.1% |
| 평균 입력 토큰 | 2,214 | 1,102 | -50.2% |
| 추정 비용 | $0.941104 | $0.028471 | -97.0% |

동일한 현행 환경의 `single-gpt55` 대조군과 비교해도 p95는 `9.37s -> 4.86s`로 `48.1%` 감소했다.

### 2. 추천 경로에서는 개선 폭이 더 뚜렷했다

추천 시나리오 12개만 분리하면 `router-nano`는 현행 단일 `gpt-5.5` 대비 p95를 `9.91s -> 4.86s`로 `5.04s` 줄였다.

| 지표 | 현행 `single-gpt55` | `router-nano` | 변화 |
| --- | ---: | ---: | ---: |
| HTTP 성공 | 60/60 | 60/60 | 동일 |
| 구조·도구 계약 통과 | 91.7% | 100.0% | +8.3%p |
| p95 | 9.91s | 4.86s | -50.9% |
| 평균 입력 토큰 | 2,260 | 1,152 | -49.0% |
| 추정 비용 | $0.700546 | $0.023965 | -96.6% |

### 3. 단일 nano는 더 빠르지만, 현재 계약 품질을 만족하지 못했다

기존 단일 nano는 p95 `3.61s`로 `router-nano`의 `4.86s`보다 빨랐다. 그러나 구조 계약 통과율은 `60.0%`에 그쳤다.

| 지표 | 이전 단일 nano | `router-nano` | 판단 |
| --- | ---: | ---: | --- |
| p95 | 3.61s | 4.86s | 단일 nano가 34.8% 빠름 |
| 구조 계약 통과 | 60.0% | 100.0% | Router/Specialist가 안정적 |
| 추정 비용 | $0.037141 | $0.028471 | Router/Specialist가 23.3% 낮음 |

따라서 현재 선택은 “가장 짧은 응답시간”이 아니라, 계약 신뢰도와 비용을 함께 만족하는 경로를 택한 것이다.

### 4. 코드 fast path는 LLM 호출 자체를 없앨 수 있다

자연어 주소 5개 케이스는 코드 fast path로 처리됐다.

| 지표 | `router-nano` 결과 |
| --- | ---: |
| 샘플 수 | 25개 |
| p95 | 57.52ms |
| Provider model call | 0 |
| 추정 비용 | $0 |
| 계약 통과 | 100% |

명확한 형식 입력은 LLM에 맡기지 않고 코드로 처리할수록 속도와 결정성이 함께 좋아진다는 근거다.

### 5. 남은 지연의 중심은 Specialist가 필요한 복합 요청이다

`router-nano` 전체 150개 샘플의 단계 계측은 아래와 같다.

| 단계 | p50 | p95 | 의미 |
| --- | ---: | ---: | --- |
| 전체 HTTP | 3.40s | 6.58s | 사용자 체감 시간 |
| Router | 0.87s | 1.46s | 작업 경로 선택 |
| Specialist | 2.79s | 5.71s | 도구 선택·인자 생성·응답 구성 |

복합 일괄 찜은 `router-nano`에서 p95 `7.60s`로 가장 느린 신규 경로였다. 모델이 필요한 35개 샘플은 Router와 Specialist를 모두 호출했다.

## 왜 이 구조가 유리했는가

### 문제였던 구조

기존 단일 Agent는 서로 성격이 다른 추천, 상세 상품, 장바구니, 주문, 주소, 일괄 찜 흐름을 한 긴 지시문과 여러 도구 schema 안에서 동시에 판단했다. 빠른 nano 모델은 이 넓은 선택 공간에서 기대 route/tool 계약을 자주 놓쳤다.

### 바꾼 구조

1. 코드 fast path가 형식이 명확하고 안전한 요청을 먼저 처리한다.
2. Router nano가 남은 요청을 작업 route로만 분류한다.
3. Specialist nano가 선택된 route의 전용 지시문과 제한된 도구만 받아 실제 인자와 preview 응답을 만든다.
4. 선택적으로 fallback 모델을 최대 1회 재시도할 수 있다.

이 구조의 핵심은 모델 자체를 크게 바꾼 것이 아니라, **한 모델이 한 번에 읽고 판단해야 하는 지시문·도구·행동 범위를 줄인 것**이다.

## 해석과 의사결정

### 채택할 방향

- `router-nano`를 다음 단계의 기본 후보로 유지한다.
- `single` 경로는 rollback과 비교 기준을 위해 feature flag로 보존한다.
- 명확한 주소·제한된 일괄 작업처럼 코드로 결정 가능한 요청은 fast path를 계속 우선한다.

### 받아들인 트레이드오프

- Router/Specialist는 두 번의 LLM 호출 때문에 단일 nano보다 절대 최저 지연은 높다.
- 대신 단일 nano의 낮은 계약 통과율을 100%까지 올리고, 입력 토큰과 추정 비용은 더 낮췄다.
- 따라서 이 설계는 저지연만이 아니라 **도구 호출 안정성, 비용, 확장성**을 함께 최적화한 선택이다.

## 아직 증명되지 않은 것

### Fallback 복구 효과

`router-nano-fallback`은 정상 경로에서 150/150을 통과했지만 fallback이 실제로 한 번도 발동하지 않았다. 이 평가는 fallback의 평상시 오버헤드가 크지 않다는 점만 보여 준다. 모델 timeout, provider 오류, 잘못된 structured output을 의도적으로 주입한 강제 실패 테스트가 있어야 복구 효용을 증명할 수 있다.

### 추천 품질과 자연스러운 응답

자동 계약 검증의 100%는 route/tool/인자/safety 계약을 뜻한다. 상품 적합도, 문장 자연스러움, 사용자 기대 충족은 별도 수동 평가가 필요하다. 추천·시연 경로의 검토 대상은 [manual-review.csv](results/router-specialist-v1-full-post-implementation-r5/manual-review.csv)에 남아 있다.

### 비용 수치의 성격

`estimated_cost_usd`는 backend trace의 로컬 token 단가표를 이용한 추정치다. OpenAI 청구서의 최종 금액과는 소폭 차이날 수 있으므로 비용 정책은 Usage 데이터와 함께 최종 확인해야 한다.

## 다음 검증 순서

1. `manual-review.csv`를 기준으로 추천·시연 85개 샘플/profile의 의미 품질을 표본 검토한다.
2. Router timeout, Specialist 오류, 구조화 출력 오류를 강제해 fallback 1회 재시도의 성공률과 지연을 측정한다.
3. p95 `7.60s`인 복합 일괄 찜을 우선 분석해 Specialist 입력, 도구 schema, 코드 fast path 확대 가능성을 점검한다.
4. 품질과 fallback 검증을 통과한 뒤에만 `router_specialist`를 운영 기본값으로 전환한다.

## 재현 명령

~~~powershell
$env:AGENT_EVAL_USER_EMAIL = "test-user@example.com"
$env:AGENT_EVAL_USER_PASSWORD = "..."

python scripts/agent/evaluate_agent_models.py `
  --cases docs/agent-evals/fixtures/router-specialist-v1.json `
  --profiles single-gpt55 router-nano router-nano-fallback `
  --repeat 5 `
  --run-id router-specialist-v1-full-post-implementation-r5 `
  --allow-write-previews
~~~

실행기는 실제 OpenAI API를 호출한다. 주문과 일괄 찜은 confirmation 이전 preview만 생성하지만, 비용은 발생한다.
