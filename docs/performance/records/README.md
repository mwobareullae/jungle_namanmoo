# 성능 테스트 기록

이 폴더에는 실제로 실행한 성능 테스트 결과를 날짜별로 저장한다.

## 기록 템플릿

```md
# YYYY-MM-DD 시나리오

## 실행 정보

- commit:
- environment:
- data size:
- command:

## 결과

- requests:
- p50:
- p95:
- p99:
- error rate:

## 결론

-
```

계획 문서나 목표 수치는 상위 `docs/performance/` 문서에 두고, 실제 측정값만 이 폴더에 추가한다.
