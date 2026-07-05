# Embedding Plan

작성일: 2026-07-05
담당: R3 백엔드, R4 AI 추천/검색/에이전트, R5 데이터, R6 인프라/로그
상태: #294 합의용 초안

## 목적

10만 상품 검색/추천을 위해 어떤 문서를 임베딩하고, 어떤 모델과 저장소를 쓰며, 어떤 배치/재임베딩 정책으로 운영할지 결정한다.

이번 문서는 구현 PR이 아니다. 모델 선택, pgvector 차원, API 비용, 배치 주기, 재임베딩 정책은 되돌리기 어려운 결정이므로 먼저 문서로 합의한다.

## 현재 코드와 데이터 기준

### 데이터 실측

2026-07-05 현재 repo CSV 기준:

| 파일 | 행수 | 구조 |
|---|---:|---|
| `data/products.csv` | 24,585 | 상품 원천 |
| `data/vector_docs.csv` | 24,585 | 상품별 검색/임베딩 원문 1개 |
| `data/product_ingredients.csv` | 746,124 | 상품-성분 연결 |
| `data/ingredients.csv` | 33,838 | 성분 마스터. pending placeholder 포함 |

`vector_docs.csv` 분포:

| 항목 | 값 |
|---|---:|
| `source_type=product` | 24,585 |
| 고유 `source_id` | 24,585 |
| 텍스트 길이 min | 56 chars |
| 텍스트 길이 median | 346 chars |
| 텍스트 길이 mean | 322.8 chars |
| 텍스트 길이 p95 | 475 chars |
| 텍스트 길이 max | 1,146 chars |
| 총 문자 수 | 7,935,900 chars |

즉 현재 CSV 레벨에서는 상품 1개당 vector doc 1개가 맞다.

### 현재 임베딩 코드

현재 backend에는 이미 임베딩 CLI가 있다.

| 파일 | 역할 |
|---|---|
| `apps/backend/app/cli/embed_search_documents.py` | `search_documents`를 읽어 embedding 생성/저장 |
| `apps/backend/app/services/embeddings.py` | OpenAI provider와 local hash provider |
| `apps/backend/app/db/models/search.py` | `search_documents` ORM 모델 |
| `apps/backend/migrations/versions/20260629_0002_prepare_search_embeddings.py` | `search_documents.embedding`을 pgvector로 전환 |

현재 동작:

1. `search_documents`에서 embedding 대상 문서를 읽는다.
2. `OPENAI_API_KEY`가 있으면 OpenAI embedding provider를 쓴다.
3. API key가 없으면 `local-hash-v1` provider를 쓴다.
4. `embedding`, `embedding_model`, `embedding_dimensions`, `embedding_updated_at`을 저장한다.
5. `force=false`이면 embedding이 없거나 모델/차원이 다른 문서만 다시 임베딩한다.

현재 기본 설정:

| 설정 | 기본값 |
|---|---|
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | `1536` |
| `HYBRID_KEYWORD_WEIGHT` | `0.5` |
| `HYBRID_VECTOR_WEIGHT` | `0.5` |

중요: 현재 DB 타입은 `EmbeddingVector(1536)`이고 PostgreSQL에서는 `vector(1536)`이다. 1024차원, 384차원 모델을 쓰려면 migration 또는 별도 컬럼이 필요하다.

따라서 이 문서의 추천안은 신규 도입이 아니라 repo에 이미 존재하는 기반(migration `20260629_0002`, `vector(1536)`, embedding CLI, 기본 모델 `text-embedding-3-small`)을 P2 기준으로 공식 승인하는 성격이다. 추천안을 채택하면 시작 migration은 0건이다.

## vector_docs와 search_documents의 관계

두 문서는 역할이 다르다.

| 구분 | `vector_docs.csv` | `search_documents` |
|---|---|---|
| 위치 | CSV 원천 데이터 | DB 검색 문서 테이블 |
| 현재 행수 | 24,585 | seed/build 후 DB에 생성 |
| 생성 방식 | 데이터 CSV | seed 또는 `build_search_index_documents` CLI |
| 내용 | 상품명/브랜드/카테고리/주요 전성분 중심 | 상품/브랜드/카테고리/피부 적합도/성분/효능/risk/함량 단서 조인 |
| pending 제외 | CSV 자체에는 pending 성분명이 들어갈 수 있음 | builder에서 pending 성분 제외 가능 |
| 추천 | 보조 원천 또는 fallback seed | P2 임베딩 대상 추천 |

## 임베딩 대상 결정

### 선택지

| 선택지 | 장점 | 단점 |
|---|---|---|
| `vector_docs.csv` 원문 임베딩 | 구조 단순, CSV만으로 재현 가능, 상품별 1개 보장 | pending 제외/성분 효능/risk/함량 전략이 약함 |
| `search_documents` 조인 문서 임베딩 | 현재 검색 scoring이 실제로 읽는 문서, 성분/효능/risk/함량 단서 포함, pending 제외 정책 반영 가능 | DB build 선행 필요, 문서 변경 시 embedding 무효화 필요 |

### 추천안

P2 임베딩 대상은 `search_documents` 조인 문서로 한다.

이유:

- 현재 `match_product_search_documents()`가 실제로 읽는 대상이 `search_documents`다.
- #295 build job이 상품/성분/효능/risk/함량 단서를 조인해 더 풍부한 문서를 만든다.
- #345 기준으로 `ing_pending_*`, `foreign_pending_*` 성분을 검색 문서에서 제외하는 방침을 반영할 수 있다.
- `vector_docs.csv`는 상품별 1개 원천 snapshot으로 남기되, P2 실제 검색 품질 기준은 DB의 `search_documents`에 맞춘다.

## 모델 후보

가격과 스펙은 2026-07-05 확인 기준이며, 실제 과금 전 각 provider dashboard에서 재확인한다.

참고:

- OpenAI `text-embedding-3-small`: 공식 모델 문서 기준 1536차원, $0.02 / 1M tokens. [OpenAI model docs](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- OpenAI embedding guide: `text-embedding-3-small` 기본 1536차원, `text-embedding-3-large` 기본 3072차원. [OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)
- OpenAI Batch API: synchronous API 대비 50% 비용 할인, 24시간 내 비동기 완료, embeddings endpoint 지원. [OpenAI Batch API guide](https://developers.openai.com/api/docs/guides/batch)
- Voyage pricing: `voyage-4-lite` $0.02 / 1M tokens, `voyage-4` $0.06 / 1M tokens, `voyage-multilingual-2` $0.12 / 1M tokens. [Voyage pricing](https://docs.voyageai.com/docs/pricing)
- Voyage embedding docs: `voyage-3.5`, `voyage-3.5-lite` 등은 output dimension 2048/1024/512/256 지원. [Voyage embeddings](https://docs.voyageai.com/docs/embeddings)
- BGE-M3: multilingual, 최대 8192 tokens, dense embedding 1024차원 계열. [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- Multilingual E5 large: embedding size 1024. [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)
- paraphrase multilingual MiniLM: 384차원, 50+ languages. [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)

### API형 후보

| 후보 | 한국어/다국어 | 차원 | 현 DB `vector(1536)` 호환 | 비용 | P2 판단 |
|---|---|---:|---|---:|---|
| OpenAI `text-embedding-3-small` | 다국어 benchmark 개선, 한국어 포함 실사용 가능 | 1536 | 호환 | $0.02 / 1M tokens | 1순위 |
| OpenAI `text-embedding-3-large` | small보다 품질 우위 | 3072 기본 | 미호환. 1536 축소 사용 또는 migration 필요 | $0.13 / 1M tokens | 품질 비교용 |
| Voyage `voyage-multilingual-2` | multilingual 특화 | 1024 | 미호환. migration 필요 | $0.12 / 1M tokens | P3 비교 후보 |
| Voyage `voyage-4-lite` | 저비용 general embedding | 1024 기본 계열 | 미호환. migration 필요 | $0.02 / 1M tokens | P3 비교 후보 |

### 로컬 오픈소스형 후보

| 후보 | 한국어/다국어 | 차원 | 현 DB `vector(1536)` 호환 | 비용 | P2 판단 |
|---|---|---:|---|---:|---|
| `BAAI/bge-m3` | 100+ languages | 1024 | 미호환. migration 필요 | API 비용 없음, 인스턴스 비용 발생 | 품질 후보, P3 권장 |
| `intfloat/multilingual-e5-large` | multilingual | 1024 | 미호환. migration 필요 | API 비용 없음, 인스턴스 비용 발생 | 품질 후보, P3 권장 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 50+ languages | 384 | 미호환. migration 필요 | API 비용 없음, 낮은 인스턴스 비용 | dev/빠른 실험용 |
| 현재 `local-hash-v1` | 언어 독립 token hash | 1536 | 호환 | 무료 | CI/dev fallback 전용. semantic 품질 검증용 아님 |

## 비용 추산

정확한 비용은 tokenizer로 실제 token 수를 계산해야 한다. 현재 repo에는 token dry-run이 없으므로 아래는 산식 기준의 예산 판단용이다.

문서 수 기준:

| 규모 | 문서 수 |
|---|---:|
| 현재 full | 24,585 |
| 목표 100k | 100,000 |

토큰 시나리오:

| 평균 tokens/doc | 24,585 docs | 100,000 docs |
|---:|---:|---:|
| 300 | 7.38M tokens | 30M tokens |
| 500 | 12.29M tokens | 50M tokens |
| 1,000 | 24.59M tokens | 100M tokens |

API 비용:

| 모델 | 단가 | 24,585 docs @500 tokens | 100k docs @500 tokens | 100k docs @1,000 tokens |
|---|---:|---:|---:|---:|
| OpenAI `text-embedding-3-small` | $0.02 / 1M | 약 $0.25 | 약 $1.00 | 약 $2.00 |
| OpenAI `text-embedding-3-large` | $0.13 / 1M | 약 $1.60 | 약 $6.50 | 약 $13.00 |
| Voyage `voyage-4-lite` | $0.02 / 1M | 약 $0.25 | 약 $1.00 | 약 $2.00 |
| Voyage `voyage-multilingual-2` | $0.12 / 1M | 약 $1.47 | 약 $6.00 | 약 $12.00 |

결론: 텍스트 임베딩 API 비용만 보면 $1,000 예산 안에서 100k 1회 임베딩은 충분히 가능하다. 더 큰 비용 리스크는 API 토큰 비용보다 다음 항목이다.

비실시간 색인 배치는 OpenAI Batch API를 사용하면 synchronous API 대비 50% 비용 할인이 가능하다. 즉 `text-embedding-3-small` 기준 실질 단가는 약 $0.01 / 1M tokens로 볼 수 있다. 다만 Batch API는 24시간 내 완료되는 비동기 처리이므로, 실시간 검색 요청 임베딩이 아니라 대량 색인 배치에만 적용한다.

- 재임베딩을 자주 반복하는 운영 실수
- 3072차원 또는 복수 모델 저장으로 인한 DB 저장/인덱스 비용 증가
- local model을 위해 별도 GPU/CPU inference 인프라를 붙이는 비용
- 모델 변경 시 전체 재임베딩 비용과 운영 복잡도

## 저장소와 검색 방식

### 현재 저장소

현재는 PostgreSQL `search_documents.embedding`에 pgvector를 저장한다.

| 항목 | 현재 상태 |
|---|---|
| 컬럼 | `search_documents.embedding` |
| 타입 | PostgreSQL `vector(1536)` |
| 메타 | `embedding_model`, `embedding_dimensions`, `embedding_updated_at` |
| 검색 | `embedding <=> query_embedding` cosine distance 기반 |
| vector index | 현재 migration에는 embedding index 없음 |

### 추천안

P2는 PostgreSQL + pgvector를 유지한다.

| 선택 | 판단 |
|---|---|
| pgvector | P2 10만 규모에 우선 적용 |
| Elasticsearch vector | P3 이후 인프라 로드맵과 함께 검토 |
| 외부 vector DB | P2 범위 초과 |

### pgvector index

모델을 `text-embedding-3-small` 1536차원으로 고정한다면, P2 구현 시 HNSW index를 우선 검토한다.

예상 migration 초안:

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_documents_embedding_hnsw
ON search_documents
USING hnsw (embedding vector_cosine_ops)
WHERE document_type = 'product' AND embedding IS NOT NULL;
```

확인 필요:

- dev Postgres/pgvector 버전이 HNSW를 지원하는지
- index build 시간과 메모리
- 100k 기준 p95 latency
- HNSW가 어렵다면 IVFFlat 대안
- `CREATE INDEX CONCURRENTLY`는 transaction 내부에서 실행할 수 없으므로 Alembic 적용 시 autocommit block이 필요한지 확인

## 배치 파이프라인

### 현재 CLI

현재 CLI:

```bash
python -m app.cli.embed_search_documents
```

옵션:

| 옵션 | 의미 |
|---|---|
| `--limit` | 최대 대상 문서 수 |
| `--batch-size` | 기본 32 |
| `--force` | 기존 embedding이 있어도 재임베딩 |
| `--dry-run` | 대상 수만 확인하고 rollback |

현재 부족한 점:

| 항목 | 현재 상태 |
|---|---|
| retry | 없음 |
| rate limit backoff | 없음 |
| 실패 문서 기록 | 없음 |
| 비용 추산 | 없음 |
| duration 기록 | 없음 |
| content hash | 없음 |

### P2 배치 순서 추천

1. small DB 1,000개에서 dry-run
2. small DB 1,000개 실제 임베딩
3. full DB 24,585개 dry-run
4. full DB 24,585개 실제 임베딩
5. search/recommendation latency 측정
6. 100k 데이터 도착 후 같은 순서 반복

환경 구분은 README와 dev mode 문서를 따른다.

| 모드 | 용도 | DB / 데이터 기준 |
|---|---|---|
| small | 1,000개 개발용 | `mwobareullae_small` + `/data/dev-small` |
| full | 전체 데이터 성능 확인용 | `mwobareullae` + `/data` |

주의: 문서에는 실제 접속 문자열이나 비밀번호가 포함된 `DATABASE_URL`을 기록하지 않는다.

서버 배치에서는 `OPENAI_API_KEY`가 없으면 `local-hash-v1`로 조용히 대체하지 않고 실패 처리한다. `local-hash-v1`은 로컬 개발과 CI fallback 전용이며, semantic search 품질 검증 기준으로 쓰지 않는다.

### 재임베딩 정책

검색 문서 rebuild는 24,585개 기준 약 11.7초로 싸다. 반면 embedding은 외부 API 비용과 rate limit이 있으므로 변경분만 재임베딩해야 한다.

현재 코드도 부분적으로 이 정책을 따른다.

- `build_search_index_documents`에서 문서 내용이 바뀌면 embedding을 `NULL`로 비운다.
- `embed_search_documents`는 embedding이 없거나 모델/차원이 다른 문서만 다시 임베딩한다.

P2 추천안:

| 상황 | 정책 |
|---|---|
| 문서 내용 변경 | 해당 문서 embedding null 처리 후 재임베딩 |
| 모델 변경 | 전체 재임베딩 |
| 차원 변경 | migration + 전체 재임베딩 |
| 가격/재고 변경 | 검색 문서 내용에 없으므로 재임베딩 불필요 |
| 데모 전 | dry-run으로 대상 수 확인 후 필요한 문서만 임베딩 |

full rebuild 후 내용이 바뀌지 않은 문서의 embedding이 보존되는지는 회귀 테스트로 보장한다. 이 테스트가 없으면 rebuild 때마다 전체 embedding이 `NULL` 처리되어 API 비용과 rate limit이 불필요하게 증가할 수 있다.

P3 보강:

- `content_hash` 컬럼 추가
- batch run id 추가
- 실패 문서 재시도 큐
- 비용 추산 로그

## Diagnostics

### 배치 결과 기록

P2는 CLI 출력과 배포 로그에 아래 값을 남긴다.

| 필드 | 의미 |
|---|---|
| `embedding_run_id` | 배치 실행 ID |
| `source` | `small`, `full`, `100k` |
| `model` | 임베딩 모델 |
| `dimensions` | 차원 |
| `target_document_count` | 대상 문서 수 |
| `embedded_count` | 실제 임베딩 수 |
| `skipped_count` | 기존 embedding 유지 수 |
| `failed_count` | 실패 수 |
| `estimated_tokens` | 사전 추산 token |
| `actual_tokens` | provider 응답 또는 tokenizer 기준 |
| `estimated_cost_usd` | 예상 비용 |
| `duration_ms` | 소요 시간 |
| `failure_reason` | 실패 원인 |

### 추천 요청 진단

F-180 `candidate_pool_diagnostics`와 이어서 `recommendation_runs.request_context`에 vector 사용 여부를 남긴다.

```json
{
  "vector_search_diagnostics": {
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": 1536,
    "query_embedded": true,
    "document_embedding_coverage": 0.98,
    "vector_candidate_count": 120,
    "duration_ms": 42,
    "fallback_reason": null
  }
}
```

## 추천안

P2 추천안:

1. 임베딩 대상은 `search_documents` 조인 문서로 한다.
2. 모델은 `text-embedding-3-small` 1536차원으로 시작한다.
3. 저장소는 기존 PostgreSQL pgvector `vector(1536)`를 유지한다.
4. `local-hash-v1`은 dev/CI fallback으로만 사용하고 품질 지표로 보지 않는다.
5. `build_search_index_documents` 후 embedding null 문서만 재임베딩한다.
6. small 1,000개 → full 24,585개 → 100k 순서로 배치 검증한다.
7. BGE-M3, multilingual-E5, Voyage 계열은 P3 품질 비교 후보로 남긴다.

## AGENTS 확인 질문

### 질문 1. 모델 선택

- 추천안: P2는 OpenAI `text-embedding-3-small` 1536차원으로 간다.
- 대안: `text-embedding-3-large`를 1536차원 축소로 쓴다 / Voyage multilingual 계열로 간다 / 로컬 BGE-M3를 띄운다.
- 왜 중요한지: 모델과 차원이 바뀌면 전체 재임베딩과 pgvector schema/migration이 필요하다.
- 선택 후 영향: R4는 배치 구현, R6는 비용/환경변수/운영 로그, R3는 DB migration 여부를 확정한다.

### 질문 2. 저장소와 index

- 추천안: P2는 기존 PostgreSQL pgvector를 유지하고, `vector(1536)` 기준 HNSW index를 검토한다.
- 대안: IVFFlat 사용 / Elasticsearch vector search로 미룸 / 외부 vector DB 도입.
- 왜 중요한지: index 방식은 성능과 migration, dev 서버 메모리에 직접 영향을 준다.
- 선택 후 영향: R3/R6가 migration과 운영 리소스를 확인해야 R4가 vector search 구현을 진행할 수 있다.

### 질문 3. 재임베딩 정책

- 추천안: 문서 rebuild는 full rebuild, embedding은 변경 문서만 재임베딩한다.
- 대안: 매번 전체 재임베딩 / content hash 컬럼을 P2부터 추가 / embedding은 P3로 미룸.
- 왜 중요한지: 문서 rebuild는 11.7초로 싸지만 embedding은 API 비용과 rate limit이 있다.
- 선택 후 영향: R5 데이터 변경 후 rebuild/reembed 절차, R6 배치 운영, R4 검색 품질 검증 방식이 정해진다.

## PR 역할별 영향 범위 초안

- 현옥 PM/UX: 직접 화면 변경은 없습니다. P2 발표에서 "10만 상품 semantic search를 어떤 모델/비용/운영 기준으로 방어하는가" 설명 근거로 사용할 수 있습니다.
- 지현 프론트엔드: 프론트 코드와 API 응답 구조 변경은 없습니다. 검색 결과 품질 개선은 추후 API 내부 변경으로 반영됩니다.
- 원우 백엔드: pgvector 차원, HNSW/IVFFlat index, embedding metadata/diagnostics 저장 위치 확인이 필요합니다.
- 규태 AI 추천/검색/에이전트: 본인 작업입니다. `search_documents` 기준 임베딩, `text-embedding-3-small` 1536차원, 변경분 재임베딩 정책을 추천안으로 둡니다.
- 세민 데이터: `vector_docs.csv`는 상품별 1개 원천 snapshot으로 유지하고, 실제 P2 embedding 대상은 pending 제외가 반영된 `search_documents`로 제안합니다. 성분/효능/risk 매핑 변경 후 rebuild/reembed 절차가 필요합니다.
- 지운 인프라/로그: API 비용, rate limit, batch 실행 로그, dev small/full 환경 분리, pgvector index 메모리/성능 확인이 필요합니다.

## 다음 액션

1. 원우/R6에게 모델/저장소/reembedding 질문 3개 답변 요청
2. small 1,000개 DB에서 embedding dry-run 대상 수 확인
3. full 24,585개 DB에서 embedding dry-run 대상 수 확인
4. full rebuild 후 미변경 문서의 embedding 보존 회귀 테스트 추가
5. 서버 배치에서 `OPENAI_API_KEY` 부재 시 실패 처리하도록 CLI/provider 정책 확인
6. 선택 모델 기준으로 batch retry/cost/duration 로그 보강 PR 작성
7. pgvector index migration 여부 결정 후 별도 PR 진행
