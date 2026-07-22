# Agent 모델 평가 자동화

현재 단일 OpenAI Agent의 기준선입니다. Router/Specialist 구조로 바꾸기 전에 `gpt-5.5`와 `gpt-5.4-nano-2026-03-17`의 속도, 토큰, 추정 비용, 도구 선택을 같은 조건에서 비교합니다.

## 측정 범위

- 추천 품질·복잡도 문장 12개
- 시연 Agent 경로 5개: 추천, 결과 필터, 유사 상품, 주문 미리보기, 일괄 찜 미리보기
- 모델별 5회 반복 시 총 170개 샘플
- 모델 순서를 교차해 시간대 편향을 줄임
- 주문/찜은 **미리보기만 생성**하고 confirm API를 호출하지 않음

시나리오와 기대 도구 계약은 [single-agent-baseline-v1.json](/C:/github/weapon/junlge_namanmoo/docs/agent-evals/fixtures/single-agent-baseline-v1.json)에 있습니다.

## 사전 조건

로컬 backend가 실행 중이어야 합니다. `.env`의 실제 값은 이 문서나 결과물에 기록하지 않습니다.

```env
APP_ENV=local
OPENAI_API_KEY=...
OPENAI_AGENT_LOCAL_TRACE_ENABLED=true
OPENAI_AGENT_LOCAL_TRACE_DIR=/app/.local/agent-traces
```

인증이 필요한 주문/일괄 찜 미리보기에는 별도 테스트 계정만 사용합니다.

```powershell
$env:AGENT_EVAL_USER_EMAIL = "test-user@example.com"
$env:AGENT_EVAL_USER_PASSWORD = "..."
```

## 실행

먼저 외부 API를 호출하지 않는 계획 검증을 합니다.

```powershell
python scripts/agent/evaluate_agent_models.py --dry-run --repeat 1
```

파일럿은 17개 시나리오 x 2개 모델 x 1회입니다. 주문/일괄 찜 시나리오는 미리보기만 생성하지만, 명시적으로 허용해야 포함됩니다.

```powershell
python scripts/agent/evaluate_agent_models.py `
  --repeat 1 `
  --run-id single-agent-baseline-v1-pilot `
  --allow-write-previews
```

전체 기준선은 모델별 5회 반복입니다.

```powershell
python scripts/agent/evaluate_agent_models.py `
  --repeat 5 `
  --run-id single-agent-baseline-v1-full `
  --allow-write-previews
```

중단된 실행은 같은 `--run-id`에 `--resume`을 붙여 재개할 수 있습니다. 실패 샘플도 다시 시도하려면 `--retry-failed`를 추가합니다.

```powershell
python scripts/agent/evaluate_agent_models.py `
  --repeat 5 `
  --run-id single-agent-baseline-v1-full `
  --allow-write-previews `
  --resume `
  --retry-failed
```

## 기록물

생성 경로는 `docs/agent-evals/results/<run-id>/`이며 Git에는 포함되지 않습니다.

- `manifest.json`: 실행 조건, fixture 해시, 안전 설정
- `samples.jsonl`: 재개 가능한 샘플 원장
- `scenario-results.csv`: 샘플별 모델, HTTP/Agent 시간, 토큰, 추정 비용, 도구·제약 검증
- `model-summary.csv`: 모델·그룹별 p50/p95, 토큰, 추정 비용, 검증률
- `manual-review.csv`: 추천 품질·자연어 해석을 사람이 평가할 표
- `report.md`: 실행 요약과 해석 규칙

원본 요청/응답, 선택 도구 스키마, 모델 인자, 도구 응답은 로컬 trace인 `apps/backend/.local/agent-traces/`에만 남습니다. 이 파일은 개인정보 또는 테스트 계정 문맥을 포함할 수 있으므로 결과 폴더나 Git으로 복사하지 않습니다.

trace header 또는 파일이 누락되면 실행기는 기본적으로 즉시 중단합니다. trace 자체를 점검하는 상황에서만 `--allow-missing-trace`를 사용합니다.

## 해석 기준

- `client_roundtrip_ms`: 호출 클라이언트가 본 전체 왕복 시간
- `route_total_ms`: backend route 내부 전체 시간
- `agent_model_and_orchestration_ms`: 실제 모델 호출이 발생한 샘플의 모델·Agents SDK 단계 시간
- `model_source=not_called`: 규칙 기반 fast path로 모델을 호출하지 않은 샘플. 모델 성능 평균에 섞지 않음
- `estimated_cost_usd`: 입력/캐시 입력/출력 토큰에 대한 로컬 추정치. OpenAI Usage의 실제 청구와는 다를 수 있음

`gpt-5.4-nano`의 로컬 토큰 단가는 OpenAI의 [GPT-5.4 nano 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-nano)를 기준으로 `input $0.20/M`, `cached input $0.02/M`, `output $1.25/M`을 적용합니다.
