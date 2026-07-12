# 3차 Vector Search 고도화 설계안

작성일: 2026-07-06
상태: 구현 전 설계안
관련 문서:

- `docs/embedding-plan.md`
- `docs/search-fallback-reindex-plan.md`
- `docs/f180-candidate-generation-plan.md`

## 결론

3차 vector search 고도화는 `Elasticsearch dense_vector`를 바로 도입하지 않고, 이미 프로젝트에 준비된 PostgreSQL `pgvector` 기반으로 먼저 구현한다.

추천 방향:

1. 임베딩 대상은 기존 합의안처럼 `search_documents` 조인 문서로 유지한다.
2. 임베딩 모델은 기존 설정과 DB 타입에 맞춰 `text-embedding-3-small`, 1536차원을 우선 사용한다.
3. Elasticsearch는 현재 구현된 keyword search source로 유지한다.
4. vector search는 새로운 후보 source인 `pgvector_search`로 추가한다.
5. 추천 API는 `pgvector_search + es_keyword_search + legacy DB fill` fanout 구조로 확장한다.
6. `/products/search` API는 기존 응답 구조를 유지하면서 vector 결과를 fallback/fill 또는 hybrid rerank로 단계적으로 붙인다.
7. Elasticsearch, OpenAI embedding, pgvector 중 하나가 없어도 기존 DB 방식은 계속 동작해야 한다.

즉, 3차의 목적은 "검색 인프라 교체"가 아니라 "현재 추천/검색 흐름에 semantic retrieval source를 추가하는 것"이다.

## 현재 상태

### 이미 구현된 것

현재 코드 기준으로 아래 기반은 이미 있다.

| 구분 | 상태 |
|---|---|
| `search_documents` 조인 문서 생성 | `build_search_index_documents` CLI 존재 |
| 임베딩 저장 컬럼 | `search_documents.embedding vector(1536)` 존재 |
| 임베딩 메타데이터 | `embedding_model`, `embedding_dimensions`, `embedding_updated_at` 존재 |
| 임베딩 생성 CLI | `embed_search_documents` 존재 |
| 추천 내부 vector score | 후보가 정해진 뒤 `match_product_search_documents()`에서 계산 가능 |
| ES keyword index | 상품 검색용 Elasticsearch index/alias 구조 구현 |
| ES keyword source | 추천 후보와 `/products/search`에서 사용 가능 |
| ES fallback | ES 실패 시 DB 방식으로 계속 동작 |
| 검색 API | `GET /api/products/search` 구현 완료 |

### 아직 없는 것

| 구분 | 부족한 부분 |
|---|---|
| vector retrieval source | 10만 상품의 `search_documents.embedding`에서 직접 후보를 찾는 기능 없음 |
| pgvector index | HNSW/IVFFlat index migration 아직 없음 |
| vector candidate diagnostics | source별 vector 검색 성공/실패/coverage 진단 없음 |
| 검색 API hybrid merge | ES keyword 결과와 vector 결과를 합치는 정책 없음 |
| 운영용 embedding 검증 | OpenAI embedding coverage, 비용, 실패 문서 기록 보강 필요 |

중요한 점은 현재 vector는 "이미 뽑힌 후보를 점수화하는 보조 요소"에 가깝다. 3차에서는 vector를 "후보를 직접 찾아오는 retrieval source"로 올리는 것이 핵심이다.

## 범위

### 3차에 포함

- `search_documents` embedding coverage 확인
- pgvector 검색 서비스 추가
- 추천 candidate pool에 `pgvector_search` source 추가
- vector source diagnostics 추가
- `/products/search`에 vector fallback/fill 또는 hybrid rerank 추가
- ES/DB fallback 유지
- 테스트와 Docker 검증

### 3차에서 제외

- Elasticsearch `dense_vector` 전환
- 외부 vector DB 도입
- BGE-M3, multilingual-E5, Voyage 등 모델 교체
- nori analyzer 적용
- 실시간 incremental reindex 자동화
- 상품 변경 이벤트 기반 자동 re-embedding

위 항목은 기능 가치가 있지만, 지금 단계에서 같이 넣으면 검색 구조, 운영 방식, 비용 검증이 한꺼번에 흔들린다.

## 왜 pgvector 우선인가

### 이유 1. 이미 DB schema가 준비되어 있다

현재 `SearchDocument.embedding`은 PostgreSQL에서 `vector(1536)`로 동작하도록 migration이 있다. 모델 기본값도 `text-embedding-3-small`, 1536차원으로 맞춰져 있다.

따라서 pgvector를 쓰면 큰 schema 변경 없이 시작할 수 있다.

### 이유 2. 팀 문서 방향과 맞다

`embedding-plan.md`는 P2/P3 전환 전 단계에서 PostgreSQL + pgvector를 우선 유지하는 방향을 제안했다. 지금의 3차는 이 방향을 실제 검색 source로 활성화하는 작업이다.

### 이유 3. Elasticsearch 의존도를 키우지 않는다

현재 Docker 운영 방식에서는 backend만 띄우는 경우 Elasticsearch가 같이 뜨지 않는다.

따라서 3차에서도 아래 조건을 반드시 유지해야 한다.

- Elasticsearch가 없어도 백엔드 실행 가능
- Elasticsearch가 없어도 추천 가능
- Elasticsearch가 없어도 검색 API 가능
- vector embedding이 없어도 기존 DB fallback 가능

pgvector 우선 설계는 이 조건을 지키기 쉽다.

### 이유 4. 변경 범위가 작다

Elasticsearch vector search로 바로 가면 ES mapping, index rebuild, embedding bulk sync, score merge, 운영 메모리까지 한꺼번에 바뀐다.

반면 pgvector 우선이면:

- 기존 `search_documents` 사용
- 기존 embedding CLI 사용
- 기존 DB transaction/테스트 구조 사용
- ES keyword source는 그대로 유지

이 방식이 지금 프로젝트에는 더 안전하다.

## 목표 아키텍처

### 추천 후보 생성

```text
RecommendationIntent
→ retrieval fanout
  - es_keyword_search source
  - pgvector_search source
  - legacy_id_order DB fill
→ merge / dedupe
→ avoid ingredient filter
→ match_product_search_documents
→ score_candidates
→ recommendation_results 저장
```

`pgvector_search`와 `es_keyword_search`는 서로 대체 관계가 아니라 fanout source다. 실행 순서보다 중요한 것은 각 source의 결과를 독립적으로 모아 merge/dedupe한다는 점이다.

- keyword search는 정확한 단어, 상품명, 브랜드, 카테고리에 강하다.
- vector search는 표현이 달라도 의미가 가까운 상품을 찾는 데 강하다.
- legacy DB fill은 안전망이다.

### 상품 검색 API

초기 3차에서는 기존 API 응답 구조를 깨지 않는다.

```text
GET /api/products/search?q=...
→ ES keyword search 시도
→ pgvector search 시도
→ 결과 merge/fill
→ 상품 카드 hydrate
→ 둘 다 실패하면 DB fallback
```

초기 구현은 pagination 안정성을 위해 아래 원칙을 둔다.

1. ES keyword 결과가 충분하면 기존 pagination 기준을 유지한다.
2. ES 결과가 부족하거나 실패하면 vector 결과로 채운다.
3. ES와 vector를 둘 다 쓸 수 있으면 page window 안에서 score를 병합한다.
4. hybrid 전체 total count를 정확히 계산하는 작업은 별도 합의 후 진행한다.

이유는 ES keyword 결과와 vector 결과의 union total을 정확히 계산하려면 많은 후보를 가져와 dedupe해야 하고, 10만 상품에서 비용이 커질 수 있기 때문이다.

## 데이터와 임베딩 대상

### 임베딩 대상

대상은 `search_documents` 중 아래 조건을 만족하는 문서다.

```text
document_type = 'product'
document_code LIKE 'idx_prod_join_%'
product_id IS NOT NULL
```

임베딩 텍스트는 기존 함수와 동일하게 유지한다.

```text
title + "\n" + content + "\n" + keywords
```

이유:

- 기존 scoring에서 실제 읽는 문서가 `search_documents`다.
- 상품, 브랜드, 카테고리, 피부 적합도, 성분, 효능, risk, 함량 단서가 포함된다.
- pending 성분 제외 정책을 search index builder 쪽에서 반영할 수 있다.

### 모델

초기 모델은 아래로 고정한다.

| 항목 | 값 |
|---|---|
| 모델 | `text-embedding-3-small` |
| 차원 | 1536 |
| 저장소 | `search_documents.embedding` |
| dev/CI fallback | `local-hash-v1` |

`local-hash-v1`은 테스트와 로컬 동작 확인용이다. 검색 품질 검증에는 사용하지 않는다.

## 사전 조건

3차 구현 전에 아래가 되어 있어야 한다.

| 순서 | 조건 | 필요한 이유 |
|---:|---|---|
| 1 | `search_documents` build 완료 | vector 검색 대상 문서가 있어야 함 |
| 2 | embedding dry-run 확인 | 몇 개 문서가 임베딩 대상인지 알아야 함 |
| 3 | OpenAI embedding 실제 생성 | semantic search 품질 검증에 필요 |
| 4 | embedding coverage 확인 | coverage가 낮으면 vector search 결과가 비어 보일 수 있음 |
| 5 | pgvector index 방식 확인 | 10만 상품에서 latency를 지키기 위해 필요 |
| 6 | fallback 정책 유지 | ES/OpenAI/pgvector 장애 시 기존 기능 보호 |

로컬 Docker dev DB에서는 현재 상품 수가 약 1,135개 수준으로 확인됐다. 이 규모에서는 index 없이도 동작 검증은 가능하지만, 10만 상품 성능 검증에는 HNSW 또는 IVFFlat index가 필요하다.

## 구현 순서

### 1단계. embedding coverage 확인

먼저 실제 DB에 `search_documents`와 embedding이 얼마나 있는지 확인한다.

확인 항목:

- product join document 수
- embedding 존재 문서 수
- embedding model
- embedding dimensions
- embedding coverage 비율

성공 기준:

- join document가 상품 수와 비슷해야 한다.
- OpenAI embedding 기준 coverage가 최소 80% 이상이어야 vector source를 켠다.
- coverage가 낮으면 vector source는 diagnostics에 skipped로 남기고 기존 검색만 사용한다.

왜 먼저 해야 하는가:

vector search는 embedding이 있어야만 가능하다. 문서나 embedding이 비어 있으면 코드가 맞아도 결과가 안 나온다.

### 2단계. pgvector 검색 서비스 추가

새 서비스 파일을 추가한다.

예상 파일:

```text
apps/backend/app/services/pgvector_product_search.py
```

반환 형태:

```python
@dataclass(frozen=True)
class PgvectorProductSearchResult:
    product_db_ids: tuple[int, ...]
    scores_by_product_db_id: dict[int, float]
    raw_hit_count: int
    attempted: bool
    query_text: str
    provider_model: str | None
    dimensions: int | None
    duration_ms: int
    failure_reason: str | None = None
    skipped_reason: str | None = None
```

기본 쿼리:

```sql
SELECT
  search_documents.product_id,
  MAX(GREATEST(0.0, 1.0 - (embedding <=> CAST(:query_embedding AS vector)))) AS vector_score
FROM search_documents
JOIN products ON search_documents.product_id = products.id
JOIN brands ON products.brand_id = brands.id
JOIN product_categories ON products.category_id = product_categories.id
JOIN product_prices ON product_prices.product_id = products.id
WHERE search_documents.document_type = 'product'
  AND search_documents.document_code LIKE 'idx_prod_join_%'
  AND search_documents.embedding IS NOT NULL
  AND search_documents.embedding_model = :embedding_model
  AND search_documents.embedding_dimensions = :embedding_dimensions
  AND products.is_active = true
  AND brands.is_active = true
  AND product_categories.is_active = true
GROUP BY search_documents.product_id
ORDER BY vector_score DESC, search_documents.product_id ASC
LIMIT :limit
```

가격, 브랜드, 카테고리 조건은 `RecommendationIntent.purchase_conditions`를 통해 추가한다.

왜 별도 서비스로 두는가:

- 추천 후보 source와 상품 검색 API가 같은 vector 검색을 재사용할 수 있다.
- ES keyword 코드와 fallback 진단 구조를 비슷하게 맞출 수 있다.
- 테스트에서 fake search function을 주입하기 쉽다.

### 3단계. candidate pool에 `pgvector_search` source 추가

현재 candidate pool source는 크게 두 개다.

- `es_keyword_search`
- `legacy_id_order`

여기에 `pgvector_search`를 추가한다.

초기 merge 순서:

```text
es_keyword_search
pgvector_search
legacy_id_order
```

단, 내부 pre-score는 source weight를 따로 둔다.

| Source | 초기 weight |
|---|---:|
| `es_keyword_search` | 0.90 |
| `pgvector_search` | 0.85 |
| `legacy_id_order` | 0.20 |

keyword를 vector보다 아주 조금 앞에 두는 이유:

- 상품명이나 브랜드를 직접 검색한 경우 keyword exact match가 더 안전하다.
- vector는 의미 확장에 강하지만, 가끔 너무 넓게 잡을 수 있다.
- 최종 ranking은 여전히 `score_candidates()`가 결정하므로 source weight는 후보 pool truncation에만 쓴다.

성공 기준:

- ES가 켜져 있으면 ES + vector + legacy source diagnostics가 남는다.
- ES가 꺼져 있어도 vector + legacy가 동작한다.
- embedding이 없으면 vector source는 skipped가 되고 legacy는 계속 동작한다.

### 4단계. 추천 점수화와 diagnostics 연결

현재 `match_product_search_documents()`는 후보가 정해진 뒤 keyword score와 vector score를 섞는다.

3차에서는 이 구조를 유지한다.

즉, vector는 두 번 관여할 수 있다.

1. candidate pool 단계: 의미적으로 가까운 후보를 더 많이 데려온다.
2. scoring 직전 search matching 단계: 최종 후보 안에서 vector score를 계산한다.

이중 사용이 문제되지는 않는다. 역할이 다르기 때문이다.

- candidate pool vector: recall 확보
- search matching vector: 최종 점수 보조

다만 diagnostics에서 두 값을 구분해야 한다.

예상 diagnostics:

```json
{
  "candidate_generation_version": "candidate_pool_pgvector_v1",
  "source_counts": {
    "es_keyword_search": 303,
    "pgvector_search": 400,
    "legacy_id_order": 500
  },
  "source_diagnostics": [
    {
      "source": "pgvector_search",
      "requested_limit": 400,
      "returned_count": 400,
      "after_dedupe_count": 382,
      "duration_ms": 41,
      "provider_model": "text-embedding-3-small",
      "embedding_dimensions": 1536,
      "embedding_coverage": 0.98
    }
  ],
  "fallback_used": false
}
```

### 5단계. `/products/search`에 vector fill 추가

검색 API는 기존 응답 구조를 유지한다.

초기 정책:

1. ES keyword search를 먼저 시도한다.
2. ES 결과가 page size보다 부족하면 pgvector 결과로 채운다.
3. ES가 실패하면 pgvector를 단독 사용한다.
4. pgvector도 실패하면 DB fallback을 사용한다.

`match_source` 값:

| 값 | 의미 |
|---|---|
| `elasticsearch` | ES keyword 결과 |
| `pgvector` | vector search 결과 |
| `hybrid` | ES와 vector가 모두 기여한 결과 |
| `database` | DB fallback 결과 |

초기에는 total count를 무리하게 정확히 계산하지 않는다. 기존 API contract를 지키되, diagnostics에 어떤 source가 사용됐는지 남긴다.

추가 diagnostics 후보:

```python
class ProductSearchDiagnostics(BaseModel):
    backend: str
    fallback_used: bool
    es_attempted: bool
    es_failure_reason: str | None = None
    es_duration_ms: int | None = None
    vector_attempted: bool = False
    vector_failure_reason: str | None = None
    vector_duration_ms: int | None = None
    vector_result_count: int = 0
```

### 6단계. pgvector index migration 검토

1,135개 dev 데이터에서는 index 없이도 기능 검증이 가능하다. 하지만 10만 상품에서는 index가 필요하다.

우선 검토 migration:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_documents_product_embedding_hnsw
ON search_documents
USING hnsw (embedding vector_cosine_ops)
WHERE document_type = 'product'
  AND document_code LIKE 'idx_prod_join_%'
  AND embedding IS NOT NULL;
```

확인해야 할 것:

- Docker Postgres의 pgvector 버전이 HNSW를 지원하는지
- `CREATE INDEX CONCURRENTLY`를 Alembic에서 autocommit으로 처리해야 하는지
- 10만 데이터에서 index build 시간과 메모리
- HNSW가 어려우면 IVFFlat 대안 적용

초기 구현은 index 없이 먼저 기능 테스트를 통과시키고, 성능 검증 단계에서 index migration을 붙이는 순서가 안전하다.

### 7단계. 품질/성능 검증

필수 검증:

| 검증 | 성공 기준 |
|---|---|
| ES on + vector on | 추천/API 정상, diagnostics에 두 source 표시 |
| ES off + vector on | 추천/API 정상, vector 또는 DB fallback |
| ES on + embedding 없음 | 추천/API 정상, vector skipped |
| OpenAI key 없음 | 서버 실행 정상, 운영 embedding batch는 실패 처리 가능 |
| DB fallback | 기존 방식으로 결과 반환 |
| 테스트 | 기존 테스트 + vector 신규 테스트 통과 |

품질 검증 검색어 예:

- `수분 진정 크림`
- `속건조 보습 추천`
- `민감 피부 장벽 세럼`
- `피지 조절 토너`
- `주름 탄력 앰플`

각 검색어마다 확인할 것:

- keyword로만 잡히지 않던 관련 상품이 vector로 보강되는가
- 브랜드/카테고리/가격 조건이 유지되는가
- 엉뚱한 상품이 상위에 과하게 섞이지 않는가
- ES가 꺼져도 결과가 나오는가

## fallback 정책

### 추천 API

```text
es_keyword_search 시도
→ pgvector_search 시도
→ 둘 중 가능한 source 결과를 merge
→ legacy_id_order로 부족분 보충
→ 그래도 부족하면 기존 scoring 가능한 후보만 사용
```

### 상품 검색 API

```text
ES keyword 성공
→ vector로 부족분 보강
→ 둘 다 실패하면 DB fallback
```

### embedding 문제

| 문제 | 처리 |
|---|---|
| embedding 없음 | vector source skipped |
| embedding model 불일치 | vector source skipped |
| query embedding 실패 | vector source failed, fallback |
| OpenAI API timeout | vector source failed, fallback |
| local-hash embedding만 있음 | dev/CI 외 품질 검증 불가로 표시 |

## 위험 요소와 해결책

### 위험 1. vector 결과가 너무 넓게 나온다

문제:

semantic search는 의미가 비슷하면 엉뚱한 카테고리까지 끌고 올 수 있다.

해결:

- 가격/브랜드/카테고리 hard filter를 vector query에도 적용한다.
- 최종 ranking은 기존 `score_candidates()`에 맡긴다.
- candidate source weight에서 keyword를 vector보다 약간 높게 둔다.

### 위험 2. embedding coverage가 낮다

문제:

일부 상품만 vector 검색 대상이 되면 결과가 편향된다.

해결:

- coverage가 기준 이하이면 vector source를 자동 skipped 처리한다.
- diagnostics에 coverage를 남긴다.
- 배포 전 embedding dry-run과 실제 embedding 실행을 절차로 둔다.

### 위험 3. OpenAI API key가 없는 환경에서 품질이 다르게 보인다

문제:

`local-hash-v1`은 semantic 품질을 보장하지 않는다.

해결:

- local hash는 테스트와 로컬 fallback 전용으로 명시한다.
- 운영/품질 검증 배치는 `--require-openai`를 사용한다.
- diagnostics에 provider model을 반드시 남긴다.

### 위험 4. `/products/search` pagination이 복잡해진다

문제:

ES keyword와 vector 결과를 union하면 정확한 total count 계산이 어렵다.

해결:

- 초기에는 ES pagination을 유지하고 vector는 부족분 보강/fallback으로 사용한다.
- full hybrid pagination은 API contract 재합의 후 진행한다.
- diagnostics에 source별 result count를 남긴다.

### 위험 5. 10만 상품에서 pgvector가 느릴 수 있다

문제:

index 없이 전체 embedding distance 계산을 하면 latency가 커질 수 있다.

해결:

- dev 기능 구현 후 10만 데이터에서 p95 측정한다.
- HNSW index를 우선 검토한다.
- HNSW가 어려우면 IVFFlat을 대안으로 둔다.

## 지금 바로 할 작업

3차 구현의 첫 작업은 코드 구현이 아니라 아래 순서다.

1. 현재 dev DB의 `search_documents` 수와 embedding coverage를 확인한다.
2. `embed_search_documents --join-docs-only --dry-run`으로 대상 수를 확인한다.
3. OpenAI key가 있는 환경에서 소량 embedding을 생성해 vector score가 실제로 변하는지 확인한다.
4. `pgvector_product_search.py` 서비스를 추가한다.
5. candidate pool에 `pgvector_search` source를 연결한다.
6. 추천 API에서 ES on/off, vector on/off 조합을 검증한다.
7. `/products/search`에는 vector fill을 붙인다.
8. 테스트와 Docker 검증 후 10만 데이터 성능 검증으로 넘어간다.

## 최종 판단

지금 프로젝트에 가장 합리적인 3차 방향은 `pgvector 우선 + Elasticsearch keyword 유지 + DB fallback 유지`다.

이 방식이 좋은 이유:

- 이미 존재하는 embedding schema와 CLI를 활용한다.
- 팀 문서의 P2/P3 방향과 충돌하지 않는다.
- Docker 운영 방식과 충돌하지 않는다.
- Elasticsearch가 없는 backend-only 실행을 계속 보장한다.
- 3차 vector search 고도화를 작은 단계로 쪼개 검증할 수 있다.

따라서 다음 구현은 `pgvector_product_search`를 추가하고 candidate pool에 `pgvector_search` source를 붙이는 순서로 진행하는 것이 맞다.
