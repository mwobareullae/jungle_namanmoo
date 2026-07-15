# 추천 후보 데이터 Bulk Prefetch

## 상태

구현은 현재 브랜치에 존재하지만, 성능 리포트 registry에 구현 단계가 증명된 동일 조건 측정 run은 아직 등록하지 않았다. 따라서 이 문서는 설계와 검증 기준만 정의하며 성능 수치나 개선율을 예상값으로 채우지 않는다.

## 관측

Opt2에서 상품 특징과 사용자 선호를 사전 계산한 뒤에도 scoring의 데이터 사전 조회 구간이 남았다. 후보 500개의 점수 입력을 구성할 때 성분·효능, 기능성, 피부 태그, 위험 플래그, 리뷰와 행동 신호를 여러 loader에서 나눠 읽고 Python에서 합친다.

`candidate_bundle_ms`는 DB 실행 시간만이 아니다. 후보 데이터 조회, fetch, 변환과 bundle 구성까지 포함한 load time으로 해석한다. 요청당 SQL 횟수는 별도 런타임 계측이 없으므로 실측값처럼 표현하지 않는다.

## 원인 가설

- 동일 후보 ID 집합을 기준으로 관계 데이터를 여러 번 조회한다.
- 조회 결과를 후보별 점수 입력 구조로 반복 조립한다.
- 각 loader의 왕복과 materialization 비용이 누적된다.

이 항목은 측정 전 가설이다. Opt3 run을 등록한 뒤 `scoring_data_prefetch_ms`, `prefetch_candidate_bundle_ms`, backend 전체 p95가 함께 줄었는지 확인해야 원인과 효과를 확정할 수 있다.

## 검토한 대안

### 전체 상품 Snapshot 테이블

추천 입력을 상품별 JSON 또는 넓은 snapshot으로 미리 만들 수 있다. 읽기는 단순해지지만 데이터 중복, 갱신 fan-out, 버전 관리 비용이 크므로 bulk JOIN의 효과가 부족하다는 측정 근거가 생길 때 검토한다.

### Redis 결과 캐시

동일 요청에는 빠르지만 검색어, 사용자 프로필, 스킨 테스트와 행동 상태 조합이 커서 hit rate와 무효화 정책을 먼저 증명해야 한다. 현재 병목의 구조적 원인을 숨길 수 있어 첫 선택에서 제외했다.

## 선택과 트레이드오프

후보 ID 묶음에 필요한 점수 입력을 bulk 조회하고, 기존 점수식이 받는 구조로 한 번에 조립한다. 점수 공식과 결과 계약은 유지한다.

- 장점: 조회 왕복과 Python의 중복 후보 매핑을 줄인다.
- 비용: JOIN 결과의 행 폭과 중복 전송량이 커질 수 있다.
- 방어: 후보 수와 batch 크기를 제한하고 기존 loader fallback을 유지한다.
- 관측: backend latency와 함께 CPU·메모리를 guardrail로 확인한다.

## 동일 조건 재측정 기준

- actual 상품 수: `79,952`
- 사용자: `full-personalized`
- 부하: VUS `10`, `3m`, closed-loop
- cache: `cold`
- 오류율 gate: `1%` 이하
- 반복: 최소 3회, 중앙값과 개별 점을 함께 사용

비교 대상은 `Opt2 precomputed features`다. 오류 gate를 통과한 동일 조건 run만 개선율에 사용하며, 누락된 세부 지표는 0이 아닌 unavailable로 남긴다.

## 결과 등록

측정이 완료되면 `scripts/perf/recommendation-performance-report.json`의 `opt3-bulk-prefetch`에 raw run root 또는 run 경로를 등록하고 다음 명령을 실행한다.

```powershell
python scripts/perf/generate_recommendation_performance_report.py
```

새 결과는 타임라인과 파이프라인 비교에 자동 추가되고, 상세 문서는 측정 데이터가 있을 때 생성 대상이 된다.
