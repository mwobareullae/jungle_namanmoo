# 성능 테스트

성능 테스트 실행 방법, 목표 수치, 검색 성능 기록을 모아둔 폴더다.

## 먼저 읽을 문서

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
