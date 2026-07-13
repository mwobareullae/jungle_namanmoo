# 일반 상품 검색 성능 최적화 기록

작성일: 2026-07-11

## 1. 목적

일반 상품 검색 v1의 실제 전체 색인 79,963건을 대상으로 다음 성능 기준을
만족시키는 과정을 기록한다.

- 상품 검색 API p95 500ms 미만
- 자동완성 API p95 200ms 미만
- HTTP 오류율 1% 미만

대상 API는 다음과 같다.

```text
GET /api/search/products
GET /api/search/suggestions
```

이번 최적화는 서버 사양을 높이거나 Redis 같은 새 인프라를 추가하지 않았다.
요청 경로의 로그를 확인해 불필요한 DB 조회와 과도한 집계 범위를 제거하는
방식으로 진행했다.

## 2. 측정 조건

- 환경: 로컬 Docker Compose
- Elasticsearch 색인 상품 수: 79,963건
- 부하 도구: k6
- 동시 사용자: 10 VU
- 측정 시간: 2분
- 각 iteration: 상품 검색 1회 + 자동완성 1회
- HTTP 오류 허용 기준: 1% 미만

실행 명령은 다음과 같다.

```bash
k6 run \
  -e BASE_URL=http://127.0.0.1:8000/api \
  -e PROFILE=catalog \
  tests/k6/commerce-smoke.js
```

성능 기준은 `tests/k6/commerce-smoke.js`에 다음과 같이 고정돼 있다.

```text
http_req_duration{type:catalog_search}       p(95) < 500ms
http_req_duration{type:catalog_suggestions}  p(95) < 200ms
http_req_failed                              rate < 1%
```

## 3. 측정 결과

| 단계 | 상품 검색 p95 | 자동완성 p95 | iterations/s | 오류율 |
| --- | ---: | ---: | ---: | ---: |
| 최초 측정 | 2.70s | 449.37ms | 4.86 | 0% |
| 복구 조회 1차 개선 | 1.14s | 334.00ms | 8.86 | 0% |
| 최종 개선 | 371.79ms | 119.67ms | 19.30 | 0% |

최종 측정에서는 2분 동안 2,324 iterations, 4,649 HTTP 요청을 처리했다.
상품 검색 평균은 248.71ms, 자동완성 평균은 67.20ms였다.

`p95 371.79ms`는 모든 요청이 371.79ms 이내였다는 뜻이 아니다. 요청을 빠른
순서대로 정렬했을 때 95% 지점이 371.79ms였다는 뜻이며, 최종 측정의 상품 검색
최대 시간은 1.3초였다.

## 4. 병목을 찾은 방법

먼저 Elasticsearch 자체가 느린지, Elasticsearch 앞뒤의 백엔드 처리가 느린지
분리했다.

검색 완료 로그에는 다음 시간이 함께 기록된다.

```text
catalog_search_completed.duration_ms
catalog_search_completed.elasticsearch_duration_ms
```

느린 요청에서 전체 응답은 1~2초였지만 Elasticsearch 검색은 대체로
50~170ms였다. 따라서 주 병목은 Elasticsearch가 아니라 검색 전후의
PostgreSQL 조회라고 판단했다.

`db_slow_query` 로그에서는 다음 쿼리가 반복되는 것을 확인했다.

- 정상 검색에도 오타 복구용 성분·상품·브랜드 사전 조회
- 매 요청마다 브랜드와 alias 약 2,638행 전체 조회
- 검색 결과 20건을 보강하면서 전체 상품 가격을 그룹화하는 조회
- Elasticsearch 자동완성 성공 후 다시 실행하는 브랜드 DB 조회

이 로그를 기준으로 요청의 critical path에서 필요 없는 작업부터 제거했다.

## 5. 최적화 1: 정상 검색의 복구 DB 조회 생략

### 기존 문제

Elasticsearch 정상 결과가 충분해 복구 검색을 실행하지 않을 요청에서도 먼저
복구 계획을 만들었다. 이 과정에서 브랜드 전체 목록과 성분·카테고리·상품
사전을 PostgreSQL에서 조회했다.

```text
정상 검색
→ 복구 사전 DB 조회
→ 결과가 3건 이상인지 확인
→ 복구 검색 생략
```

결국 사용하지 않을 복구 정보를 만들기 위해 DB 비용을 먼저 지불하고 있었다.

### 변경 후

Elasticsearch 정상 결과 수를 먼저 확인한다.

```text
정상 결과 3건 이상
→ DB 복구 사전 조회 생략
→ 정적으로 확정된 교정어만 메모리에서 확인

정상 결과 0~2건
→ 복구 계획 생성
→ 오타·자판·브랜드 사전 조회
→ 제한된 복구 검색 실행
```

구현 위치:

- `apps/backend/app/services/catalog_search_service.py`
  - `_build_recovery_plan_for_result`
- `apps/backend/app/services/catalog_search_recovery.py`
  - `build_catalog_search_recovery_plan`

이 변경만 적용한 중간 측정에서 상품 검색 p95가 2.70초에서 1.14초로
감소했다.

## 6. 최적화 2: 브랜드·카테고리 사전 60초 캐시

### 기존 문제

검색어에서 브랜드를 감지하기 위해 요청마다 활성 브랜드와 alias를 모두
조회했다. 실제 데이터에서는 약 2,638행이었으며 동시 요청 10개가 같은 조회를
반복해 DB connection과 네트워크를 함께 사용했다.

### 변경 후

브랜드·카테고리 lookup dictionary를 백엔드 프로세스 메모리에 60초 동안
보관한다.

```text
첫 요청 또는 TTL 만료
→ PostgreSQL 조회
→ Python dict 생성
→ 60초 캐시

TTL 안의 요청
→ 메모리 dict 재사용
```

구현 위치:

- `apps/backend/app/services/catalog_search_query.py`
  - `_LOOKUP_CACHE_TTL_SECONDS`
  - `_brand_lookup`
  - `_category_lookup`

이 캐시는 Redis가 아닌 프로세스 내부 캐시다. 각 백엔드 worker가 별도 캐시를
가지며 worker 재시작 후 첫 요청은 DB를 조회한다. 브랜드·카테고리 변경은 최대
60초 뒤 파서 사전에 반영될 수 있다.

SQLite 단위 테스트에서는 전역 캐시로 인해 테스트 데이터가 섞이지 않도록
캐시를 사용하지 않는다.

## 7. 최적화 3: 가격 집계 범위를 검색 결과로 제한

### 기존 문제

Elasticsearch가 상위 상품 20개를 골라도 PostgreSQL 보강 쿼리의 최저가
subquery는 전체 `product_prices`를 상품별로 그룹화했다.

개념적으로 다음과 같은 형태였다.

```sql
SELECT product_id, MIN(price)
FROM product_prices
GROUP BY product_id;
```

필요한 것은 20개 상품의 가격뿐인데 전체 가격표를 먼저 집계한 셈이다.

### 변경 후

Elasticsearch가 반환한 현재 페이지의 상품 ID를 가격 집계 안으로 먼저 넣었다.

```sql
SELECT product_id, MIN(price)
FROM product_prices
WHERE product_id IN (:current_page_product_ids)
GROUP BY product_id;
```

구현 위치:

- `apps/backend/app/services/catalog_search_service.py`
  - `_load_catalog_rows`
  - `_catalog_row_statement`

핵심은 `GROUP BY` 뒤에서 결과를 버리는 대신 집계 전에 대상 행 수를 줄이는
것이다.

## 8. 최적화 4: 자동완성의 중복 DB 조회 제거

### 기존 문제

Elasticsearch 자동완성이 성공해 상품과 브랜드 정보가 이미 있어도 브랜드
후보를 PostgreSQL에서 한 번 더 조회했다.

### 변경 후

- Elasticsearch 성공: Elasticsearch suggestion document에서 브랜드 추출
- Elasticsearch 실패: 제한된 DB fallback에서 브랜드와 상품 조회

구현 위치:

- `apps/backend/app/services/catalog_suggestion_service.py`
  - `get_catalog_suggestions_response`

정상 경로에서는 자동완성 한 번에 Elasticsearch 요청 하나만 사용하게 됐다.

## 9. 최종 요청 흐름

상품 검색의 정상 흐름은 다음과 같다.

```text
검색어 입력
→ 60초 캐시된 브랜드·카테고리 사전으로 파싱
→ Elasticsearch 검색·랭킹·facet 집계
→ 결과가 3건 미만일 때만 복구 검색
→ 현재 페이지 상품만 PostgreSQL에서 최신 가격·재고 확인
→ 응답
```

자동완성의 정상 흐름은 다음과 같다.

```text
검색어 prefix 입력
→ Elasticsearch edge/초성 필드 검색
→ PRODUCT·BRAND·CATEGORY·CORRECTION 타입 구성
→ 응답
```

## 10. 사용한 기술과 역할

| 기술 | 역할 |
| --- | --- |
| FastAPI | 검색·자동완성 HTTP API |
| Elasticsearch 8.15.3 | 후보 검색, 랭킹, facet, 자동완성 |
| analysis-nori | 한국어 형태소 검색 |
| PostgreSQL | 상품·가격·재고 source of truth |
| SQLAlchemy | 검색 결과 보강 및 fallback 쿼리 |
| Python 메모리 캐시 | 저변경 사전의 반복 DB 조회 제거 |
| 구조화 성능 로그 | 전체 시간, ES 시간, slow query 분리 |
| k6 | 동시 사용자 부하와 p95·오류율 측정 |

성능 향상의 핵심은 새로운 기술을 추가한 것이 아니라 기존 요청에서 불필요하게
반복되던 일을 제거한 것이다.

## 11. 정확성 검증

성능만 높이고 검색 결과를 바꾸지 않았는지 다음 검증을 함께 실행했다.

- 실제 API 품질 평가: 118/118 통과
- 정확 상품 Hit@1: 100%
- 브랜드 Precision@10: 100%
- 카테고리 Precision@20: 100%
- 오타 복구율: 100%
- 필터 위반: 0건
- 무관 인기 상품 채움: 0건
- 잘못된 자동 교정: 0%
- Docker 비-slow·비-live 테스트: 373 passed, 22 deselected

품질 평가 명령은 다음과 같다.

```bash
docker compose exec -T backend \
  python -m app.cli.evaluate_catalog_search_quality \
  --base-url http://localhost:8000/api \
  --json-output /tmp/catalog-search-quality-report.json \
  --markdown-output /tmp/catalog-search-quality-report.md
```

전체 회귀 테스트 명령은 다음과 같다.

```bash
docker compose exec -T backend \
  python -m pytest -m "not slow and not live"
```

## 12. 운영 적용 시 주의점

이번 결과는 로컬 Docker 기준이므로 운영 성능을 보장하는 수치는 아니다.

- dev·운영 환경에서 같은 k6 시나리오를 다시 실행한다.
- RDS network latency와 connection pool 대기를 함께 확인한다.
- 백엔드 worker 수가 늘어나면 worker마다 브랜드 사전 캐시를 따로 가진다.
- 브랜드·카테고리 실시간 반영이 필요해지면 명시적 cache invalidation을 검토한다.
- p95만 보지 말고 p99, 최대 시간, timeout, 오류율도 함께 본다.
- Elasticsearch 장애 시 DB fallback의 호출량과 지연을 별도로 측정한다.
- 데이터 증가 후에는 가격 보강 쿼리를 `EXPLAIN ANALYZE`로 재확인한다.

## 13. 공부할 핵심 주제

이번 최적화에서 일반화해 공부할 만한 주제는 다음과 같다.

1. 평균 latency와 p50·p95·p99의 차이
2. 요청 critical path와 단계별 timing 계측
3. DB round trip과 반복 조회 제거
4. cache TTL, cold start, invalidation, stale data
5. SQL filter pushdown과 aggregation 대상 축소
6. `EXPLAIN ANALYZE`와 DB index 확인
7. 검색 엔진과 원본 DB의 역할 분리
8. 동시성 부하 테스트와 처리량·지연의 관계
9. 최적화 전후 품질 회귀 테스트

권장 학습 순서는 `p95 이해 → slow query 로그 읽기 → EXPLAIN ANALYZE → 캐시
트레이드오프 → k6 부하 테스트`다.
