# 02. 개인화 점수화 최적화

## 문제

후보를 빠르게 확보한 뒤에도 500개 후보의 성분·효능·피부·리뷰·행동 신호를 요청마다 읽고 정밀 계산하면 점수화가 다음 병목이 됐다. Opt1 이후에도 `scoring_ms` 평균은 `3.70초`였다.

## 판단과 변경

- 자주 변하지 않는 상품 성분·효능 정보를 사전 집계 feature로 만들어 요청 경로의 조인과 객체 구성을 줄였다.
- 후보별로 흩어진 조회를 `bulk prefetch`로 모아 DB 왕복을 줄였다.
- 500개는 가벼운 coarse 점수로 먼저 정렬하고, 상위 50개만 exact scoring을 수행하는 `coarse-to-fine ranking`으로 계산 범위를 축소했다.

## 확인한 수치

| 지표 | 변경 전 | 변경 후 | 변화 |
| --- | ---: | ---: | ---: |
| HTTP p95 | 12.80초 | 6.48초 | -6.32초 |
| `scoring_ms` 평균 | 3.70초 | 1.20초 | -67.6% |
| 상세 평가 대상 | 500개 | 50개 | -90.0% |

`scoring_ms` 평균은 Opt1과 Opt6의 같은 내부 지표를 비교한 값이다. HTTP p95와 합산하지 않고, 요청 체감 지연과 점수화 자체의 개선을 각각 확인했다.

## 세부 계측에서 확인한 원인

| 점수화 구간 | Baseline 평균 | Opt3 평균 |
| --- | ---: | ---: |
| prefetch | 5.84초 | 0.88초 |
| score loop | 1.08초 | 0.45초 |
| 총 `scoring_ms` | 6.97초 | 1.65초 |

사전 집계와 bulk prefetch는 데이터 준비 시간을, coarse-to-fine ranking은 상세 계산 대상을 줄이는 역할을 분리해서 담당한다.

## 근거

- 점수화 세부 계측: `docs/performance/results/recommendation/transitions/data/scoring-component-metrics.csv`
- 파이프라인 단계 변화: `docs/performance/results/recommendation/transitions/data/pipeline-component-deltas.csv`
- coarse-to-fine 실행 흐름: `perf-runs/stages/opt7-remove-candidate-trace/analysis/00-summary/execution-flow/README.md`
