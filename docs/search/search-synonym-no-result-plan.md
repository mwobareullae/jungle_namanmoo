# Search Synonym and No-result Management Plan

작성일: 2026-07-06  
담당: R4 AI 추천/검색/에이전트, R6 인프라/로그  
협업: R3 백엔드, R2 프론트엔드, R5 데이터  
상태: #285 합의용 초안

## 목적

엑셀 #42 / GitHub #285의 "검색 고도화 (동의어·무결과 관리) + 관리자 화면" 범위를 정리한다.

이번 문서는 구현 PR이 아니다. 이미 존재하는 alias/동의어 체계를 새로 만드는 문서가 아니라, 실패 검색어와 no-result를 어떤 흐름으로 관측하고 기존 alias 체계에 반영할지 정하는 문서다. 동의어, no-result 처리, 검색 ranking, 관리자 수정 권한은 되돌리기 어려운 결정과 연결되므로 먼저 기준을 합의한다.

## 현재 상태

현재 검색/추천 입력 해석은 여러 경로로 나뉘어 있다.

| 구분 | 현재 위치 | 상태 |
|---|---|---|
| 고민 동의어 | `data/tags.json` | 11개 고민 태그와 synonym을 seed |
| 성분 alias | `data/ingredient_aliases.csv` | 1,382개 alias, `ko/en/inci/typo/abbrev/synonym` 유형 |
| 성분 canonical 매핑 | `data/ingredient_canonical_mappings.csv` | source ID 또는 broad+exact name 697개를 canonical로 해석 |
| 브랜드 alias | `purchase_conditions.py` + `products.csv` | 일부 브랜드 override + 상품 CSV 브랜드명 기반 |
| 카테고리 alias | `purchase_conditions.py` | serum/toner/lotion/cream 하드코딩 |
| unmatched terms | `RecommendationResponse.unmatched_terms` | 추천 응답에 반환 |
| 검색/no-result 이벤트명 | `event.py` | `search_performed`, `search_no_result` 정의됨 |
| 검색 문서 | `search_documents` | `idx_prod_join_*` 기준으로 통일 |
| pg_trgm fallback | `docs/search-fallback-reindex-plan.md` | 계획 문서 완료, 실제 migration/구현 전 |

현재 문제는 "동의어가 전혀 없다"가 아니라, 동의어/무결과 관리 지점이 여러 파일과 코드에 흩어져 있고, 운영자가 실패 검색어를 보고 다음 조치를 결정하는 흐름이 아직 없다는 점이다.

## 이미 되어 있는 것과 새로 정할 것

이미 되어 있는 것:

- `data/tags.json`에 고민 동의어가 있다.
- `data/ingredient_aliases.csv`에 성분 alias가 있다.
- seed는 `ingredient_aliases.csv`를 DB의 `ingredient_aliases`로 적재한다.
- A군 성분 정리 스크립트는 alias 표를 사용해 raw 성분명을 canonical 성분으로 맞춘다.
- 브랜드/카테고리 alias는 `purchase_conditions.py`에서 일부 처리한다.
- 추천 응답은 `unmatched_terms`를 반환한다.

아직 없는 것:

- 실제 사용자 검색/추천 입력에서 실패한 표현을 모아보는 리포트
- no-result가 왜 났는지 구분하는 기준
- 실패 표현을 alias 후보로 정리하는 리포트
- alias 후보를 누가 확인할지에 대한 역할 기준
- 관리자 화면에서 볼 최소 리포트 범위

따라서 이번 문서의 초점은 alias 기능 생성이 아니라, 기존 alias 체계를 운영 가능한 개선 루프로 연결하는 것이다.

## P2 추천안

P2에서는 관리자 CRUD나 승인 상태 관리를 바로 열지 않고, 먼저 관측과 리포트 흐름을 만든다.

1. 검색/추천 입력이 실패하거나 약한 경우를 진단한다.
2. 실패한 입력을 `unmatched_terms`, no-result event, search diagnostics로 모은다.
3. R4가 alias 후보를 정리하고, 성분 alias는 R5가 데이터 관점으로 확인한다.
4. 확정된 alias만 CSV/JSON에 반영한다.
5. seed 또는 search index rebuild 후 품질을 재확인한다.

즉, P2에서는 "자동 관리자 수정"보다 "실패 검색어 리포트 + CSV/JSON PR 기반 수동 반영"을 우선한다.

## 동의어 관리 기준

### 고민 동의어

고민/피부 문제 표현은 `data/tags.json`을 기준으로 관리한다.

예:

| 사용자 표현 | 표준 고민 |
|---|---|
| 피지, 유분, 블랙헤드 | 모공 |
| 잡티, 기미, 색소침착 | 미백 |
| 붉은기, 화끈거림, 따가움 | 민감 |

P2에서는 `tags.json` 변경 후 seed를 다시 돌리는 방식으로 반영한다. 관리자 화면에서 바로 수정하는 것은 P3로 넘긴다.

### 성분 alias

성분 alias는 `data/ingredient_aliases.csv`를 기준으로 관리한다.

예:

| 사용자/라벨 표현 | canonical |
|---|---|
| 니아신아마이드, 비타민B3, Vitamin B3 | niacinamide |
| BHA, 살리실산 | salicylic_acid_bha |
| 시카, Cica | centella_asiatica |

P2에서는 alias 후보를 바로 자동 반영하지 않는다. 특히 부분일치 후보는 오탐 가능성이 있으므로 R5 데이터 확인 후 반영한다.

### 브랜드/카테고리 alias

브랜드와 카테고리 alias는 현재 `purchase_conditions.py`에 일부 하드코딩되어 있다.

P2에서는 다음 기준으로 유지한다.

| 구분 | P2 기준 | P3 후보 |
|---|---|---|
| 브랜드 alias | CSV 브랜드명 + 일부 override | `brand_aliases` 운영 UI |
| 카테고리 alias | serum/toner/lotion/cream 고정 | 카테고리 alias 관리 UI |

## No-result 기준

P2에서 no-result는 단순히 "상품이 0개"만 뜻하지 않는다.

| 유형 | 기준 |
|---|---|
| parser no-match | `unmatched_terms`가 있고 matched concern/effect가 없음 |
| candidate no-result | 후보 상품이 0개 |
| weak result | 결과는 있으나 상위 `search_match_score`가 낮음 |
| fallback failure | pg_trgm/vector fallback 후에도 후보가 부족함 |

P2 1차 no-result 판정은 아래 조건으로 시작한다.

- 최종 추천 상품 수가 0개
- 또는 matched concern/effect가 없고 `unmatched_terms`만 존재
- 또는 상위 검색 점수가 매우 낮아 fallback 후보가 필요한 경우

정확한 threshold는 #296 fallback 구현에서 함께 확정한다.

## Diagnostics 제안

### 추천 요청 단위

`recommendation_runs.request_context`에 아래 값을 남긴다.

```json
{
  "search_intent_diagnostics": {
    "matched_concern_count": 1,
    "expected_effect_count": 2,
    "unmatched_terms": ["속은 당기는데 겉은 번들"],
    "purchase_category_count": 0,
    "purchase_brand_count": 0,
    "join_document_count": 24585,
    "keyword_match_count": 10,
    "vector_used": true,
    "no_result_reason": null
  }
}
```

### 이벤트 단위

현재 event schema에는 `search_performed`, `search_no_result`가 이미 있다. P2에서는 새 테이블보다 event log metadata를 우선 사용한다.

추천 metadata:

| 필드 | 의미 |
|---|---|
| `query_text` | 사용자가 입력한 원문 |
| `matched_concerns` | 매칭된 고민명 |
| `expected_effects` | 매칭된 효능명 |
| `unmatched_terms` | 해석 실패 표현 |
| `result_count` | 최종 결과 수 |
| `top_search_match_score` | 상위 검색 점수 |
| `fallback_used` | fallback 사용 여부 |
| `no_result_reason` | no-result 사유 |

## 관리자 화면 범위

### P2 최소 화면

P2에서는 "수정 화면"보다 "리포트 화면"을 먼저 만든다.

| 화면 | 내용 |
|---|---|
| 검색 실패 리포트 | 검색어, 빈도, 결과 수, unmatched_terms, no_result_reason |
| alias 후보 목록 | 사용자 표현, 추천 canonical, source, confidence |
| 확인 메모 | R4/R5가 나중에 볼 수 있는 간단한 비고 |

P2에서는 관리자 화면에서 alias를 즉시 DB에 쓰지 않고, 필요한 항목만 기존 CSV/JSON PR로 반영한다.

### P3 확장

P3에서 관리자 CRUD를 열 경우 아래가 필요하다.

- alias rule DB table
- 승인 상태와 수정 이력
- 충돌 검증
- seed/CSV와 DB alias의 우선순위
- 배포 없이 hot reload할지 여부

이 결정은 DB schema와 운영 권한을 바꾸므로 별도 확인 후 진행한다.

## 구현 순서 제안

| 순서 | 작업 | PR 성격 |
|---:|---|---|
| 1 | no-result/search diagnostics 필드 추가 | backend |
| 2 | `search_performed` / `search_no_result` 이벤트 metadata 정리 | backend + infra/log |
| 3 | no-result 리포트용 집계 쿼리 또는 CLI 작성 | backend |
| 4 | alias 후보 CSV 산출 스크립트 작성 | data/ai |
| 5 | 관리자 리포트 화면 연결 | frontend/admin |
| 6 | 관리자 CRUD/승인 상태 관리 여부 결정 | P3 |

## 하지 않는 것

P2 1차에서는 아래를 하지 않는다.

- 관리자 화면에서 alias를 즉시 DB에 쓰기
- 검색 ranking weight 변경
- `pg_trgm` extension/index migration을 이 문서 PR에서 함께 구현
- Elasticsearch 전환
- `ingredient_aliases.csv` 자동 일괄 매핑

## 팀 확인 질문

### 추천안

P2에서는 검색 실패/무결과를 먼저 관측하고, alias 후보는 리포트로 모은 뒤 필요한 항목만 CSV/JSON PR로 수동 반영한다. 관리자 화면은 P2에서 리포트 중심으로 시작하고, CRUD와 accepted/rejected 같은 상태 관리는 P3로 넘긴다.

### 대안

1. P2부터 관리자 alias CRUD를 구현한다.
2. 관리자 화면 없이 CSV/JSON 수동 관리만 유지한다.
3. pg_trgm/Elasticsearch 연결 후 no-result 정책을 다시 설계한다.

### 왜 중요한지

동의어와 no-result 처리는 검색 ranking, 데이터 계약, 운영 권한, 관리자 화면과 동시에 연결된다. 자동 수정 권한을 너무 빨리 열면 잘못된 alias가 추천 품질을 망칠 수 있고, 너무 늦게 열면 실패 검색어 개선이 느려진다.

### 선택 후 영향

| 역할 | 영향 |
|---|---|
| 현옥 PM/UX | no-result 문구와 관리자 리포트에서 볼 항목을 정해야 한다. |
| 지현 프론트엔드 | P2 관리자 리포트 화면 또는 no-result 화면 연결 시 참고한다. |
| 원우 백엔드 | diagnostics 저장 위치, event metadata, no-result 집계 API 여부 확인이 필요하다. |
| 규태 AI 추천/검색/에이전트 | alias 후보 산출과 no-result 판정 기준을 구현한다. |
| 세민 데이터 | 성분 alias 후보가 생기면 pending/canonical 매핑과 충돌 여부를 확인한다. |
| 지운 인프라/로그 | `search_no_result` 이벤트 수집, 리포트 집계, 추후 관리자 로그 연결을 확인한다. |

## PR 역할별 영향 범위 초안

- 현옥 PM/UX: 검색 결과 0건/약한 검색 시 사용자 문구와 관리자 리포트 항목을 정하는 기준 문서입니다.
- 지현 프론트엔드: 이번 PR은 문서만 추가합니다. 추후 no-result 화면이나 관리자 리포트 화면을 만들 때 이 기준을 참고합니다.
- 원우 백엔드: no-result diagnostics 저장 위치, event metadata, 집계 API 여부를 확인해야 합니다. API 응답 구조는 이번 PR에서 변경하지 않습니다.
- 규태 AI 추천/검색/에이전트: 본인 작업입니다. 동의어 후보와 no-result 기준을 구현하기 전 합의 문서입니다.
- 세민 데이터: 성분 alias 후보는 자동 반영하지 않고 데이터 확인 후 CSV/JSON PR로 반영하는 기준입니다.
- 지운 인프라/로그: `search_performed`, `search_no_result` 이벤트와 관리자 리포트 집계 기준을 확인해야 합니다.
