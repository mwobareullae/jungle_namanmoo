# 04. 캐시·동시 처리 확장

## 문제

로직 최적화 이후에도 동일 조건의 후보 생성은 반복될 수 있고, 단일 프로세스는 CPU 자원을 동시에 활용하는 데 한계가 있다. 이 단계는 알고리즘을 다시 바꾸기보다, 이미 줄인 추천 경로를 안정적으로 반복 처리하는 데 초점을 맞췄다.

## 판단과 변경

- 추천 후보 목록을 조건 기반 Redis cache에 보관해 동일 조건의 후속 요청에서 후보 생성 비용을 피했다.
- cold/warm 상태를 분리해 측정해 캐시 효과를 숨기지 않았다.
- Uvicorn multi-worker로 CPU 작업을 여러 프로세스에서 처리할 수 있게 하고, worker 수·VUS별 결과와 서버 리소스 스냅샷을 함께 남겼다.

## 확인한 수치

| 지표 | 변경 전 | 변경 후 | 변화 |
| --- | ---: | ---: | ---: |
| HTTP p95 | 4.48초 | 3.12초 | -30.4% |
| 완료 처리량 | 2.809 RPS | 4.631 RPS | +64.9% |
| 오류율 | 측정 run별 확인 | 0.00% | 최종 선택 run |

HTTP p95와 RPS는 다른 축이다. 첫 번째는 느린 요청의 체감 지연을, 두 번째는 같은 시간에 완료된 요청 수를 보여 준다.

## 해석 범위

`3.12초`는 Redis warm cache와 multi-worker를 함께 적용한 선택 run의 결과다. 따라서 이 수치를 순수 코드 최적화 하나의 효과로 해석하지 않고, 실서비스에서 반복 요청과 동시 처리를 포함한 운영 경로의 결과로 기록한다.

## 근거

- 최적화 타임라인: `perf-runs/stages/opt10-candidate-cache/analysis/01-optimization-timeline/stage-summary.csv`
- worker·자원 스냅샷: 각 `perf-runs/stages/opt11-worker-scaleout/` run의 `docker-stats.csv`, `system-metrics.csv`
