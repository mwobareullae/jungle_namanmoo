# P2 부하테스트 KPI 및 성능 개선 보고서 초안

작성일: 2026-07-10
상태: Draft — 실제 측정값 입력 전
분류: **필수 문서 2/2 — 성능 측정과 최적화 검증 상세**
대상 환경: EC2 `t3.large`(FastAPI, Redis, Elasticsearch), RDS PostgreSQL + pgvector, S3/CloudFront, Vercel
기준 데이터: 상품 약 80,000건

> 이 문서는 기술 리포트의 성능 측정 부분을 실행 가능한 테스트 조건·KPI·Before/After 형식으로 구체화한 문서다.

## 1. 한 줄 목표

> 상품 8만 건과 EC2 t3.large 환경에서 P2 핵심 사용자 여정을 50 VU로 10분간 수행할 때, 성공률 99% 이상과 API 등급별 p95 목표를 만족하고 OOM, 컨테이너 재시작, DB connection 고갈 없이 처리한다.

첨부 기술 보고서처럼 최종 결과를 `RPS 0 → 5000`처럼 표현하려면 먼저 실제 최대 지속 처리량을 측정해야 한다. 현재 k6는 VU 기반이고 한 iteration 안에서 여러 API를 순차 호출하므로, VU 수를 RPS로 표현하면 안 된다. 최종 보고서에는 아래 두 값을 분리해서 기록한다.

- 사용자 여정 처리량: `iterations/s`
- HTTP 처리량: `http_reqs/s`

최종 대표 문장은 다음 형식을 사용한다.

> **상품 8만 건, t3.large, 50 VU, 10분 기준**
> **여정 성공률 A% → B%, 전체 p95 A초 → B초, HTTP 처리량 A req/s → B req/s, 최대 지속 처리량 A req/s → B req/s**

## 2. 현재 결과의 사용 가능 범위

### 2.1 8만 건 baseline: 최초 문제 상태로 사용

`perf-runs/20260708-113413_baseline_full-80000` 결과는 최적화 전 문제 상태를 설명하는 자료로 사용한다.

| 항목 | 결과 |
| --- | ---: |
| 환경 | EC2 t3.xlarge, 10 VU, 4분 |
| HTTP 처리량 | 0.6568 req/s |
| 실패율 | 12.64% |
| 전체 p95 | 60.00초 |
| 홈 p95 | 60.00초 |
| 추천 생성 p95 | 52.17초 |
| 상품 검색 p95 | 32.29초 |
| slow query | 870건 |
| backend 최대 메모리 | 2.78GiB |
| 당시 backend limit | 6GiB |
| Elasticsearch 최대 메모리 | 1.447GiB / 2GiB limit |

이 결과는 정상 baseline이 아니라 이미 timeout과 5xx가 발생한 실패 상태다. 당시 환경은 t3.xlarge에서 backend limit 6GiB, Docker PostgreSQL과 frontend container까지 포함했다. 현재 목표 환경은 t3.large에서 RDS와 Vercel을 외부로 분리한 구성이므로 개선 전후의 절대 비교 기준으로 단독 사용하지 않는다.

다만 backend가 실제로 2.78GiB까지 사용한 실행에 2GiB 제한을 적용하면 OOM 가능성이 있다. Compose 기본값 `BACKEND_MEMORY_LIMIT=2g`를 실제 운영 적정값으로 간주하지 않고, 서버의 `docker inspect` 결과와 새 t3.large baseline을 기준으로 재산정한다.

### 2.2 1천 건 smoke: KPI 기준에서 제외

`perf-runs/20260710-023115_smoke_small-1000`은 실패율이 46.3%지만, 119건의 실패가 구현되지 않은 홈 경로의 404 응답이다.

```text
/api/home/layout
/api/home/market-popular
/api/home/evidence-picks
/api/home/for-you
```

현재 backend에는 `/api/home/sections`가 구현되어 있어 k6 시나리오와 API route가 일치하지 않는다. 404 응답시간이 10~30ms라서 홈 API가 빠른 것처럼 보이므로, 해당 실행의 홈 latency와 전체 처리량은 성능 근거로 사용하지 않는다.

## 3. P2 성능 KPI 제안

아래 값은 현재 P2 범위와 t3.large 한 대 구성을 기준으로 한 1차 목표다. 유효한 8만 건 baseline을 다시 얻은 뒤 한 차례 보정한다.

### 3.1 필수 통과 KPI

| 분류 | KPI | Smoke | Baseline/Target |
| --- | --- | ---: | ---: |
| 정확성 | k6 check 성공률 | 100% | 99% 이상 |
| 오류 | 예상하지 않은 4xx/5xx | 0건 | 전체 요청의 1% 미만 |
| 안정성 | OOM/container restart | 0건 | 0건 |
| 처리량 | dropped iteration | 0건 | 전체 iteration의 1% 미만 |
| 회복성 | 부하 종료 후 health 정상화 | 즉시 | 1분 이내 |

`http_req_failed < 1%`만으로는 부족하다. HTTP 200이지만 응답 body가 비었거나 추천 결과가 없는 경우도 실패로 계산하도록 k6 check 성공률을 함께 사용한다.

### 3.2 API latency KPI

| API 등급 | 대상 | p95 | p99 |
| --- | --- | ---: | ---: |
| health | `GET /health` | 300ms 이하 | 500ms 이하 |
| fast read | 인기상품, 상품상세, 추천결과 조회 | 1초 이하 | 2초 이하 |
| home | 실제 계약에 존재하는 홈 API | 1.5초 이하 | 3초 이하 |
| search | 상품 검색 | 2초 이하 | 3초 이하 |
| recommendation core | 추천 생성, 외부 LLM 제외 | 3초 이하 | 5초 이하 |
| write | 장바구니 추가, checkout preview | 1.5초 이하 | 3초 이하 |
| LLM E2E | LLM 의도분석/서술 포함 별도 테스트 | 8초 이하 | 12초 이하 |

현재 스크립트는 `fast/home/search/write` 모두 동일하게 p95 3초를 사용한다. 보고서에서는 API 특성이 다른 만큼 위 등급별 기준으로 분리한다.

### 3.3 처리량 KPI

| KPI | 정의 | 1차 목표 |
| --- | --- | ---: |
| baseline 처리량 | 10 VU, 10분 동안의 `http_reqs/s` | 10 req/s 이상 |
| target 안정성 | 50 VU, 10분 동안 모든 필수 KPI 유지 | PASS |
| 처리량 유지율 | 실제 처리량 / 주입 요청률 | 95% 이상 |
| 최대 지속 처리량 | 필수 KPI를 5분 이상 만족하는 가장 높은 요청률 | stress에서 측정 |
| 포화 후 회복 | 부하를 낮춘 뒤 p95가 target 기준으로 복귀 | 1분 이내 |

10 req/s는 최종 사업 트래픽 목표가 아니라 현재 0.6568 req/s 실패 상태에서 정상 baseline을 만들기 위한 1차 검증값이다. 서비스의 예상 DAU, 피크 동시 사용자, 사용자당 요청 수가 확정되면 target 요청률을 다시 계산한다.

### 3.4 서버와 데이터 계층 KPI

| 계층 | KPI | 목표 |
| --- | --- | ---: |
| EC2 | 전체 CPU 평균/최대 | 평균 70% 이하, 5분 최대 90% 이하 |
| EC2 | CPU credit | `CPUCreditBalance` 20 이상, 고갈 없음 |
| EC2 | 디스크 사용률 | 70% 미만 |
| FastAPI | 컨테이너 메모리 | limit의 80% 미만 |
| Elasticsearch | 컨테이너 메모리 | limit의 80% 미만 |
| Redis | 컨테이너 메모리 | limit의 80% 미만, eviction 사유 기록 |
| RDS | CPU 평균/최대 | 평균 60% 이하, 최대 80% 이하 |
| RDS | DB connection | 최대 연결 수의 70% 미만 |
| RDS | idle in transaction | 2회 연속 샘플에서 1개 이상이면 FAIL |
| RDS | slow query | API 요청당 0.2건 이하, 1초 초과 쿼리 0건 |
| 전체 | OOM/restart | 0건 |

### 3.4.1 P2 컨테이너 메모리 1차 설정

최적화 전 t3.large 검증에서는 다음 값을 1차 설정으로 사용한다.

```text
BACKEND_MEMORY_LIMIT=3584m
ELASTICSEARCH_MEMORY_LIMIT=2g
ELASTICSEARCH_HEAP_SIZE=1g
REDIS_MEMORY_LIMIT=512m
REDIS_MAXMEMORY=256mb
```

backend 3584MiB는 기존 2.78GiB peak가 약 80%가 되는 임시 안전값이다. 최종 설정은 전체 hydrate 제거와 검색 경로 정상화 후 다시 측정한다.

| 최적화 후 backend peak | 판단 |
| --- | --- |
| 2.4GiB 이하 | 3GiB limit 검토 |
| 2.4~2.8GiB | 3584MiB 유지 |
| 2.8GiB 이상 지속 | t3.large 단일 구성 한계 검토 |
| OOM 또는 3GiB 이상 증가 | 인스턴스 상향 또는 ES 분리 실험 |

Compose 선언값만으로 적용을 가정하지 않는다. 각 run의 manifest에 `docker inspect`로 확인한 실제 memory limit을 기록한다.

### 3.5 검색·추천 경로 KPI

| KPI | 목표 |
| --- | ---: |
| Elasticsearch index/alias 정상 | 테스트 전 100% |
| pgvector embedding coverage | 99% 이상 |
| 검색 요청의 DB fallback 비율 | 1% 미만 |
| 추천 요청의 `legacy_id_order` 단독 fallback 비율 | 1% 미만 |
| 대표 검색어 5종의 정상 응답 | 100% |
| 추천 결과 1개 이상 반환 | 99% 이상 |
| 추천 `intent_parse_ms` p95 | 외부 LLM 제외 300ms 이하 |
| 추천 `candidate_pool_ms` p95 | 500ms 이하 |
| 추천 `scoring_ms` p95 | 1초 이하 |

LLM 호출을 포함한 `intent_parse_ms`는 외부 서비스 지연이 섞인다. 내부 추천 엔진 KPI와 LLM 포함 E2E KPI를 별도 프로파일로 측정해야 한다.

## 4. 테스트 매트릭스

| 단계 | 데이터 | 부하 | 시간 | 목적 | 통과 조건 |
| --- | ---: | ---: | ---: | --- | --- |
| Contract preflight | 1천/8만 | 요청 1회 | 1분 이내 | route, status, schema 확인 | 모든 대상 API check 100% |
| Smoke | 8만 | 1 VU | 1분 | 테스트와 관측 도구 검증 | 실패 0건 |
| Baseline | 8만 | 10 VU | 10분 | 개선 전후 고정 비교 | 필수 KPI PASS |
| Target | 8만 | 20 → 50 VU | 각 5분 | P2 목표 동시 사용자 검증 | 50 VU 구간 필수 KPI PASS |
| Endpoint capacity | 8만 | arrival-rate 단계 증가 | 단계별 5분 | API별 최대 지속 RPS 산출 | 처리량 유지율 95% 이상 |
| Stress | 8만 | 50 → 100 VU | 각 5분 | 포화점과 회복 확인 | 한계점과 최초 실패 원인 기록 |
| Write load | 8만 | 별도 profile | 10분 | Cart/Checkout transaction 검증 | 오류 <1%, 재고/합계 불변식 유지 |
| Soak | 8만 | 10 VU | 60분 | 메모리/connection/디스크 누수 | 우상향 누수 및 restart 0건 |

### 테스트 조건 고정값

개선 전후 비교 시 아래 값이 하나라도 다르면 같은 실험으로 비교하지 않는다.

- Git SHA와 변경사항
- EC2/RDS instance type
- Docker memory/CPU limit
- 상품, 이미지, 성분, 검색문서, embedding 건수
- Elasticsearch index 이름과 alias
- k6 script SHA, profile, VU/arrival rate, 실행 시간
- 검색어와 추천 요청 fixture
- cart write, 인증 사용자, narrative, LLM 활성 여부
- 테스트 실행 위치와 접근 URL
- 캐시 cold/warm 상태

각 실험은 동일 조건으로 3회 실행하고 p95 중앙값을 대표값으로 사용한다. 3회 결과 편차가 10%를 넘으면 원인을 확인한 뒤 다시 측정한다.

## 5. 현재 테스트 도구에서 보완할 항목

### P0. 유효한 baseline을 만들기 위한 필수 보완

1. k6 홈 endpoint와 실제 API 계약을 일치시킨다.
2. 부하 시작 전 대상 route를 한 번씩 호출하고 예상 status가 아니면 즉시 종료한다.
3. t3.large와 8만 건 데이터로 smoke를 먼저 통과시킨다.
4. smoke 통과 전에는 baseline/target/stress 결과를 성능 개선 수치로 사용하지 않는다.

홈 route 구조 변경 여부는 API 계약에 영향을 주므로 구현 전에 확인이 필요하다.

### P1. KPI 계산에 필요한 수집 항목

현재 `parse_k6.py`와 report는 latency와 HTTP 실패율 중심이다. 다음 항목을 추가해야 기술 보고서의 전후 비교를 자동 생성할 수 있다.

- `checks` 성공률
- `iterations`, `iterations/s`, `iteration_duration`
- `dropped_iterations`
- endpoint별 요청 수와 req/s
- status code별 요청 수
- endpoint별 p50/p95/p99와 timeout 수
- 단계별 VU/arrival-rate와 실제 처리량
- 추천 stage duration p95
- 검색 backend별 성공/실패/fallback 비율
- EC2 CPU, memory, disk, `CPUCreditBalance`
- Elasticsearch query latency, JVM heap, rejected request
- Redis memory, hit rate, eviction
- RDS 상위 slow query와 `EXPLAIN (ANALYZE, BUFFERS)`

### P1. RPS 측정 방식 보완

현재 `constant-vus`와 `ramping-vus`는 서버가 느려지면 k6가 요청을 덜 보내기 때문에, 서버가 처리 가능한 RPS를 정확히 주입하지 못한다. API별 최대 지속 RPS는 `constant-arrival-rate` 또는 `ramping-arrival-rate`로 별도 측정한다.

전체 사용자 여정은 VU 기반으로 유지하고, 홈·검색·추천·상품상세는 endpoint별 arrival-rate 시나리오를 추가한다.

### P1. 추천 품질 평가 도구 분리

k6는 추천 API가 빠르고 안정적으로 응답하는지를 측정한다. 추천된 상품이 적합한지는 별도의 offline evaluator에서 측정한다.

```text
k6
→ p50/p95/p99 · 오류율 · req/s · iterations/s · stage latency · 자원 사용률

offline recommendation evaluator
→ label QA · HitRate@10 · MRR@10 · Recall@50 · NDCG@10 · ablation · slice metrics

서비스 이벤트
→ 추천 노출 · 클릭 · 장바구니 · 구매 · 부정 행동 전환
```

offline evaluator가 수집할 최소 지표:

| 구분 | 지표 |
| --- | --- |
| Silver-label QA | Product mapping rate, Concern/Effect precision, Leakage rate, Human agreement, Label coverage |
| 후보 추출 | Recall@50 |
| 개별 리뷰 ranking | HitRate@10, MRR@10, Negative exposure@10 |
| 고민 그룹 ranking | Concern-group NDCG@10 |
| 설명 가능성 | Evidence path coverage, Source traceability, Concentration decision success |
| 편향 확인 | head/mid/tail, 카테고리, 고민, 피부 타입별 slice metrics |
| 차별점 검증 | 인기순, BM25, 성분-only, +효능, +근거, +함량 ablation |

성능 report와 추천 품질 report에는 같은 Git SHA, scoring version, dataset version을 기록해 “빠른 모델”과 “적합한 모델”을 같은 변경 단위로 비교한다.

## 6. 성능 개선 보고서 구성

첨부 README와 같은 결과물을 만들 때 각 개선 단계는 아래 구조를 반복한다.

### 6.1 보고서 첫 화면

```text
결론

상품 8만 건, t3.large, 50 VU, 10분 기준
- 전체 p95: Before → After
- 오류율: Before → After
- HTTP 처리량: Before → After
- 최대 지속 처리량: Before → After
- 병목 자원: Before → After
```

### 6.2 개선 단계별 기록

```text
## N차 고도화: 변경 제목

### 테스트 조건
- Git SHA:
- 데이터 건수:
- 인스턴스:
- 부하 profile:
- 실행 시간:
- 캐시 상태:

### 문제 상황
- 사용자 증상:
- endpoint p95/p99:
- 오류율:
- 처리량:
- 병목 로그/쿼리:

### 가설
- 왜 느리다고 판단했는가:
- 어떤 지표가 개선되면 가설이 맞는가:

### 변경 사항
- 코드/쿼리/인덱스/캐시 변경:
- 영향 범위:

### 검증 결과
| KPI | Before | After | 변화율 | 목표 | 판정 |
| --- | ---: | ---: | ---: | ---: | --- |
| p95 | | | | | |
| p99 | | | | | |
| 오류율 | | | | | |
| HTTP req/s | | | | | |
| RDS CPU | | | | | |
| slow query/request | | | | | |

### 실행계획 또는 내부 stage 비교
- EXPLAIN ANALYZE:
- 추천 stage duration:
- ES/pgvector/fallback 비율:

### 부작용과 회귀 검증
- 정확성 회귀:
- 메모리 증가:
- 캐시 정합성:
- 비용 변화:

### 결론
- 가설 채택/기각:
- 다음 병목:
```

## 7. 권장 성능 개선 챕터 순서

아래 항목은 확정 구현 목록이 아니라 baseline에서 병목이 확인됐을 때 적용하는 최적화 후보이다. 각 단계는 `측정 → 가설 → 한 가지 변경 → 동일 조건 재측정` 순서로 진행한다.

| 최적화 후보 | 우선순위 | 적용 조건 | 핵심 검증 지표 |
| --- | --- | --- | --- |
| 쿼리 튜닝 | 최우선 | N+1, 중복 조회, 불필요한 JOIN, 과다 row, slow query 확인 | API당 query 수, 반환 row 수, DB time, p95/p99 |
| 일반/pgvector 인덱스 | 높음 | 실행계획에서 Seq Scan, 고비용 정렬, vector full scan 확인 | `EXPLAIN (ANALYZE, BUFFERS)`, CPU/I/O, latency, Recall@50 |
| Redis cache | 높음 | 동일한 홈·상품·근거·추천 결과가 반복 조회되고 원본 쿼리 개선이 끝난 뒤 | hit rate, p95, DB 부하, 정합성, eviction |
| application pool/PgBouncer | 조건부 | connection 생성 비용, wait, 고갈, 과도한 idle connection 확인 | pool wait, active/idle connection, timeout, p95 |
| RDS read replica | P3 확장 | 쿼리·인덱스·cache 이후에도 read CPU/I/O가 지속 포화 | primary/read CPU, replica lag, read throughput, 비용 |

적용 순서는 다음을 원칙으로 한다.

```text
구간별 시간·실행계획 측정
→ 쿼리와 인덱스 최적화
→ 반복 read Redis cache
→ connection pool 조정 또는 PgBouncer 검증
→ 필요할 때만 read replica
```

PgBouncer와 read replica는 단일 요청의 느린 쿼리를 직접 해결하는 수단으로 간주하지 않는다. connection 또는 읽기 처리량 병목이 측정된 경우에만 별도 실험한다.

### P2 인프라 분리 판단

발표 전에는 FastAPI·Elasticsearch·Redis를 t3.large 한 대에 유지하고, 자동화·관측·쿼리 최적화를 먼저 완료한다. 다른 일반 EC2로 ES·Redis를 옮기면 서버·보안·스토리지·배포·장애 복구 대상이 늘고 기존 baseline도 다시 측정해야 한다.

- Redis는 활성 cache 경로와 실제 memory/eviction이 확인되기 전에는 분리하지 않는다.
- 공유 CPU·메모리 부족이면 단일 EC2 사양 상향을 먼저 비교한다.
- ES heap 75% 이상 지속, rejected request, ES indexing과 backend p95의 상관, CPU credit 고갈이 반복될 때 ES만 별도 분리한다.
- 관리형 OpenSearch/ElastiCache 이전은 호환성과 비용을 검증한 뒤 P3 확장으로 다룬다.

### 1차: 홈 전체 hydrate 제거

- 최초 근거: 홈 p95 60초, 상품 약 79,516행과 성분 최대 39만행 조회
- 목표: 홈 p95 1.5초 이하
- 핵심 비교: DB 반환 row 수, slow query, RDS CPU, 응답 p95

### 2차: Elasticsearch/pgvector 검색 경로 정상화

- 최초 근거: Elasticsearch CPU 0.68%, 검색 p95 32.29초, DB fallback 의심
- 목표: 검색 p95 2초 이하, DB fallback 1% 미만
- 핵심 비교: ES query latency, fallback 비율, DB query 수, `EXPLAIN (ANALYZE, BUFFERS)`
- pgvector가 실제 candidate retrieval 경로이고 vector full scan이 확인된 경우에만 HNSW/IVFFlat을 비교한다.
- HNSW/IVFFlat 적용 전후에는 latency뿐 아니라 Recall@50, index size, build time, RDS CPU/I/O를 함께 기록한다.
- Elasticsearch가 후보 검색을 담당하는 경로라면 ES mapping·filter·top-K와 PostgreSQL fallback 정상화가 pgvector 인덱스보다 우선한다.

### 3차: 추천 pipeline 분해와 후보군 제한

- 최초 근거: 추천 생성 p95 52.17초, intent parse와 candidate/scoring 지연
- 목표: 외부 LLM 제외 추천 core p95 3초 이하
- 핵심 비교: `intent_parse_ms`, `candidate_pool_ms`, `scoring_ms`, 후보 수

### 4차: 상품 상세/인기상품 조회 최적화

- 최초 근거: 병목 전파 시 fast API도 p95 3~8초
- 목표: fast read p95 1초 이하
- 핵심 비교: query 수, 이미지/가격 조회 row 수, cache hit rate
- N+1, 중복 조회, 불필요한 JOIN을 먼저 제거하고 원본 쿼리가 목표를 만족하는지 확인한다.
- Redis는 반복 read에 적용하고 cache key에 dataset/scoring version을 포함한다.
- cold/warm p95, DB 부하, hit rate, TTL, eviction, 무효화 후 정합성을 함께 검증한다.

### 5차: connection pool 검증

- SQLAlchemy/application pool의 size, overflow, wait time, active/idle connection을 먼저 측정한다.
- connection wait·생성 비용·고갈이 확인된 경우에만 pool 값을 조정하거나 PgBouncer를 별도 실험한다.
- transaction pooling 사용 시 session 상태와 prepared statement 등 호환성을 회귀 검증한다.
- 핵심 비교: connection wait p95, DB connection 수, timeout, API p95, transaction 오류

### 6차: Cart/Checkout 동시성

- 읽기 API가 target을 통과한 뒤 별도 write profile로 진행한다.
- 목표: write p95 1.5초 이하, 오류율 1% 미만, 재고/가격/주문 불변식 위반 0건

### P3 확장: 읽기 전용 요청 분산

- 쿼리·인덱스·cache 최적화 후에도 RDS read CPU/I/O가 지속 포화될 때 read replica를 검토한다.
- replica lag 허용 범위와 eventual consistency가 가능한 API만 분산한다.
- 현재 P2의 40초 단일 요청 지연을 해결하는 1차 수단으로 사용하지 않는다.

## 8. 최종 완료 기준

성능 개선 한 단계는 다음 조건을 모두 만족해야 완료로 기록한다.

1. 동일한 환경과 데이터에서 Before/After를 각각 3회 측정했다.
2. 기능 check 성공률이 99% 이상이고 5xx가 증가하지 않았다.
3. 목표 API의 p95와 p99가 개선됐다.
4. 처리량이 유지되거나 증가했다.
5. 다른 API의 p95가 10% 이상 악화되지 않았다.
6. OOM, restart, connection 고갈이 없다.
7. 실행계획 또는 stage log로 개선 원인을 설명할 수 있다.
8. 결과 폴더와 Git SHA가 보고서에 연결되어 있다.

## 9. 다음 실행 순서

1. 홈 API 계약과 k6 endpoint 불일치를 먼저 해소한다.
2. 8만 건/t3.large smoke를 실행해 모든 check가 100%인지 확인한다.
3. 10 VU, 10분의 새 baseline을 3회 실행한다.
4. baseline 중앙값을 이 문서의 1차 목표와 비교해 KPI를 보정한다.
5. query 수와 `EXPLAIN (ANALYZE, BUFFERS)`로 쿼리·인덱스 병목을 먼저 확정한다.
6. 홈 API부터 한 번에 하나의 가설만 적용해 Before/After를 측정한다.
7. 반복 read에는 Redis를 검증하고, connection 병목이 있을 때만 PgBouncer를 검토한다.
8. target 50 VU를 통과하면 endpoint별 arrival-rate로 최대 지속 RPS를 산출한다.
