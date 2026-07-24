# Search Fallback and Reindex Plan

작성일: 2026-07-05  
담당: R4 AI 추천/검색/에이전트, R6 인프라/로그, R3 백엔드  
상태: P2 합의용 초안

## 목적

P2 10만 상품 검색/추천에서 검색 결과가 약하거나 0건일 때의 fallback 기준과, `search_documents` 재생성 정책을 합의한다.

이번 문서는 구현 PR이 아니다. `pg_trgm` migration, 검색 ranking 변경, reindex job 운영 방식은 모두 되돌리기 어려운 결정이므로 먼저 문서로 합의한다.

## 현행 검색 경로

현재 추천 검색 매칭은 다음 흐름이다.

1. 추천 요청에서 `RecommendationIntent`를 만든다.
2. 후보 상품 목록을 만든다.
3. `match_product_search_documents()`가 후보 상품의 `search_documents`를 읽는다.
4. 고민/효능 term을 문서의 `title`, `content`, `keywords`에 부분 문자열 방식으로 매칭한다.
5. embedding이 준비되어 있으면 vector score를 추가로 섞는다.
6. `search_match_score`가 `scoring.py`의 최종 점수 요소 중 하나로 들어간다.

현재 keyword 검색은 DB 전체 검색이 아니라, 이미 만들어진 후보 상품 안에서 `search_documents`를 조회해 점수를 붙이는 방식이다. `pg_trgm` 기반 fallback은 아직 구현되어 있지 않다.

## 현행 search_documents build job

`build_search_index_documents` CLI는 `search_index_builder.py`를 통해 상품 조인 문서를 만든다.

현재 문서에 들어가는 값:

| 구분 | 포함 여부 | 내용 |
|---|---:|---|
| 상품 | 포함 | 상품명, 상품 코드, 설명, 기능성 상태/클레임/근거 |
| 브랜드 | 포함 | 브랜드명, 브랜드 코드 |
| 카테고리 | 포함 | 카테고리명, 카테고리 코드 |
| 피부 적합도 | 포함 | `product_skin_profiles` 상위 적합도와 민감도 태그 |
| 성분 | 포함 | 성분명, 영문명, 성분 코드, display name |
| 효능 | 포함 | `ingredient_effect`와 `effects` 조인 결과 |
| 함량 단서 | 포함 | 전성분 함량 텍스트와 정규화된 함량 단서 |
| risk | 포함 | risk display text와 risk type |
| 가격 | 제외 | `product_prices`는 현재 검색 문서에 들어가지 않음 |
| 재고 | 제외 | `product_inventory`는 현재 검색 문서에 들어가지 않음 |
| 이미지 | 제외 | `product_image_assets`는 현재 검색 문서에 들어가지 않음 |

현재 빌더는 `is_active=true` 상품을 id 순서로 batch scan하고, `document_code=idx_prod_join_{product_code}` 기준으로 upsert한다. 문서 내용이 바뀌면 기존 embedding은 비워 다음 embedding 재생성 대상으로 만든다.

주의: 현재 `dev` 기준 빌더는 `ing_pending_*` 성분만 제외한다. `foreign_pending_*`까지 제외하는 보강은 `fix/search-index-pending-prefixes` PR에서 진행 중이다. P2 운영 기준은 해당 PR 머지 후의 동작으로 잡는다.

## P2 fallback 사다리 제안

P2에서는 Elasticsearch를 전제로 하지 않고, Postgres 기반 fallback을 먼저 합의한다.

| 단계 | 조건 | 동작 | P2 적용 |
|---|---|---|---|
| 1. 기존 keyword/vector score | 기본 경로 | 후보 상품의 `search_documents`에서 부분 문자열 + vector score 계산 | 유지 |
| 2. 후보 cap 확대 | 최종 후보가 너무 적음 | 기존 후보 pool limit을 일시적으로 키워 재점수화 | 적용 가능 |
| 3. `pg_trgm` fallback | 검색어가 있는데 keyword/vector 결과가 0건 또는 매우 약함 | `search_documents.title`, `keywords`, 필요 시 `content`에서 similarity 검색 | 합의 후 적용 |
| 4. fallback_quality | source 후보가 계속 부족함 | 이미지/가격/데이터 완성도 기반 안전 후보 사용 | F-180 계획과 연결 |
| 5. no-result 응답 | 후보가 여전히 없음 | 추천 결과 없음 narrative와 검색어 수정 유도 | 유지 |

### pg_trgm 발동 조건 초안

`pg_trgm`은 아래 중 하나일 때만 사용한다.

| 조건 | 기준값 초안 |
|---|---:|
| 검색어 또는 자유 고민 입력이 있음 | `intent.search_terms` 또는 `concern_text` 존재 |
| 기존 검색 매칭이 없음 | `search_match_count == 0` |
| 기존 검색 매칭이 약함 | 상위 후보 `search_match_score < 0.15` |
| vector embedding이 없거나 실패함 | embedding 없음, provider error, timeout |
| 응답 지연 보호 | 기존 경로 timeout 시 fallback은 최대 1회만 |

P2에서는 fallback이 추천 결과 전체를 대체하지 않는다. fallback은 후보를 더 찾는 장치이고, 최종 순위는 기존 `scoring.py`가 결정한다.

## pg_trgm 도입 시 필요한 DB 변경

`pg_trgm`은 PostgreSQL extension과 index가 필요하다. 따라서 구현 전 원우/R6 확인이 필요하다.

추천 migration 초안:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_documents_title_trgm
ON search_documents USING gin (title gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_search_documents_keywords_trgm
ON search_documents USING gin (keywords gin_trgm_ops);
```

`content`는 길이가 길어 index 비용이 커질 수 있다. P2 첫 적용은 `title`, `keywords`를 우선하고, 성능 측정 후 `content` index를 추가 검토한다.

## Reindex 정책 추천안

### 결론

P2에서는 incremental reindex를 바로 구현하지 않고, full rebuild를 기본 정책으로 둔다.

근거:

- 최근 실데이터 dry-run 기준: 24,585개 상품 전체 build 약 11.7초
- 현재 검색 문서는 가격/재고/이미지를 포함하지 않음
- P2 단계에서는 데이터 변경 빈도보다 구현 단순성과 재현성이 더 중요함

### P2 운영 정책

| 상황 | 정책 |
|---|---|
| seed/import 후 | full rebuild 1회 |
| dev 배포 전 또는 머지 후 필요 시 | full rebuild 1회 |
| 데모/발표 전 | full rebuild 1회 |
| 정기 작업 | 일 1회 또는 데이터 대량 갱신 시 수동 실행 |
| 가격/재고만 변경 | reindex 불필요 |

P2 stale 허용 시간:

| 데이터 변경 | 허용 시간 | 이유 |
|---|---:|---|
| 상품명/브랜드/카테고리/설명 변경 | 최대 24시간 | 검색 문서에 직접 반영되는 텍스트 |
| 성분/효능/risk 매핑 변경 | 최대 24시간 | 검색 품질에 직접 영향 |
| 데모/QA 전 | 0시간 | 발표 전에는 full rebuild로 정합성 보장 |
| 가격/재고 변경 | 검색 stale 대상 아님 | 현재 검색 문서에 포함되지 않음 |

### P3 incremental reindex 설계 초안

P3에서 incremental reindex가 필요해지면 변경 source별로 product_id를 역추적한다.

| 변경 source | reindex 대상 |
|---|---|
| `products` | 해당 product_id |
| `brands` | 해당 brand_id의 모든 product_id |
| `product_categories` | 해당 category_id의 모든 product_id |
| `product_skin_profiles` | 해당 product_id |
| `product_ingredients` | 해당 product_id |
| `ingredients` | 해당 ingredient_id를 가진 모든 product_id |
| `ingredient_effect` | 해당 ingredient_id를 가진 모든 product_id |
| `effects` | 해당 effect_id와 연결된 ingredient의 모든 product_id |
| `risk_flags` | 해당 ingredient_id를 가진 모든 product_id |
| `product_prices` | 제외 |
| `product_inventory` | 제외 |
| `product_image_assets` | 제외 |

삭제/비활성화 정책은 별도 확인이 필요하다. 현행 full rebuild는 active 상품을 scan해 upsert하지만, 비활성화된 상품의 기존 `search_documents` 삭제 정책은 문서상 명확하지 않다. P2에서는 full rebuild 전후 orphan/비활성 문서 정리 검증을 추가하는 방향을 권장한다.

## Diagnostics 제안

F-180 `candidate_pool_diagnostics`와 같은 패턴으로 검색 fallback과 reindex 실행 결과를 남긴다.

### 추천 요청 단위

`recommendation_runs.request_context`에 아래 값을 기록한다.

```json
{
  "search_fallback_diagnostics": {
    "fallback_version": "search_fallback_v0",
    "fallback_used": true,
    "fallback_type": "pg_trgm",
    "trigger_reason": "zero_keyword_match",
    "keyword_match_count": 0,
    "trgm_candidate_count": 42,
    "selected_candidate_count": 20,
    "duration_ms": 38,
    "failure_reason": null
  }
}
```

### reindex 실행 단위

P2에서는 CLI 출력과 배포 로그만으로도 충분하다. P3에서 별도 테이블 또는 event log와 연결한다.

기록 후보:

| 필드 | 의미 |
|---|---|
| `reindex_mode` | `full` 또는 `incremental` |
| `target_product_count` | 대상 상품 수 |
| `scanned` | scan한 상품 수 |
| `upserted` | 새로 쓰거나 바뀐 문서 수 |
| `unchanged` | 변경 없음 문서 수 |
| `pending_ingredients_skipped` | pending 제외 성분 수 |
| `duration_ms` | 실행 시간 |
| `failure_reason` | 실패 원인 |

## 팀 확인 질문

### 추천안

P2는 `search_documents` full rebuild 정책을 기본으로 하고, `pg_trgm` fallback은 결과 0건/약한 검색/embedding 실패 시에만 제한적으로 사용한다. Incremental reindex는 트리거 설계만 문서화하고 P3로 넘긴다.

### 대안

1. P2부터 incremental reindex를 구현한다.
2. P2에서는 `pg_trgm` 없이 기존 keyword/vector만 유지한다.
3. Elasticsearch 준비를 기다린 뒤 fallback을 다시 설계한다.

### 왜 중요한지

`pg_trgm`은 extension과 index migration이 필요하고, 검색 fallback은 ranking 결과를 바꾼다. Reindex 정책도 배포/운영 주기와 연결된다. R4가 단독으로 코드부터 넣으면 R3 백엔드, R6 인프라, R5 데이터와 충돌할 수 있다.

### 선택 후 영향

| 역할 | 영향 |
|---|---|
| 현옥 PM/UX | no-result UX와 검색 실패 시 문구 기준을 정할 수 있다. |
| 지현 프론트엔드 | API 응답 구조 변경은 없지만, no-result 화면/문구가 바뀔 수 있다. |
| 원우 백엔드 | `pg_trgm` extension/index migration, fallback query 위치, recommendation diagnostics 저장 기준 확인이 필요하다. |
| 규태 AI 추천/검색/에이전트 | fallback 조건과 reindex 기준에 맞춰 검색 후보 생성/점수화를 구현한다. |
| 세민 데이터 | 성분/효능/risk 매핑 변경 후 full rebuild 필요 여부를 확인한다. |
| 지운 인프라/로그 | full rebuild 주기, 배포 로그, pg_trgm index 운영 비용, 추후 event log 연결을 확인한다. |

## PR 역할별 영향 범위 초안

- 현옥 PM/UX: 검색 결과 0건/약한 검색 시 fallback 기준과 no-result 방향을 정리한 문서입니다. 화면 문구와 발표 설명에서 "검색이 안 될 때 어떻게 방어하는가" 근거로 쓸 수 있습니다.
- 지현 프론트엔드: 프론트 코드와 API 응답 구조는 변경하지 않습니다. 다만 no-result 화면/문구를 설계할 때 fallback 정책을 참고하면 됩니다.
- 원우 백엔드: `pg_trgm` extension/index migration, fallback query 위치, `recommendation_runs.request_context` diagnostics 저장 기준 확인이 필요합니다.
- 규태 AI 추천/검색/에이전트: 본인 작업입니다. P2는 full rebuild + 제한적 pg_trgm fallback, incremental reindex는 P3 이월 기준으로 다음 구현을 진행합니다.
- 세민 데이터: 상품/성분/효능/risk 매핑이 바뀌면 full rebuild 대상입니다. 가격/재고/이미지는 현재 검색 문서에 포함되지 않으므로 reindex 트리거에서 제외합니다.
- 지운 인프라/로그: full rebuild 운영 주기와 배포 로그, pg_trgm index 비용, 추후 reindex diagnostics/event log 연결 기준 확인이 필요합니다.
