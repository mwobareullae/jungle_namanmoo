# 추천 성능 결과 보관 규칙

`perf-runs`는 추천 성능 측정의 원본 run과 로컬 분석 산출물을 보관한다. 원본은 Git에 추가하지 않고 이 README만 추적한다.

## 폴더 구조

```text
perf-runs/
  inbox/
  stages/
    <stage-id>/
      runs/
        scale-sweep/
        headline-repeats/
        diagnostics/
          <topic>/
      analysis/
        README.md
        00-summary/
        10-pipeline/
        20-instrumentation/
        30-root-cause/
          intent-parser/
          scoring/
          data-loading/
        40-guardrails/
        data/
  transitions/
    <stage-id>/
  workbench/
    previews/
  quarantine/
  legacy/
    pending-removal/
```

## 원본 run 분류

- `scale-sweep`: dataset 또는 VUS를 체계적으로 바꾼 실행
- `headline-repeats`: 동일한 공식 비교 조건으로 반복한 실행
- `diagnostics/<topic>`: 세부 계측을 추가해 특정 병목을 조사한 실행
- `inbox`: 실행할 때 분류값을 주지 않은 새 run
- `quarantine`: 실패, 미완료, 외부 부하 개입 등으로 공식 비교에서 제외한 run

하나의 원본 run은 한 위치에만 둔다. 대표 run도 복사하지 않고 `scripts/perf/recommendation-performance-report.json`에서 run ID로 선택한다.

## 분석 산출물 분류

- `00-summary`: latency, RPS, 오류율, dataset/VUS matrix
- `10-pipeline`: client/backend, pipeline stage, Pareto, context load
- `20-instrumentation`: metric 존재 여부, 표본 수, null 비율, 로그 커버리지
- `30-root-cause/intent-parser`: intent, LLM, purchase parser
- `30-root-cause/scoring`: scoring, score loop
- `30-root-cause/data-loading`: behavior, ingredient effect, prefetch
- `40-guardrails`: backend, Elasticsearch, Redis의 CPU와 메모리
- `data`: `summary.csv`, 세부 CSV, `analysis-manifest.json`

`workbench/previews`는 그래프 개발 중 임시 출력만 둔다. 공식 문서에 쓰는 최종 그래프와 CSV는 `docs/performance/results/recommendation`에서 생성한다.

## 보존과 삭제

1. 이동 전후에 run ID, manifest 수, 파일 SHA-256을 비교한다.
2. 동일 run ID의 모든 상대 파일 경로·크기·SHA-256이 같을 때만 중복 복사본으로 확정한다.
3. 검증된 중복과 재생성 가능한 preview만 삭제할 수 있다.
4. 분류나 삭제 판단이 불확실하면 `legacy/pending-removal`에 보존한다.
5. `quarantine` run은 공식 비교에서는 제외하지만 원본은 유지한다.

## 단계 분석 흐름

각 `stages/<stage-id>/analysis/README.md`는 아래 순서를 유지한다.

1. 전체 성능
2. 큰 파이프라인 병목
3. 기존 로그의 부족한 부분
4. 추가한 세부 계측
5. 확인한 실제 원인
6. 선택한 다음 최적화
7. 대응하는 transition 결과

최종 비교 수치와 공유용 그래프는 [추천 성능 결과](../docs/performance/results/recommendation/README.md)에서 확인한다.
