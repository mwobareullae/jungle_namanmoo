# Agent 모델·오케스트레이션 평가

이 디렉터리의 고정 fixture와 실행기는 기존 단일 Agent와 코드 기반
Router/Specialist 경로를 실제 OpenAI API로 비교한다. 결과의 목적은 모델 또는
구조의 우열을 추정으로 선언하는 것이 아니라, 같은 문장·문맥·안전 정책에서
시간, 비용, route, tool, argument를 재현 가능하게 관찰하는 것이다.

## 평가 대상

| profile | 실행 모드 | Router | Specialist | fallback |
| --- | --- | --- | --- | --- |
| single-gpt55 | single | 없음 | gpt-5.5 단일 Agent | 없음 |
| router-nano | router_specialist | nano | nano | off |
| router-nano-fallback | router_specialist | nano | nano | on, gpt-5.5 최대 1회 |

Router와 Specialist nano 모델은 gpt-5.4-nano-2026-03-17을 사용한다.

## Fixture

router-specialist-v1.json은 기존 single-agent-baseline-v1.json의 17개
scenario를 확장한다.

| 묶음 | 수 | 검증 내용 |
| --- | ---: | --- |
| 기존 추천·시연 Agent 경로 | 17 | 피부 고민, 결과 필터, 유사 상품, 주문 preview, 일괄 찜 preview |
| 자연어 주소 | 5 | 라벨, 순서 변경, 무라벨, 누락 필드, 잘못된 우편번호 |
| 복합 일괄 찜 | 8 | rank 1~50, 성분 all/any, 카테고리, 가격, 결과 0건, rank 51 거절 |
| 합계 | 30 | route, tool, 필수 인자, safety/confirmation |

각 fixture에는 scenario ID와 사용자 문장, page/context/auth 사전조건, 기대
route/tool, 필수 argument, clarification 허용 여부, preview/write 성격,
결과 검증 방식을 명시한다.

## 사전 조건

로컬 backend와 실제 OpenAI API key가 있는 개발 환경에서만 실행한다. credential은
환경변수로만 전달하며, 문서·결과·Git에 기록하지 않는다.

~~~powershell
$env:AGENT_EVAL_USER_EMAIL = "test-user@example.com"
$env:AGENT_EVAL_USER_PASSWORD = "..."
~~~

주문과 일괄 찜은 항상 preview만 생성한다. confirmation endpoint, 실제 결제,
실제 주문, 실제 취소는 실행기가 호출하지 않는다.

## 실행

### 외부 API 없이 계획 확인

~~~powershell
python scripts/agent/evaluate_agent_models.py --cases docs/agent-evals/fixtures/router-specialist-v1.json --profiles single-gpt55 router-nano router-nano-fallback --repeat 1 --dry-run
~~~

### A/B/C live 비교

~~~powershell
python scripts/agent/evaluate_agent_models.py --cases docs/agent-evals/fixtures/router-specialist-v1.json --profiles single-gpt55 router-nano router-nano-fallback --repeat 4 --run-id router-specialist-v1-live-YYYYMMDD --allow-write-previews
~~~

### 실패 fixture 집중 재검증

~~~powershell
python scripts/agent/evaluate_agent_models.py --cases docs/agent-evals/fixtures/router-specialist-v1.json --profiles router-nano router-nano-fallback --only ingredient-price-01 bulk-wishlist-empty-price-window --repeat 6 --run-id router-specialist-v1-contract-retest-YYYYMMDD --allow-write-previews
~~~

중단된 run은 같은 run-id에 resume을 붙여 이어갈 수 있다. 실패 sample만
다시 실행하려면 retry-failed를 함께 사용한다.

~~~powershell
python scripts/agent/evaluate_agent_models.py --cases docs/agent-evals/fixtures/router-specialist-v1.json --profiles router-nano router-nano-fallback --repeat 6 --run-id router-specialist-v1-contract-retest-YYYYMMDD --allow-write-previews --resume --retry-failed
~~~

## 산출물과 검증 의미

결과는 docs/agent-evals/results/<run-id>/에 생성되며 Git ignore 대상이다.

| 파일 | 용도 |
| --- | --- |
| manifest.json | fixture hash, profile, 반복 수, 안전 설정, health/bootstrap 결과 |
| samples.jsonl | 재개 가능한 sample 원장 |
| scenario-results.csv | sample별 HTTP, route, tool, 인자, 단계 시간, token, 비용 |
| model-summary.csv | profile/group별 p50/p95와 검증률 |
| manual-review.csv | 구조 검증만으로 판단할 수 없는 추천 품질 검토 표 |
| report.md | run 요약, 실패 sample, stage timing |

passed는 구조 및 제약 검증을 통과했음을 뜻한다. failed는 기대 route/tool,
필수 인자 또는 safety/confirmation 계약 중 하나가 실패했음을 뜻한다.
needs_manual_review는 구조는 통과했지만 추천 품질·자연어 해석의 적합성은 사람이
검토해야 함을 뜻한다. HTTP 200만으로 품질 성공을 선언하지 않는다.

주요 CSV 필드:

- provider_model_call_count: Router/Specialist/fallback의 실제 provider 호출 합
- route_pass, tool_pass, structural_pass, constraint_pass, safety_pass
- router_ms, specialist_ms, fallback_ms, tool_execution_ms
- input_tokens, output_tokens, estimated_cost_usd
- instructions_bytes, selected_tool_count, selected_tool_schema_bytes

estimated_cost_usd는 로컬 token 단가표를 사용한 추정치다. OpenAI Usage의 실제
청구 총액과 다를 수 있다.

## 실제 실행 기록

### 기존 단일 Agent 기준선

single-agent-baseline-v1-full-before-router는 기존 17개 fixture를 모델별 5회
실행한 기준선이다.

| 모델 | 추천 HTTP 성공 | 추천 구조 검증 | 추천 p95 |
| --- | ---: | ---: | ---: |
| gpt-5.5 | 59/60 | 91.5% | 9.31초 |
| gpt-5.4-nano-2026-03-17 | 60/60 | 43.3% | 3.68초 |

### 30-case A/B/C 비교

router-specialist-v1-full-final-r4는 30개 fixture × 3 profile × 4회로
360 sample, 444 provider model call을 수집했다.

| profile | 추천 HTTP 성공 | 추천 구조 검증 | 추천 p95 | 추천 그룹 추정 비용 |
| --- | ---: | ---: | ---: | ---: |
| single-gpt55 | 48/48 | 91.7% | 10.40초 | $0.582338 |
| router-nano | 48/48 | 97.9% | 4.95초 | $0.018811 |
| router-nano-fallback | 48/48 | 100.0% | 5.68초 | $0.019006 |

해당 run의 전체 응답 p50/p95는 3,727.42/7,232.49ms, Router p50/p95는
780.25/1,249.30ms, Specialist p50/p95는 2,326.66/5,440.85ms였다.
route/tool/safety 통과율은 100.0%/98.9%/100.0%였다.

이 run의 strict 실패 7건은 raw 결과에 남겼다.

- 단일 gpt-5.5 일반 고민 4건: 예상 create_recommendation tool 미호출
- Router nano 1건: 나이아신아마이드 성분명을 variant로 바꿔 결과 0건
- 단일 성분 2건: 의미상 동등한 any를 보내 strict all 계약에 불일치

성분 원문 보존 지시문과 단일 성분 모드 서버 정규화 후,
router-specialist-v1-contract-retest-r6에서 두 fixture × 두 profile × 6회,
총 24 sample을 재실행했다. 실패는 0건이며 route/tool/safety는 모두 100.0%였다.

Router/Specialist 구현 검증 run만 합산하면 826 sample, provider model call 1,023회,
로컬 추정 비용 $2.143182이다. 기존 single-Agent 기준선 run까지 함께 합치면
1,030 sample, 1,215 provider call, $3.358460이다. 전자는 구조 구현 검증 호출 수이고,
후자는 저장된 비교 결과 전체이므로 서로 구분한다. 이 수치는 trace 또는 credential을
복사하지 않고 CSV 집계에서 계산했다.

## 안전·개인정보

- raw request/response, tool argument, 테스트 계정 문맥은
  apps/backend/.local/agent-traces/에만 남긴다.
- raw trace는 docs/agent-evals/results/로 복사하지 않고 Git에 추가하지 않는다.
- 일반 application log와 OpenAI metadata에는 새 원문 개인정보를 넣지 않는다.
- HTTP 200, preview 생성, confirmation 미호출 여부는 manifest.json과
  scenario-results.csv에서 함께 확인한다.

## 현재 해석의 한계

- 결과는 로컬 backend, 고정 fixture, 순차 실행에서의 관찰값이다.
- fallback-on profile의 live run에서는 fallback이 실제로 0회 실행됐다.
  불필요한 재시도가 없었다는 뜻이지, provider 오류에서 fallback 성공률을 live로
  입증했다는 뜻은 아니다.
- 추천 품질은 manual-review.csv에서 별도로 검토해야 한다.
- production 기본값은 여전히 single이다. feature flag 전환은 별도 운영 판단이다.
