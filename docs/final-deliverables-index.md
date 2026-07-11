# 뭐바를래 최종 산출물 읽기 안내

작성일: 2026-07-10
상태: Draft package index

## 먼저 읽을 문서

### 1. 기술 리포트

[`technical-report-final-draft.md`](./technical-report-final-draft.md)

서비스 목표와 기술적 의의, 고민-효능-성분-함량-근거 추천 구조, 리뷰 기반 추천 평가, 8만 상품 성능 문제와 최적화 방향을 한 문서에서 설명한다.

팀원이 전체 맥락을 이해하기 위해 가장 먼저 읽어야 하는 문서다.

### 2. 성능 KPI 및 개선 보고서

[`performance-kpi-draft.md`](./performance-kpi-draft.md)

기술 리포트의 성능 부분을 실제로 측정하기 위한 테스트 조건, p95/p99·RPS·오류율·자원 KPI, 최적화 순서와 Before/After 기록 형식으로 구체화한다.

성능 테스트와 최적화를 직접 수행하거나 결과를 검증하는 팀원이 읽어야 한다.

## 부록: 참고용 예시 초안

아래 문서는 필수 기준이 아니며 기술 리포트와 성능 KPI를 발표·화면·실행 일정으로 옮겨본 예시다. 실제 팀 상황, 최신 코드와 API 계약, 합의된 역할분담을 우선한다.

### 부록 A. 발표 구성 예시

[`final-presentation-outline-draft.md`](./final-presentation-outline-draft.md)

7분 발표를 인트로 1분, 데모 5분, 클로징 1분으로 구성한 예시다. 실측 결과가 나온 뒤 슬라이드 순서와 문구를 다시 확정한다.

### 부록 B. 화면 설계 예시

[`screen-design-final-draft.md`](./screen-design-final-draft.md)

고민 입력부터 추천 근거·구매 연결, 내부 추천 품질 화면까지의 설계 예시다. 확정 route나 API 계약이 아니다.

### 부록 C. 역할·마일스톤 예시

[`final-presentation-milestone-plan.md`](./final-presentation-milestone-plan.md)

7월 19일 완료와 7월 25일 발표를 가정한 역할·산출물·KPI·일정 예시다. 담당자와 업무량은 팀 합의 전에 확정 기준으로 사용하지 않는다.

## 문서 우선순위

문서 간 내용이 다르면 다음 순서로 판단한다.

```text
실제 코드·migration·테스트·최신 API 계약
→ 기술 리포트
→ 성능 KPI 및 개선 보고서
→ 발표·화면·역할 마일스톤 부록
```

## 현재 남은 작업

- 리뷰 평가 데이터셋과 human gold set 생성
- 실제 리뷰 저장·조회 API 연결 및 mock 리뷰와 구분
- 최신 `dev` 배포, migration `20260710_0029`·seed 적용, 추천 가능 상품 수 검증
- 인기순/BM25/ablation/최종 모델의 추천 품질 실측
- t3.large·8만 상품의 유효한 성능 baseline
- 최적화 전후 동일 조건 재측정
- 목표값과 예시값을 실제 결과로 교체

실측되지 않은 목표값과 예시값은 완료 성과로 발표하지 않는다.
