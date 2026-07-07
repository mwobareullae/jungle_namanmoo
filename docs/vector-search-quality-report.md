# Vector Search Quality Report

작성일: 2026-07-06
범위: dev DB 1,135개 product join `search_documents`
상태: pgvector embedding 100% 생성 후 1차 품질 점검, exact keyword bonus 2차 보정 반영

## 요약

OpenAI `text-embedding-3-small` 기반 embedding을 전체 product join 문서 1,135개에 생성했고, pgvector 검색 source가 실제로 동작하는 것을 확인했다.

현재 coverage:

| 항목 | 값 |
|---|---:|
| product join documents | 1,135 |
| embedded documents | 1,135 |
| coverage | 100.00% |
| model | `text-embedding-3-small` |
| dimensions | 1536 |

결론:

- pgvector는 정상 동작한다.
- `주름 탄력 앰플`, `수분 진정 크림`처럼 의도가 명확한 검색어에서는 의미 있는 결과가 나온다.
- 단독 검색 backend로 바로 쓰기에는 품질 편차가 있다.
- 현재 전략처럼 `ES keyword 우선 + pgvector fallback/fill + DB fallback` 구조를 유지하는 것이 맞다.
- 다음 작업은 pgvector 결과를 무조건 상위 노출하는 것이 아니라, threshold/source weight/필터/rerank 기준을 조정하는 것이다.

## 검증 방식

대표 검색어 5개를 아래 세 경로로 비교했다.

| Mode | 의미 |
|---|---|
| `es_keyword` | Elasticsearch keyword search만 사용 |
| `pgvector` | pgvector semantic search만 사용 |
| `database` | DB fallback search만 사용 |

검색어:

1. `속건조 보습 추천`
2. `수분 진정 크림`
3. `민감 피부 장벽 세럼`
4. `피지 조절 토너`
5. `주름 탄력 앰플`

## 결과 분석

### 1. 속건조 보습 추천

ES keyword:

- `지피덤 셀트리온EGF 스킨베리어 하이드레이팅 수분크림`
- `듀이트리 AC 딥 장벽 진정 보습 앰플`
- `듀이트리 AC 딥 장벽 진정 보습 크림`

pgvector:

- `반코르 바쿠치올 모공결 주름결 세럼`
- `비건이펙트 콜라겐 NMN 캡슐 크림`
- `비건이펙트 콜라겐 NMN 세럼`

판단:

- ES는 `속건조`, `보습`, `장벽`이 직접 들어간 상품을 잘 잡았다.
- pgvector는 보습/탄력/진정 계열로 의미 확장은 됐지만, `속건조` 직접성은 약했다.
- 이 검색어에서는 ES keyword와 DB exact matching이 더 안정적이다.

조치:

- pgvector는 단독 상위 노출보다 후보 보강 source로 쓰는 것이 맞다.
- `속건조` 같은 강한 키워드는 ES/DB exact signal을 더 우선해야 한다.

### 2. 수분 진정 크림

ES keyword:

- `아벤느 클리낭스 아쿠아크림-인-젤 수분 크림`
- `셀인샷 EGF 알란테놀 트러블 크림`
- `어바웃미 숲 진정 수분 크림`

pgvector:

- `어바웃미 숲 진정 수분 크림`
- `원진이펙트 콜라겐 물방울 수분 크림`
- `세타필 페이셜 수분크림`

DB:

- `션리 다시마 글레이즈드 크림`
- `비플레인 시카테롤 크림`
- `듀이트리 AC 딥 흔적 진정 크림`

판단:

- 세 경로 모두 관련성이 높다.
- pgvector 상위 결과도 카테고리와 의도 모두 잘 맞는다.
- 이 검색어에서는 pgvector가 ES fallback/fill source로 충분히 유용하다.

조치:

- `수분`, `진정`, `크림`처럼 카테고리와 효능이 명확한 검색어에서는 pgvector를 적극 활용해도 된다.

### 3. 민감 피부 장벽 세럼

ES keyword:

- `아렌시아 홀리 히솝 세럼`
- `rdrd 핑크 애플 락토 장벽 세럼`
- `디퍼 소이큐브 엑소리페어 두유 장벽 세럼`

pgvector:

- `주미소 나이아신아마이드 10% 세럼`
- `주미소 나이아신아마이드 20% 세럼`
- `믹순 순디 병풀 에센스`

DB:

- `유리아쥬 시카 데일리 인텐스 리페어 세럼`
- `빌리프 슈퍼드랍스 펩타이드 퍼밍 세럼`
- `스킨앤랩 베리어덤 밀키 세럼`

판단:

- pgvector가 `세럼` 카테고리는 맞췄지만, `민감`, `장벽` 직접성은 약했다.
- ES도 1위는 `피부`와 `세럼`에 끌린 결과로 보이며, 2~3위부터 장벽 관련성이 좋아진다.
- DB exact matching은 `민감`, `장벽`, `세럼` 직접 매칭에서 상대적으로 안정적이다.

조치:

- pgvector 단독 top result로 쓰기에는 위험하다.
- `민감`, `장벽` 같은 safety/skin barrier 의도는 exact keyword 또는 scoring rerank에서 강하게 보정해야 한다.
- candidate pool에서는 pgvector 후보를 넣되, 최종 ranking은 기존 성분/효능/피부 프로필 scoring을 반드시 거쳐야 한다.

### 4. 피지 조절 토너

ES keyword:

- `피캄 베리어 사이클 락토P 토너`
- `조선미녀 맑은쌀채운 토너`
- `몰바니 율피 엑소좀 모공 타이트닝 토너`

pgvector:

- `피지오겔 DMT 에센스 인 토너`
- `몰바니 율피 엑소좀 모공 타이트닝 토너`
- `닥터디퍼런트 스케일링 토너`

DB:

- `피지오겔 레드수딩 시카밸런스 토너`
- `피캄 베리어 사이클 락토P 토너`
- `어나더페이스 펩타테놀 수분 밸런스 토너`

판단:

- pgvector는 토너 카테고리는 잘 잡았다.
- 하지만 `피지 조절`의 `피지`와 브랜드명 `피지오겔`이 섞여 보일 위험이 있다.
- ES/DB도 일부 같은 위험이 있지만, ES는 `피지/진정케어`, `피지케어`처럼 직접 키워드가 들어간 결과를 더 잘 잡았다.

조치:

- `피지`처럼 브랜드명과 의미어가 충돌할 수 있는 term은 keyword/rerank 보정이 필요하다.
- pgvector 결과에 exact term bonus 또는 brand-name false-positive 보정이 필요할 수 있다.

### 5. 주름 탄력 앰플

ES keyword:

- `미샤 비타씨플러스 잡티씨 탄력 앰플`
- `일소 펩타이드 3엑스 모공톡스 탄력 앰플`
- `스킨푸드 도토리 모공 탄력 앰플`

pgvector:

- `테라로직 레티날 주름탄력 앰플`
- `테라로직 레티놀 안티링클3D 모공 앰플`
- `라운드랩 동백 딥 콜라겐 탄력 앰플`

DB:

- `테라로직 레티날 주름탄력 앰플`
- `프랭클리 PDRN 바운스볼 광채세럼 앰플`
- `미샤 비타씨플러스 잡티씨 탄력 앰플`

판단:

- pgvector 결과가 매우 좋다.
- `주름`, `탄력`, `앰플` 의도를 의미적으로 잘 반영했다.
- DB exact와도 상위 결과가 겹친다.

조치:

- 이 유형에서는 pgvector를 적극적으로 활용할 가치가 있다.
- semantic search가 keyword보다 좋은 후보를 앞쪽에 가져올 수 있는 사례다.

## 종합 판단

## exact keyword bonus 2차 보정 결과

적용 내용:

- pgvector score에 exact keyword bonus를 더하되, 최대 bonus는 `0.3`으로 제한했다.
- exact bonus 대상은 `product_name`, search document `title`, category name, `keywords`, `content`로 제한했다.
- exact bonus 계산 전에 `brand.name`, `brand_code`를 match text에서 제거한다.
- brand를 제거한 primary field(`product_name`, `title`, category)에 핵심어가 직접 들어가면 별도 small bonus를 추가한다.
- `추천`, `피부`, `케어` 같은 일반어와 `크림`, `세럼`, `앰플`, `토너`, `로션`, `에센스` 같은 제형어는 exact bonus term에서 제외했다.

이유:

- pgvector는 의미적으로 가까운 상품을 찾는 데 유리하지만, 짧고 강한 효능어를 놓칠 수 있다.
- 반대로 `세럼`, `크림`, `토너` 같은 제형어에 bonus를 주면 이미 category filter로 처리된 내용을 중복 가산하게 되어 순위가 왜곡될 수 있다.
- `피지`와 `피지오겔`처럼 효능어와 브랜드명이 겹치는 경우가 있어 brand text는 matching 전에 제거했다.
- `민감 피부 장벽 세럼`처럼 body/content에는 넓게 걸리지만 상품명/title에는 직접성이 약한 경우가 있어 primary field direct match를 별도 보정했다.

보정 후 대표 결과:

| 검색어 | 보정 후 판단 |
|---|---|
| `속건조 보습 추천` | `보습`, `장벽`, `속건조` 관련 상품이 상위 5개에 안정적으로 포함된다. |
| `수분 진정 크림` | 상위 5개가 모두 cream category이며 `수분`, `진정` 의도도 잘 맞는다. |
| `민감 피부 장벽 세럼` | 상위 5개가 모두 `장벽` 직접 관련 상품으로 개선됐다. |
| `피지 조절 토너` | `피지오겔` brand false-positive가 상위 5개에서 빠지고, 실제 `피지케어` 토너가 1위로 올라왔다. |
| `주름 탄력 앰플` | `주름`, `탄력` 직접 키워드가 강하게 반영되어 품질이 좋다. |

테스트:

- `python -m compileall app/services/pgvector_product_search.py` 통과
- `pytest tests/test_pgvector_product_search.py tests/test_product_search_service.py tests/test_candidate_pool.py` 통과: 13 passed

남은 주의점:

- `민감 피부 장벽 세럼`은 `장벽` 직접성은 개선됐지만, `민감` 자체의 세밀한 품질 평가는 추가 데이터/리뷰 기준이 있으면 더 좋아진다.
- exact bonus만으로 모든 검색어를 해결하면 점수 보정이 과해질 수 있다.
- 다음 보정은 field별 diagnostics 또는 ES/pgvector hybrid merge scoring을 정교화하는 것이 좋다.

## ES 우선 실제 경로 검증

검증 내용:

- Docker 기준 backend, Postgres, Redis, Elasticsearch healthcheck가 모두 정상인 상태에서 `/products/search` 서비스 경로를 확인했다.
- ES가 cold 상태일 때 첫 검색이 `0.5s` timeout에 걸려 pgvector fallback으로 내려가는 현상을 확인했다.
- `ELASTICSEARCH_TIMEOUT_SECONDS` 기본값을 `2.0`으로 올리고 backend 컨테이너를 재생성했다.
- 재검증 결과 대표 검색어 5개 모두 `backend=elasticsearch`, `fallback_used=false`, `es_failure_reason=null`로 응답했다.

조치 이유:

- ES 컨테이너가 healthy여도 첫 검색이나 alias 확인이 0.5초를 넘을 수 있다.
- timeout이 너무 짧으면 실제 장애가 아닌데도 ES를 실패로 보고 pgvector fallback으로 내려간다.
- 2초는 cold query 실패를 줄이면서, ES 장애 시 fallback이 지나치게 늦어지지 않는 절충값이다.

남은 확인점:

- 현재 `/products/search`는 ES가 page size만큼 결과를 반환하면 pgvector를 시도하지 않는다.
- 따라서 `민감 피부 장벽 세럼`처럼 pgvector 보정 결과가 더 좋은 검색어에서도 최종 응답은 ES 결과가 우선한다.
- 다음 품질 작업은 ES 결과가 충분해도 pgvector를 일부 병합할지, 또는 ES ranking 자체를 보정할지 결정하는 것이다.

## AI 추천 후보 생성 경로 검증

검증 내용:

- 일반 검색 `/products/search`는 ES 우선 경로지만, AI 추천 `/api/recommendations`의 후보 생성은 다르다.
- AI 추천 후보 생성에서는 `es_keyword_search`, `pgvector_search`, `legacy_id_order`를 모두 호출한다.
- 대표 검색어 4개 기준으로 ES와 pgvector가 모두 정상 연결되는 것을 확인했다.

대표 결과:

| 검색어 | ES 후보 | pgvector 후보 | legacy 후보 | 최종 후보 pool |
|---|---:|---:|---:|---:|
| `민감 피부 장벽 세럼` | 50 | 50 | 50 | 131 |
| `피지 조절 토너` | 50 | 50 | 50 | 111 |
| `수분 진정 크림` | 50 | 50 | 50 | 117 |
| `주름 탄력 앰플` | 50 | 50 | 50 | 130 |

판단:

- AI 추천에서는 pgvector가 단순 fallback이 아니라 실제 후보 source로 동작한다.
- 최종 scoring 상위권에도 pgvector 후보가 들어온다.
- 따라서 pgvector 보정 작업은 AI 추천 후보 다양성과 의미 기반 후보 보강에 실제로 반영된다.

남은 주의점:

- 최종 추천 순위는 search score만으로 결정되지 않는다.
- 현재 scoring에서 search match 비중은 전체 점수 중 일부라서, 성분/피부/효능 점수가 더 강하게 작동할 수 있다.
- `민감 피부 장벽 세럼`처럼 검색 의도가 강한 질의에서는 pgvector 후보가 들어오더라도 최종 1위가 반드시 `장벽` 직접 상품이 되지는 않는다.
- 다음 AI 추천 품질 작업은 search intent가 강한 질의에서 `search_match` 또는 `vector_score` 비중을 조건부로 높일지 검토하는 것이다.

## AI 추천 search intent boost 1차 반영

적용 내용:

- scoring version을 `v1_search_intent_boost`로 올렸다.
- 기본 scoring weight는 기존 구조를 유지한다.
- 카테고리/브랜드 같은 명확한 상품 selector와 검색 terms가 함께 있는 질의에만 `search_intent_boost` profile을 적용한다.
- `search_match` weight를 `0.07`에서 `0.15`로 높였다.
- 총합 1.0을 유지하기 위해 `ingredient_effect`, `ingredient_evidence` weight를 낮췄다.

weight 비교:

| 항목 | 기본 | search intent boost |
|---|---:|---:|
| ingredient_effect | 0.35 | 0.31 |
| ingredient_evidence | 0.25 | 0.21 |
| skin_profile | 0.15 | 0.15 |
| concentration_fit | 0.08 | 0.08 |
| functional_claim | 0.05 | 0.05 |
| search_match | 0.07 | 0.15 |
| price | 0.05 | 0.05 |

검증 결과:

- `민감 피부 장벽 세럼`, `피지 조절 토너`, `수분 진정 크림`, `주름 탄력 앰플`에는 `search_intent_boost`가 적용됐다.
- `민감하고 진정 위주 추천`처럼 카테고리/브랜드 selector가 없는 고민형 문장은 기존 `default` profile을 유지했다.
- 최종 상위 추천에도 pgvector 후보가 계속 포함된다.
- `수분 진정 크림`에서는 `수분진정` 직접 상품이 최상위로 올라왔다.
- `민감 피부 장벽 세럼`에서는 장벽 직접 상품이 상위권에 올라왔지만, 1위가 항상 장벽 직접 상품이 되지는 않았다.

판단:

- 이번 변경은 검색 의도가 강한 질의에서 검색 관련성을 더 반영하는 보수적인 1차 보정이다.
- 팀 약속인 `ES keyword + pgvector 후보 보강 + DB fallback` 구조를 바꾸지 않는다.
- 일반 검색 `/products/search`의 ES 우선 구조도 바꾸지 않는다.
- 검색 의도 보정은 AI 추천 최종 scoring 내부에만 적용된다.

남은 주의점:

- `search_match` weight만 올리면 충분하지 않은 케이스가 있다.
- 특히 `민감`, `장벽`, `피지` 같은 term은 document body에 넓게 매칭되어 keyword score가 여러 상품에서 비슷해질 수 있다.
- 다음 단계에서 필요하면 `title/product_name direct match`를 AI 추천 scoring에도 별도 feature로 넣는 방식을 검토한다.

### 잘 된 점

- pgvector embedding coverage가 100%가 됐다.
- pgvector source가 실제 API와 추천 후보 생성에서 동작한다.
- ES가 꺼졌을 때 `/products/search`가 DB fallback으로 바로 내려가지 않고 pgvector로 응답한다.
- `주름 탄력 앰플`, `수분 진정 크림`, `피지 조절 토너`, `민감 피부 장벽 세럼`에서 pgvector 결과 품질이 개선됐다.
- 기존 fallback 구조가 유지된다.

### 문제점

- pgvector 단독 결과는 검색어별 편차가 있다.
- `민감`처럼 피부 타입/주의 성향에 가까운 term은 상품명보다 profile/content에 많이 들어가므로 별도 품질 기준이 필요할 수 있다.
- `피지`와 `피지오겔`처럼 의미어와 브랜드명이 섞일 수 있어 brand stripping을 유지해야 한다.
- pgvector score를 단독 순위로 쓰면 exact keyword 의도를 놓칠 수 있다.

## 다음 조정 방향

### 1. ES keyword 우선 전략 유지

현재 구조는 유지한다.

```text
ES keyword
→ pgvector fallback/fill
→ DB fallback
```

이유:

- 상품명/브랜드/카테고리/정확한 효능어는 ES/DB exact matching이 안정적이다.
- pgvector는 의미 확장과 후보 보강에 강하다.

### 2. pgvector source weight를 낮게 시작

candidate pool에서 pgvector는 중요한 source지만 최종 순위를 지배하면 안 된다.

추천:

```text
es_keyword_search weight > pgvector_search weight > legacy_id_order weight
```

현재 설계 방향과 맞다.

### 3. exact keyword bonus를 유지하거나 강화

특히 아래 term은 exact match가 중요하다.

- `민감`
- `장벽`
- `피지`
- `주름`
- `탄력`
- `진정`
- `수분`

pgvector 결과가 있더라도 이런 term이 상품명/keywords/content에 직접 들어가면 rerank에서 보정하는 것이 좋다.

### 4. category hard filter 유지

`크림`, `세럼`, `토너`, `앰플` 같은 카테고리성 검색어는 product category 또는 product name signal로 강하게 반영해야 한다.

pgvector만 믿으면 의미적으로 가까운 다른 제형이 섞일 수 있다.

### 5. brand false-positive 점검

`피지`와 `피지오겔`처럼 단어 일부가 브랜드명과 겹치는 경우가 있다.

향후 보정 후보:

- brand_name match와 efficacy/concern term match를 diagnostics에서 분리
- concern term이 brand_name에만 걸린 경우 ranking 가산을 제한
- `피지` 같은 짧은 term은 exact field별 가중치를 다르게 둠

## 결론

pgvector 고도화 방향은 맞다. 다만 pgvector를 ES keyword의 대체재로 쓰면 안 되고, 검색 후보 source 중 하나로 사용하는 것이 맞다.

현재 가장 합리적인 운영 방식:

```text
1. ES keyword search로 정확한 후보를 먼저 찾는다.
2. pgvector search로 의미적으로 가까운 후보를 보강한다.
3. DB fallback으로 장애 상황을 방어한다.
4. 최종 추천 순위는 기존 scoring.py에서 성분/효능/피부/가격/risk/search score를 종합해 rerank한다.
```

다음 구현 후보:

1. pgvector score threshold 또는 최소 score diagnostics 추가
2. exact keyword bonus/rerank 보강
3. brand false-positive 보정
4. ES와 pgvector hybrid merge scoring 정교화
5. 10만 상품 기준 pgvector HNSW/IVFFlat index 검토

## `민감` 의도 반영 보정

후속 QA에서 `민감하고 진정 위주 추천`의 `민감`이 `unmatched_terms`로 남는 문제가 확인됐다.

원인:

- 예제 데이터에는 `concern_sensitive`가 있었지만, 실제 운영 데이터 `data/tags.json`에는 `민감` concern이 없었다.
- API 요청에서 `sensitivity`를 명시하지 않으면 기본값 `보통`이 적용되어, concern text 안의 `민감/예민` 표현이 민감도 scoring에 반영되지 않았다.

조치:

- 운영 데이터에 `concern_sensitive`를 추가했다.
- `concern_sensitive`는 `진정`을 주효과, `보습·장벽`을 보조효과로 연결했다.
- `sensitivity`가 비어 있고 concern text에 `민감/예민` 계열 표현이 있으면 민감도 `민감`으로 추론하도록 했다.
- 사용자가 `sensitivity`를 직접 보낸 경우에는 명시값을 우선한다.

검증 결과:

- `민감하고 진정 위주 추천`
  - `sensitivity`: `민감`
  - `matched_concerns`: `민감`
  - `expected_effects`: `진정`, `보습·장벽`
  - `unmatched_terms`: 없음
  - `needs_llm`: `False`
- `민감 피부 장벽 세럼`
  - `sensitivity`: `민감`
  - `matched_concerns`: `민감`
  - `expected_effects`: `진정`, `보습·장벽`
  - `unmatched_terms`: 없음
  - `needs_llm`: `False`

테스트:

- `tests/test_recommendation_intent.py`
- `tests/test_api_contracts.py`
- `tests/test_scoring.py`

결과: `48 passed`

## Docker 실행 검증

Docker Compose 기준으로 backend/Postgres/Redis/Elasticsearch를 실행해 검증했다.

검증 결과:

- `docker compose up -d --build backend`
  - backend 이미지 재빌드 성공
  - backend 컨테이너 재생성 후 `healthy`
- Elasticsearch 정상 상태 검색 API:
  - 요청: `/api/products/search?q=수분 크림&page_size=3`
  - `backend`: `elasticsearch`
  - `fallback_used`: `false`
  - `es_failure_reason`: `null`
- Elasticsearch 중지 상태 검색 API:
  - 요청: `/api/products/search?q=수분 크림&page_size=3`
  - `backend`: `pgvector`
  - `fallback_used`: `true`
  - API는 실패하지 않고 3개 상품을 반환했다.
- AI 추천 API:
  - 요청: `민감하고 진정 위주 추천`
  - `sensitivity`: `민감`
  - `matched_concerns`: `민감`
  - `expected_effects`: `진정`, `보습·장벽`
  - `unmatched_terms`: 없음

검증 중 발견/조치:

- Docker 환경에서 ES가 중지된 경우 실패 사유가 `connection check timed out after 0.5s`로 표시됐다.
- 컨테이너 설정값 `ELASTICSEARCH_TIMEOUT_SECONDS`는 `2.0`이었지만, ES 사전 연결 체크 코드가 `0.5s` 상한을 강제하고 있었다.
- 사전 연결 체크도 provider timeout 설정을 사용하도록 수정했다.
- 수정 후 ES 중지 상태 실패 사유가 `connection check timed out after 2.0s`로 정상 반영됐다.
- ES를 다시 시작한 뒤 backend를 재시작해 정상 검색 경로가 `elasticsearch`로 복구되는 것도 확인했다.

Docker 테스트:

- `docker compose exec -T backend pytest tests/test_elasticsearch_product_search.py tests/test_product_search_service.py`
- 결과: `9 passed`
