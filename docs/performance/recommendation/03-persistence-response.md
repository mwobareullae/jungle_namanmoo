# 03. 저장·응답 최적화

## 문제

추천 결과를 만들고 난 뒤에도 500개 후보의 추적 레코드, 최종 결과·근거, 응답용 재조회가 요청 경로에 남아 있었다. 화면에는 10개만 표시하지만 저장 단계는 더 많은 중간 데이터를 다뤘다.

## 판단과 변경

- 사용 계획이 없는 후보 500개 `SearchCandidate` 추적 저장을 제거했다.
- 남겨야 하는 최종 결과와 근거는 ORM 객체를 반복 생성하는 대신 SQLAlchemy Core 기반 bulk insert 경로로 저장했다.
- 저장 직후 화면을 만들 때는 ORM 관계 전체를 다시 불러오지 않고, 화면 10개에 필요한 컬럼만 읽는 projection query를 사용했다.

## 확인한 수치

| 지표 | 변경 전 | 변경 후 | 변화 |
| --- | ---: | ---: | ---: |
| HTTP p95 | 6.48초 | 4.48초 | -2.00초 |
| 후보 trace 저장 평균 | 0.60초 | 0초 | 제거 |
| 후보 trace flush 평균 | 0.43초 | 0초 | 제거 |

아래 두 저장 지표는 후보 trace를 제거한 직접 효과다. Core bulk insert와 projection query는 같은 저장·응답 구간을 추가로 줄이는 후속 변경이므로, 서로 다른 run의 내부 지표를 임의로 더하지 않았다.

## 왜 SQLAlchemy Core인가

최종 결과·근거는 저장 직후 ORM 객체 그래프를 다시 사용할 필요가 없다. 이 경로에서는 ORM 단위 객체 생성·flush 비용보다, 필요한 컬럼만 한 번에 입력하는 SQLAlchemy Core가 더 적합했다. 반대로 복잡한 도메인 규칙을 다루는 점수 계산은 ORM/도메인 모델 흐름을 유지했다.

## 근거

- persistence drill-down: `perf-runs/stages/opt6-candidate-pool-v2/analysis/diagnostics/persistence/data/persistence-drilldown-timings.csv`
- Opt7 실행 흐름과 저장 시간: `perf-runs/stages/opt7-remove-candidate-trace/analysis/00-summary/execution-flow/persistence/README.md`
- 단계별 선택 run: `perf-runs/stages/opt10-candidate-cache/analysis/01-optimization-timeline/stage-summary.csv`
