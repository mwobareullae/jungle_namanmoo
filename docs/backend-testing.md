# Backend Test Suites

백엔드 pytest는 PR 대기 시간을 줄이기 위해 fast suite와 full suite로 나눈다.

## Fast Suite

PR 기본 검증에서 실행한다.

```bash
docker compose exec -T backend python -m pytest -m "not slow and not live"
```

포함:

- API 계약, 인증, 장바구니, 주문, 결제, 이벤트, 추천 핵심 로직
- 예시 데이터 기반 단위/통합 테스트

제외:

- `slow`: 전체 `data/` 카탈로그를 읽는 넓은 회귀 테스트
- `live`: OpenAI 등 외부 유료 서비스 호출 테스트

## Full Suite

dev/main push, 야간 스케줄, 수동 workflow dispatch에서 실행한다.

```bash
docker compose exec -T backend python -m pytest
```

포함:

- fast suite 전체
- full data parser/recommendation intent 회귀 테스트
- opt-in 조건이 맞으면 live 테스트

## Marker 기준

- `slow`: 전체 `data/` 카탈로그나 넓은 회귀 경로를 검증해서 PR마다 돌리기에는 무거운 테스트
- `live`: 외부 유료 API를 호출할 수 있어 환경변수로 명시적으로 켜야 하는 테스트

## 현재 측정값

- 개선 전 전체 pytest: 약 3분 34초
- 캐싱 후 전체 pytest: 약 1분 03초
- PR fast suite: 약 49초

측정값은 로컬 Docker 환경 기준이라 CI 머신 상태에 따라 달라질 수 있다.
