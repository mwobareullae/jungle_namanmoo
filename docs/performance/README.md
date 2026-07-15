# 성능 테스트

성능 테스트 실행 방법, 목표 수치, 검색 성능 기록을 모아둔 폴더다.

## 먼저 읽을 문서

- [추천 성능 최적화 Case Study](recommendation-performance-case-study.md)
- [추천 성능 리포트 재생성](#추천-성능-리포트-재생성)
- [부하 테스트 실행 방법](load-testing.md)
- [검색 성능 최적화 기록](catalog-search-performance-optimization.md)
- [데이터 규모별 테스트](data-scale-test-5000.md)
- [성능 KPI 초안](performance-kpi-draft.md)

## 결과 기록

실제 실행 결과는 [records](records/) 아래에 날짜와 시나리오 기준으로 저장한다.

권장 파일명:

```text
YYYY-MM-DD_<scenario>_<data-size>.md
```

기록에는 실행 커밋, 데이터 규모, 환경, 요청 수, p50/p95/p99, 오류율, 주요 설정과 결론을 포함한다.

## 추천검색 최적화 설계

- [추천검색 ES Retrieval 전환 최적화 설계](recommendation-es-retrieval-optimization.md)
- [추천 사전 계산 특징 배치](recommendation-feature-rollup.md)
- [추천 후보 데이터 Bulk Prefetch](recommendation-bulk-prefetch.md)

## 추천 성능 리포트 재생성

원본 run은 `perf-runs`에 그대로 보존하고 아래 명령으로 정규화 데이터, 핵심 그래프, 단계별 결과 문서를 함께 만든다.

```powershell
python -m pip install -r scripts/perf/requirements-analysis.txt
python scripts/perf/generate_recommendation_performance_report.py
```

산출물은 `results/recommendation` 아래 `main`, `details`, `appendix`, `data`로 분리된다. 새 최적화 단계는 `scripts/perf/recommendation-performance-report.json`에 다음 항목을 추가하고 다시 생성한다.

1. 구현 변경을 설명하는 고유 `id`, 순서, 색상
2. 직전 비교 단계인 `compared_to`
3. 검증된 raw run의 `roots` 또는 `runs`
4. 관측, 원인, 대안, 트레이드오프, 구현 구조, 새 병목
5. 상세 설계 문서와 직접 효과를 확인할 `focus_metrics`

계측 필드만 추가된 경우에는 새 Opt 단계를 만들지 않는다. 로그에 실제로 존재하는 필드에 따라 `measurement_schema`가 자동 분류된다.
