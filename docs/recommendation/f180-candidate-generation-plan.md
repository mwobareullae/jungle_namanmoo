# F-180 대량 candidate generation 설계

## 목적

`F-180 대량 candidate generation`은 10만 상품에서 추천 요청마다 전체 상품을 모두 점수화하지 않기 위한 R4 추천/검색 쪽 선행 작업이다.

현재 추천 파이프라인은 `list_product_candidates()`가 기본 필터 후 `Product.id` 순서로 후보를 가져오고, 그 후보에 대해 검색 매칭과 성분 점수를 계산한다. 2천 개 수준에서는 동작하지만, 10만 상품에서는 전체 scan 또는 단순 id limit으로는 추천 품질과 성능을 동시에 보장하기 어렵다.

목표는 아래 흐름이다.

```text
10만 상품 전체
→ hard filter로 판매 가능 후보만 남김
→ 검색/효능/성분/프로필/인기 신호별 retrieval 후보를 fanout
→ source별 후보를 합치고 dedupe
→ 500~2,000개 candidate pool만 feature hydrate
→ 기존 scoring.py로 rerank
→ recommendation_id 기준으로 결과 저장/cache
```

## 범위

### R4가 책임지는 것

- 후보군 생성 정책
- retrieval source별 우선순위와 cap
- 성분/효능 기반 후보 생성 기준
- 검색/벡터/키워드 후보와 성분 후보를 합치는 방식
- candidate pool 크기와 tie-breaker
- `score_candidates()`에 넘기기 전 후보 품질 보장

### R4가 직접 책임지지 않는 것

- DB migration 작성
- 주문/장바구니/결제 mutation
- 프론트 화면 구현
- 이벤트 taxonomy 최종 소유
- Elasticsearch/Redis 운영 설정

단, 위 항목에 필요한 계약은 R4가 원우/R6와 합의해야 한다.

## 현재 코드 기준 문제

현재 추천 후보 로딩은 `apps/backend/app/services/product_candidates.py`의 `list_product_candidates()`가 담당한다.

현재 장점:

- 상품 활성화 여부, 브랜드 활성화, 카테고리 활성화 필터가 있다.
- 가격 조건, 브랜드 조건, 카테고리 조건을 적용한다.
- 추천 파이프라인에서 `candidate_pool_limit`으로 후보 수를 제한한다.

현재 한계:

- 기본 정렬이 `Product.id.asc()`라 추천 의도와 무관한 앞쪽 상품이 먼저 들어올 수 있다.
- 관심 효능축, 성분 근거, 검색어, 피부 프로필을 후보 생성 단계에서 쓰지 않는다.
- 검색/벡터 매칭은 후보를 가져온 뒤에만 적용된다.
- 10만 상품에서는 후보 생성 전에 관련 상품을 줄이지 않으면 `score_candidates()` 단계의 join 비용이 커진다.

따라서 `list_product_candidates()`는 hard filter 역할로 남기고, 그 위에 `generate_candidate_pool()` 계층을 추가하는 방향이 맞다.

## 후보 생성 단계

### 0. 추천 의도 정규화

입력:

- `concern_text`
- `skin_type`
- `sensitivity`
- `avoid_ingredients`
- 가격/브랜드/카테고리 조건

이미 존재하는 흐름:

- `build_recommendation_intent()`
- `parse_purchase_conditions()`
- `intent.effects`
- `intent.priority_effects`
- `intent.search_terms`
- `intent.semantic_query_text`

이 단계는 유지한다.

### 1. Hard filter

10만 상품 전체에서 반드시 먼저 제거한다.

조건:

- `Product.is_active = true`
- `Brand.is_active = true`
- `ProductCategory.is_active = true`
- 가격 존재
- 요청한 카테고리 조건 충족
- 요청한 브랜드 조건 충족
- 요청한 가격 범위 충족
- `avoid_ingredients`에 걸리는 상품 제외

이 단계의 목표 후보 수:

```text
100,000 → 20,000~80,000
```

주의:

- 재고 mock 값으로 추천 후보를 제외하지 않는다.
- 실제 판매 상태/재고 정책은 원우 커머스 API 기준이 확정된 뒤 hard filter에 추가한다.

### 2. Retrieval fanout

Hard filter 결과에서 여러 source로 후보를 뽑는다. 하나의 source만 쓰면 추천이 한쪽으로 쏠리므로 fanout 후 합친다.

| Source | 목적 | 예시 cap | 소유/의존 |
|---|---:|---:|---|
| `keyword_search` | 상품명/브랜드/문서 키워드가 고민과 맞는 후보 | 400 | R4/R6 |
| `vector_search` | 의미적으로 비슷한 상품 후보 | 400 | R4/R6 |
| `effect_ingredient` | 원하는 효능축 성분을 가진 후보 | 800 | R4/R5 |
| `functional_claim` | 미백/주름개선 등 기능성 claim 후보 | 300 | R4/R5 |
| `skin_profile_fit` | 피부 타입/민감도 적합 후보 | 300 | R4/R5 |
| `market_popular` | 리뷰/평점/판매/최근 행동 기반 후보 | 300 | R4/R5/R6 |
| `fallback_quality` | 데이터 완성도/가격/이미지 기준 fallback | 200 | R4 |

Source별 cap은 초기값이며 10만 데이터 성능 측정 후 조정한다.

P2 적용 기준:

- `effect_ingredient`, `keyword_search`, `functional_claim`, `skin_profile_fit`, `market_popular`, `fallback_quality`는 P2에서 바로 적용 가능한 source로 본다.
- `vector_search`는 search document embedding과 pgvector/Elasticsearch 인덱스 준비 상태에 따라 켠다.
- vector 인프라가 P2 일정 안에 안정화되지 않으면 `vector_search`는 P3 확장 source로 남기고, P2에서는 `keyword_search`와 `effect_ingredient` 중심으로 후보를 만든다.

초기 cap 근거:

- `effect_ingredient`는 현재 서비스의 핵심 차별점인 성분·효능 근거와 직접 연결되므로 가장 큰 cap을 둔다.
- `keyword_search`와 `vector_search`는 사용자가 직접 입력한 고민/상품명 의도를 반영하므로 성분 source 다음으로 크게 둔다.
- `functional_claim`, `skin_profile_fit`, `market_popular`는 중요한 보조 source지만 단독으로 추천 이유를 지배하면 섹션/상품 쏠림이 생길 수 있어 중간 cap을 둔다.
- `fallback_quality`는 후보 부족 시 안전망이므로 낮은 cap을 둔다.

이 숫자는 정책값이 아니라 10만 seeded DB 성능 측정 전의 1차 시작값이다. 실제 분포를 본 뒤 source별 recall, latency, 최종 클릭/장바구니 전환을 기준으로 조정한다.

`effect_ingredient` cap 800은 성분 근거 후보의 recall을 확보하기 위한 시작값이다. 다만 특정 범용 성분이 후보 pool을 지배하면 cold-start에서 겪은 성분 쏠림이 재발할 수 있으므로, source 내부에서는 아래 보정을 둔다.

- 효능축별 후보 cap을 둔다.
- 같은 canonical ingredient만으로 과다 노출되는 상품은 source rank에서 낮춘다.
- 최종 merge에서는 `multi_source_bonus`가 있는 상품을 우선해 단일 범용 성분 후보가 pool을 독점하지 않게 한다.

### 3. Candidate merge/dedupe

각 source에서 나온 후보를 합친다.

원칙:

- `product_id` 기준 dedupe
- source별 rank와 source weight를 보존
- 같은 source 안에서는 rank가 낮을수록 우선
- 여러 source에 걸린 상품은 가산
- 최종 candidate pool은 500~2,000개로 제한

초기 source weight:

| Source | weight |
|---|---:|
| `effect_ingredient` | 1.00 |
| `keyword_search` | 0.90 |
| `vector_search` | 0.85 |
| `functional_claim` | 0.80 |
| `skin_profile_fit` | 0.70 |
| `market_popular` | 0.60 |
| `fallback_quality` | 0.30 |

merge pre-score:

```text
candidate_pre_score =
  Σ(source_weight * source_rank_score)
  + exact_priority_effect_bonus
  + multi_source_bonus
  - avoid_or_risk_prefilter_penalty
```

`candidate_pre_score`는 최종 추천 점수가 아니다. 비싼 feature join을 하기 전에 후보를 줄이는 데만 쓴다.

초기 `source_rank_score`는 source 안 순위를 0~1 범위로 정규화한 값으로 둔다.

```text
source_rank_score = 1 - ((source_rank - 1) / max(source_count - 1, 1))
```

즉 source 안 1위는 1.0, 마지막 후보는 0.0에 가까워진다. 이 값은 candidate pool truncation에만 쓰며, `scoring.py`의 `raw_score`에는 직접 더하지 않는다. 최종 순위는 기존 `score_candidates()` 결과가 결정한다.

결정론적 tie-breaker:

```text
candidate_pre_score desc
multi_source_count desc
best_source_weight desc
best_source_rank asc
effect_ingredient_rank asc nulls last
keyword_search_rank asc nulls last
vector_search_rank asc nulls last
lowest_price asc nulls last
product_id asc
```

동일한 입력 데이터와 동일한 알고리즘 버전이면 같은 candidate pool이 나와야 한다. 동점 후보의 순서가 실행마다 바뀌면 recommendation_id별 결과 비교와 성능 회귀 검증이 어려워지므로, merge/dedupe 단계에서도 tie-breaker를 고정한다.

### 4. Feature hydration

선택된 candidate pool에 대해서만 상세 feature를 가져온다.

필요 feature:

- product/brand/category/price
- product ingredients
- ingredient effects
- ingredient evidence
- ingredient effect ranges
- concentration values
- functional claim
- risk flags
- product skin profile
- search match score
- market signal score

이 단계부터 기존 `score_candidates()`를 그대로 재사용한다.

함량 coverage 레이어와의 관계:

- `concentration_fit_score`는 F-180 후보 생성 source가 아니라 rerank feature다.
- `concentration_coverage_estimates.csv`의 `exact`, `range`, `regulatory_anchor`, `legal_upper_bound`처럼 공개/점수화에 쓸 수 있는 근거는 `score_candidates()`의 함량 적합도 계산에 반영한다.
- `marker_upper_bound`, `prior_estimate`처럼 약한 추정은 후보 생성 hard filter나 강한 가산에 쓰지 않는다.
- `functional_claim` source는 기능성 claim 후보를 빠르게 끌어오기 위한 retrieval source이고, 함량 coverage는 해당 후보가 rerank 단계에서 얼마나 신뢰 가능한지 보정하는 별도 feature다.
- 따라서 F-180은 함량 전략을 대체하지 않고, 함량 전략이 적용될 후보 pool을 줄이는 앞단 역할을 한다.

### 5. Rerank

기존 `apps/backend/app/services/scoring.py`의 점수식을 사용한다.

현재 점수 요소:

```text
ingredient_effect_score
ingredient_evidence_score
skin_profile_score
concentration_fit_score
functional_claim_score
search_match_score
price_score
risk_penalty
```

F-180은 이 점수식을 대체하지 않는다. F-180은 점수식을 먹일 후보를 빠르고 품질 좋게 만드는 작업이다.

`candidate_pre_score`는 `raw_score` 공식에 섞지 않는다. 필요한 경우 API 응답이 아니라 diagnostics/debug metadata에만 남긴다. 만약 나중에 pre-score를 최종 점수에 반영하려면 추천 scoring 기준 변경에 해당하므로 원우/R4/PM 합의를 먼저 거친다.

### 6. 저장/cache

현재 저장 흐름:

- `recommendation_runs`
- `search_candidates`
- `recommendation_results`
- `recommendation_score_evidence`

F-180에서는 `recommendation_id` 기준으로 다음을 추적할 수 있어야 한다.

- 전체 hard filter 후 후보 수
- source별 retrieval 후보 수
- dedupe 후 후보 수
- rerank 대상 후보 수
- 최종 결과 수
- fallback 사용 여부

DB 컬럼을 바로 추가하기 전에는 `score_breakdown` 또는 로그 metadata에 요약을 남기는 방식으로 시작할 수 있다. 단, event taxonomy와 영구 저장 구조는 R6/원우와 합의 후 변경한다.

diagnostics 연결 원칙:

- 모든 diagnostics는 `recommendation_id` 또는 내부 `recommendation_run_id`에 연결되어야 한다.
- 최소 저장 단위는 run 단위 summary다. product별 source 상세 로그는 비용과 개인정보 이슈가 있어 P2에서는 기본 저장하지 않는다.
- 추천 품질 리포트(F-102)와 100k 성능 검증(F-179)이 같은 run을 재현할 수 있도록 `algorithm_version`, `scoring_version`, `candidate_generation_version`을 함께 남긴다.
- event taxonomy가 확정되기 전에는 영구 테이블을 늘리지 않고, recommendation run metadata 또는 테스트 로그로 시작한다.

초기 diagnostics 예:

```json
{
  "recommendation_id": "rec_xxx",
  "candidate_generation_version": "candidate_pool_v1",
  "hard_filter_count": 48231,
  "source_counts": {
    "effect_ingredient": 800,
    "keyword_search": 276,
    "vector_search": 400,
    "functional_claim": 118,
    "skin_profile_fit": 300,
    "market_popular": 300,
    "fallback_quality": 0
  },
  "merged_count": 1542,
  "final_pool_count": 1000,
  "fallback_used": false
}
```

## 10만 기준 목표 수치

초기 목표:

| 단계 | 목표 |
|---|---:|
| hard filter | 20,000~80,000 |
| retrieval fanout 합산 | 1,500~3,000 |
| dedupe 후 candidate pool | 500~2,000 |
| rerank 후 저장 | 50 |
| API 기본 노출 | page_size 10 |

성능 목표:

| 항목 | 목표 |
|---|---:|
| 추천 API p95 | 500ms 이내 |
| 후보 생성 p95 | 250ms 이내 |
| scoring/rerank p95 | 250ms 이내 |
| full table scan | 금지 |

위 숫자는 1차 목표다. 실제 10만 seeded DB에서 측정 후 조정한다.

## 인덱스/검색 의존성

R4가 원우/R6와 확인해야 하는 인덱스 후보:

- `products(is_active, category_id, brand_id)`
- `product_prices(product_id, price)`
- `product_ingredients(ingredient_id, product_id)`
- `ingredient_effect(ingredient_id, effect_id, effect_score)`
- `search_documents(document_type, product_id)`
- `search_documents` keyword index 또는 Elasticsearch(nori)
- `search_documents.embedding` pgvector index
- `product_skin_profiles(product_id)`

Elasticsearch가 늦으면 `pg_trgm` fallback을 허용한다. 단, fallback 조건과 성능 목표를 문서에 남긴다.

## 구현 인터페이스 초안

최종 구현은 `list_product_candidates()`를 직접 키우기보다 별도 계층을 둔다.

```python
def generate_candidate_pool(
    session: Session,
    intent: RecommendationIntent,
    purchase_conditions: ParsedPurchaseConditions,
    *,
    skin_type: str,
    sensitivity: str,
    avoid_ingredients: list[str],
    target_pool_size: int = 1000,
) -> CandidatePool:
    ...
```

반환 개념:

```python
@dataclass(frozen=True)
class CandidatePool:
    candidates: list[ProductCandidate]
    diagnostics: CandidatePoolDiagnostics

@dataclass(frozen=True)
class CandidatePoolDiagnostics:
    hard_filter_count: int
    source_counts: dict[str, int]
    merged_count: int
    final_pool_count: int
    fallback_used: bool
```

이후 `recommendation_pipeline.py`는 아래처럼 바뀐다.

```text
build intent
→ generate_candidate_pool
→ match_product_search_documents
→ score_candidates
→ save_search_candidates / save_recommendation_results
```

## 구현 전 확인 질문

이 문서는 추천 후보 추출 방식 변경에 해당하므로, AGENTS 규칙상 구현 전에 아래 결정을 확인한다.

- 추천안: `list_product_candidates()`는 hard filter로 유지하고, 별도 `generate_candidate_pool()` 계층을 추가한다.
- 대안: 기존 `list_product_candidates()`에 retrieval source와 merge 로직을 계속 붙인다.
- 왜 중요한지: 후보 생성은 추천 품질과 10만 상품 성능을 동시에 좌우한다. 백엔드 쿼리, 인덱스, 로그 저장 구조와 맞물려 되돌리기 어렵다.
- 선택 후 영향: 추천 파이프라인에 candidate diagnostics가 생기고, 원우/R6와 DB index 및 run metadata 저장 기준을 합의해야 한다.

## fallback 정책

후보가 너무 적으면 아래 순서로 완화한다.

1. `priority_effects`만 보던 것을 `effects` 전체로 확장
2. category 조건이 없으면 인접 카테고리 허용
3. vector/keyword 후보 cap 확대
4. `fallback_quality` 후보 사용

단, 아래 조건은 완화하지 않는다.

- avoid ingredients
- 가격 hard filter
- 비활성 상품
- 비활성 브랜드/카테고리

## R4 다음 작업 순서

1. 이 문서를 원우/R6에게 공유해 candidate generation이 DB/API 어느 지점에 들어갈지 합의한다.
2. 현재 `list_product_candidates()` 성능과 한계를 테스트로 고정한다.
3. `CandidatePoolDiagnostics`를 먼저 도입해 후보 수를 관측한다.
4. `effect_ingredient` source부터 구현한다.
5. `keyword_search`와 `vector_search` source를 붙인다.
6. 10만 seeded DB에서 p95를 측정한다.

## 역할별 영향 범위

- 현옥 PM/UX: 추천 결과가 왜 특정 상품으로 좁혀졌는지 설명 가능한 흐름이 생긴다. 화면 문구는 “전체 상품을 전부 계산”이 아니라 “관련 후보를 좁힌 뒤 성분 근거로 비교”로 설명하는 것이 맞다.

- 지현 프론트엔드: 직접 코드 영향 없음. 다만 추천 결과가 `recommendation_id` 기준으로 저장되고 page 기반으로 내려오는 구조는 유지해야 한다.

- 원우 백엔드: `list_product_candidates()` 앞/뒤에 candidate pool 계층이 추가될 수 있다. DB query, pagination, recommendation_runs/search_candidates 저장 흐름과 맞춰야 한다.

- 규태 AI 추천/검색/에이전트: 후보 생성 source, source cap, pre-score, rerank 전 feature hydration 기준을 소유한다.

- 세민 데이터: product/ingredient/effect/search_documents 데이터 품질이 candidate generation 품질에 직접 영향을 준다. product canonical/dedup과 ingredient mapping 오류가 후보 누락/오노출로 이어진다.

- 지운 인프라/로그: 10만 성능 측정, index build, pg_trgm/pgvector/Elasticsearch fallback, candidate diagnostics 로그 기준을 함께 봐야 한다.
