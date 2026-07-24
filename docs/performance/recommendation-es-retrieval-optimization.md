# 추천검색 ES Retrieval 전환 최적화 설계

작성일: 2026-07-14

> 동일 조건 재측정 수치와 요청별 분포는 [Opt1 측정 결과](results/recommendation/details/opt1-es-retrieval/README.md)에서 확인한다.

## 1. 목적

추천검색의 후보 추출 책임을 Python 전처리 파서에서 Elasticsearch 색인 기반 retrieval로 이동한다.

현재 추천검색은 사용자의 자연어 고민을 먼저 Python에서 파싱한 뒤, 브랜드/카테고리/가격 같은 구매 조건을 hard filter로 만들고 후보 상품을 조회한다. 이 구조에서 브랜드 조건 생성이 병목으로 확인됐다.

이번 작업의 목표는 단순히 병목 함수를 빠르게 만드는 것이 아니라, 검색엔진이 처리해야 할 후보 탐색 책임을 Elasticsearch로 옮기고 Python 파서는 점수 계산에 필요한 의미 구조화만 담당하도록 역할을 분리하는 것이다.

## 2. 기존 구조

현재 추천검색 흐름은 다음과 같다.

```text
사용자 고민 문장
→ build_recommendation_intent()
→ parse_concern_text()
→ parse_purchase_conditions()
   → 브랜드 alias 전수 검사
   → 카테고리/가격 조건 파싱
→ generate_candidate_pool()
   → Elasticsearch 후보 추출
   → pgvector 후보 추출
   → legacy DB 후보 추출
→ DB hydrate
→ recommendation scoring
→ 최종 추천 결과
```

핵심 문제는 `parse_purchase_conditions()`가 Elasticsearch 후보 추출보다 먼저 브랜드를 찾는다는 점이다.

8만 상품 데이터 기준으로 브랜드 alias는 약 2,657개다. 브랜드가 없는 일반 고민 문장도 매 요청마다 전체 브랜드 alias를 정규식으로 전수 검사한다.

```text
요청 1회 비용 ≈ 브랜드 alias 수 × 사용자 문장 길이 × 정규식 처리 비용
           ≈ 2,657 × query_length × regex
```

즉, 사용자가 단순히 `수분 부족하고 민감한 피부에 좋은 세럼 추천`이라고 입력해도 브랜드가 없다는 것을 확인하기 위해 모든 브랜드 alias를 끝까지 확인한다.

## 3. 병목 판단

성능 로그에서 `intent_purchase_parse_ms` 내부의 브랜드 관련 시간이 크게 나타났다.

주요 원인은 두 가지다.

- 브랜드 alias load: 요청 시점 lazy loading과 동시 요청 cache miss로 상품 CSV 기반 브랜드 목록 생성이 중복될 수 있다.
- 브랜드 match: 매 요청마다 약 2,657개 alias를 정규식으로 전수 검사한다.

이 병목은 추천 스코어링 자체의 복잡도 문제가 아니라, 후보 추출 전 단계의 책임 배치 문제다.

## 4. 개선 방향

추천검색 후보 추출을 Elasticsearch 중심으로 전환한다.

```text
사용자 고민 문장
→ lightweight intent parser
   → 고민/효능 구조화
   → 가격/부정/회피 조건 구조화
→ Elasticsearch retrieval
   → 상품명, 브랜드명, 브랜드 alias, 카테고리명, 성분/효능 텍스트 검색
   → 후보 500개 추출
→ DB hydrate
→ recommendation scoring
   → 고민/효능 기반 성분 점수
   → 피부 타입/스킨테스트
   → 리뷰
   → 행동 개인화
   → 가격
→ 최종 추천 결과
```

브랜드/카테고리/상품명 탐색은 Python hard filter가 아니라 Elasticsearch field boost로 처리한다.

예상 field boost 방향은 다음과 같다.

```text
brand_name       ^8
brand_aliases    ^8
title            ^5
category_name    ^3
keywords         ^3
content          ^1
```

실제 boost 값은 품질 테스트와 성능 테스트 후 조정한다.

## 5. 남길 파서와 줄일 파서

Python 파서를 완전히 제거하지 않는다. Elasticsearch는 검색엔진이고, 추천 점수 계산에 필요한 의미 구조화까지 자동으로 책임지지는 않는다.

남길 책임:

- 고민 태그 추출: `수분 부족`, `민감`, `잡티`, `주름` 등
- 효능 추론: 보습, 진정, 미백, 탄력 등 scoring용 `effect_id`
- 우선 효능: 사용자가 특히 강조한 효능
- 제외 고민/부정 표현: `말고`, `제외`, `없는`, `빼고`
- 가격 범위: `2만원 이하`, `3만원대`, `저렴한`
- 회피 성분: 향료, 알코올 등 명시 회피 조건

줄이거나 제거할 책임:

- 브랜드 alias 전체 전수 검사
- 카테고리 alias 전체 전수 검사
- Elasticsearch가 후보 추출에서 처리할 수 있는 단순 텍스트 매칭

정리하면 다음과 같다.

```text
ES가 할 일:
브랜드/상품명/카테고리/성분/효능 텍스트 기반 후보 추출

Python parser가 할 일:
추천 점수 계산과 비즈니스 조건에 필요한 최소 구조화
```

## 6. 하드필터 정책

브랜드 hard filter는 기본 경로에서 제거한다.

다만 다음 조건은 별도 정책으로 남길 수 있다.

- 명시적 제외: `토리든 말고`, `라운드랩 제외`
- 가격 범위: `2만원 이하`
- 회피 성분: `향료 없는`
- 재고/구매 가능 여부: 상품 판매 가능 조건

브랜드 명시 검색은 우선 hard filter가 아니라 strong signal로 처리한다.

예:

```text
토리든 수분 세럼 추천
```

기존:

```text
Python에서 토리든 alias 탐색
→ brand_code hard filter 생성
→ 토리든 상품만 후보 조회
```

개선:

```text
Elasticsearch가 brand_name/brand_aliases/title/content를 함께 검색
→ 토리든 필드 매칭 상품이 높은 점수로 후보에 포함
→ 후보 500개 안에서 추천 스코어링
```

이 방식은 브랜드를 반드시 100% 제한하지 않기 때문에, 브랜드 명시 쿼리 품질 테스트가 필수다.

## 7. 구현 계획

### 1단계: 품질 기준 고정

브랜드 hard filter 제거 전에 추천 결과 품질 기준을 테스트로 고정한다.

필수 케이스:

- `토리든 수분 세럼 추천`
- `마녀공장 토너 추천`
- `아누아 어성초 진정 제품`
- `수분 부족 민감 피부 세럼 추천`
- `토리든 말고 수분 세럼 추천`
- `2만원 이하 진정 크림 추천`

검증 관점:

- 브랜드 명시 쿼리에서 해당 브랜드가 상위권에 충분히 노출되는가
- 브랜드가 없는 고민 쿼리에서 특정 브랜드가 과도하게 편향되지 않는가
- 부정 표현과 가격 조건은 유지되는가
- 후보 500개 확보율이 유지되는가

### 2단계: ES 색인 필드 확인

추천검색용 Elasticsearch 문서에 다음 필드가 있는지 확인한다.

```text
product_db_id
product_id
title
brand_code
brand_name
brand_aliases
category_code
category_name
keywords
content
lowest_price
```

`brand_aliases`가 없거나 부족하면 색인 문서 생성 로직을 먼저 보강한다.

### 3단계: ES retrieval query 재설계

`search_elasticsearch_product_candidates()`에서 query DSL을 재구성한다.

변경 방향:

- `concern_text`와 `intent.search_terms`를 모두 query text로 사용
- `brand_name`, `brand_aliases`에 높은 boost 적용
- `title`, `category_name`, `keywords`, `content` field boost 정리
- 가격 조건은 range filter로 유지
- 제외 조건은 가능하면 `must_not` 또는 후보 후처리로 분리

### 4단계: 구매조건 파서 축소

`parse_purchase_conditions()`에서 브랜드 전수 매칭을 제거하거나 기본 비활성화한다.

초기 구현은 feature flag 또는 parser mode를 둘 수 있다.

```text
recommendation_purchase_brand_filter_mode=legacy | es_signal
```

단, 최종 목표는 추천검색 기본 경로에서 legacy 브랜드 hard filter를 제거하는 것이다.

### 5단계: 성능 측정

동일 조건으로 before/after를 측정한다.

기준 시나리오:

```text
dataset=80000
user_type=full-personalized
vus=10
duration=3m
```

반복 횟수:

```text
최소 3회
```

## 8. 측정 지표

필수 성능 지표:

- `duration_ms`
- `intent_parse_ms`
- `intent_purchase_parse_ms`
- `intent_purchase_brand_match_ms`
- `candidate_generation_ms`
- `elasticsearch_duration_ms`
- `scoring_ms`
- `http_req_duration p95`
- `http_req_failed`
- RPS

필수 품질 지표:

- 후보 500개 확보율
- no-result 비율
- 브랜드 명시 쿼리 top N 브랜드 일치율
- 가격 조건 위반 여부
- 부정 브랜드 노출 여부
- 기존 추천 품질 케이스 통과 여부

## 9. 예상 결과

기대하는 변화:

```text
intent_purchase_brand_match_ms
→ 기본 경로에서 제거 또는 0에 가깝게 감소

intent_purchase_parse_ms
→ 크게 감소

elasticsearch_duration_ms
→ field boost와 query 확장으로 소폭 증가 가능

전체 p95
→ Python 전수 검사 제거분만큼 감소
```

주의할 점:

성능은 개선될 가능성이 높지만, 브랜드 명시 쿼리의 결과 품질은 ES ranking에 의존하게 된다. 따라서 성능 개선과 품질 회귀 테스트를 같은 PR에서 함께 확인해야 한다.

## 10. 트레이드오프

장점:

- Python 전수 regex 매칭 제거
- 검색엔진과 애플리케이션의 책임 분리 개선
- 일반검색과 추천검색의 후보 추출 계층 통합
- 성능 병목 원인과 개선 효과를 문서화하기 쉬움

단점:

- 브랜드 hard filter만큼 강한 제한은 기본적으로 사라진다.
- ES field boost 튜닝이 필요하다.
- 브랜드 명시 쿼리 품질 테스트가 부족하면 결과가 흔들릴 수 있다.
- `말고`, `제외` 같은 부정 표현은 여전히 별도 파싱이 필요하다.

## 11. 커밋 계획

권장 커밋 단위:

```text
test(recommendation): ES 후보 추출 품질 기준 추가
refactor(recommendation): 구매조건 파서에서 브랜드 전수 매칭 분리
feat(recommendation): 추천 후보 추출을 ES 브랜드 필드 중심으로 전환
test(perf): 추천 ES retrieval 전환 벤치마크 추가
docs(perf): 추천 후보 추출 최적화 결과 정리
```

## 12. 문서화 계획

최종 결과는 이 문서를 갱신해 남긴다.

추가로 실제 측정 결과는 아래 경로에 별도 기록한다.

```text
docs/performance/records/YYYY-MM-DD_recommendation-es-retrieval_80000.md
docs/performance/results/recommendation-es-retrieval/
```

결과 문서에는 다음을 포함한다.

- before/after p95 표
- stage breakdown 그래프
- purchase parser breakdown 그래프
- ES duration 변화
- 품질 케이스 결과
- 남은 병목과 다음 최적화 후보

## 13. 최종 판단

이번 최적화는 `Aho-Corasick` 같은 단일 알고리즘 교체보다 더 큰 구조 개선이다.

`Aho-Corasick`은 기존 Python 브랜드 파서를 유지하면서 빠르게 만드는 패치다. 반면 ES retrieval 전환은 후보 추출 책임을 검색엔진으로 이동시키는 설계 개선이다.

추천검색의 장기 구조는 다음이 맞다.

```text
Elasticsearch:
후보 상품을 빠르게 찾는다.

Python intent parser:
점수 계산에 필요한 고민/효능/조건만 구조화한다.

Recommendation scoring:
후보 안에서 개인화와 성분/리뷰/가격 점수를 계산한다.
```

## 14. 1차 구현 결과

이번 1차 구현은 후보 추출 구조 전체를 갈아엎지 않고, 병목으로 확인된 브랜드 hard filter 전수 매칭을 추천 기본 경로에서 제거하는 범위로 제한했다.

적용한 변경:

- `parse_purchase_conditions()`에 `include_brand_filters` 옵션을 추가했다.
- 추천 intent 생성 경로에서는 `include_brand_filters=False`로 호출한다.
- 따라서 추천 기본 경로에서는 브랜드 alias load/match를 수행하지 않는다.
- 가격 조건, 카테고리 조건, 검색 원문과 search terms 조합은 유지한다.
- Elasticsearch 후보 추출에서 `brand_name`, `brand_aliases`, `title`, `category_name` field boost를 강화했다.

의도적으로 건드리지 않은 부분:

- 추천 scoring 계산식
- pgvector 후보 추출
- legacy DB 후보 추출 fallback
- API request/response schema
- DB migration
- frontend
- 신규 성능 metric 추가

검증:

```powershell
docker compose run --rm --no-deps backend python -m pytest tests/test_purchase_conditions.py tests/test_recommendation_intent.py tests/test_elasticsearch_product_search.py
```

결과:

```text
22 passed
```

성능 수치는 이 문서에 아직 확정 기록하지 않는다. 배포 후 기존 benchmark runner로 아래 조건을 다시 측정한 뒤 `docs/performance/records/`에 별도 기록한다.

```text
dataset=80000
user_type=full-personalized
vus=10
duration=3m
```
