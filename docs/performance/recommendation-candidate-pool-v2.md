# 추천 후보 추출 v2

작성일: 2026-07-17

## 목적

Opt6는 추천 파이프라인의 후보 추출 경로만 교체한다. 추천 점수 계산식과
`coarse 500 -> 50`, `exact 50 -> 10` 구조는 변경하지 않는다.

## 현재 구조와 문제

기존 추천 후보 풀은 다음 세 소스를 순서대로 합친다.

```text
추천 전용 Elasticsearch 조회
-> pgvector 조회
-> Product.id 오름차순 DB 후보 500개 조회
-> DB hydration 및 중복 제거
```

현재 벤치마크 환경은 카탈로그 Elasticsearch 색인을 생성하지만 추천 쿼리는
구 추천 색인의 `title`, `keywords`, `content` 필드를 조회한다. 카탈로그 색인에는
이 필드가 없으므로 상품명, 성분, 효능 신호를 정상적으로 사용하지 못한다.

또한 벤치마크 DB의 embedding 문서는 0건이어서 pgvector 소스는 후보를 만들지
못한다. 그와 무관하게 `legacy_id_order`가 매 요청마다 500개를 조회하고 썸네일까지
hydrate하므로, ES 성공 여부와 관계없이 DB 비용과 품질이 낮은 ID순 후보가 섞인다.

## Opt6 목표 흐름

```text
사용자 문장
-> 기존 RecommendationIntent
-> 추천 전용 Query DSL
-> 카탈로그 Elasticsearch 색인
   -> 관련도 직접 매칭
   -> 같은 hard filter 안에서 인기순 부족분 보완
-> ES _source로 최대 500개 ProductCandidate 생성
-> 기존 coarse 500 -> 50
-> 기존 exact 50 -> 10
-> 기존 최종 결과 상세 조회
```

정상 요청에서는 Elasticsearch가 유일한 후보 소스다. pgvector는 Opt6 후보 경로에서
호출하지 않는다. DB 후보 조회는 ES 장애, timeout, alias 오류처럼 ES 결과를 사용할
수 없을 때만 비상 fallback으로 실행한다.

ES가 정상 응답했지만 hard filter를 만족하는 상품이 500개보다 적은 경우에는 DB로
채우지 않는다. 조건을 깨서 후보 수를 맞추는 것보다 사용자가 명시한 조건을 지키는
것을 우선한다.

## 색인과 Query DSL 경계

일반 상품검색과 추천검색은 같은 카탈로그 색인을 사용한다. 다만 목적이 다르므로
Query DSL은 공유하지 않는다.

- 일반 상품검색: 정확 상품 탐색, 정렬, facet, 오타 복구에 맞춘 기존 DSL 유지
- 추천검색: 고민, 기대 효능, 성분, 상품명, 브랜드, 카테고리의 후보 recall에 맞춘 별도 DSL

Opt6는 일반 상품검색의 boost, sort, no-result 정책을 변경하지 않는다.

추천 후보 hard filter는 다음과 같다.

- `is_recommendable=true`
- 파싱된 카테고리와 브랜드
- 최소/최대 가격
- 회피 성분

피부 타입, 스킨테스트, 행동 개인화, 리뷰 개인화는 hard filter로 사용하지 않고 기존
추천 scoring에 맡긴다.

추천 관련도에는 사용자 원문과 파서가 찾은 고민/효능/우선 효능을 사용한다. 검색
대상은 상품명, 브랜드명/별칭, 카테고리, 성분명/별칭, 효능명/별칭, 기능 코드다.
관련도 동점과 직접 매칭 부족분은 popularity를 우선하고, 색인 값이 있을 때만 평점과
리뷰 수를 작은 보조 신호로 사용한다.

## 후보 DTO와 DB 접근

후보 단계에서는 ES `_source`에서 다음 값만 읽는다.

```text
product_db_id
product_id
product_name
brand_code
brand_name
category_code
lowest_price
```

후보 500개의 썸네일과 상세 데이터를 DB에서 hydrate하지 않는다. 썸네일과 상세
정보는 기존 최종 결과 단계에서 선택된 상품에 대해서만 읽는다.

## Legacy와 pgvector 처리

- `legacy_id_order`: 정상 경로에서 제거한다.
- DB fallback: 판매 가능 상품을 우선한 뒤 popularity, 리뷰 수, 안정적인 상품 코드
  순서로 정렬한다.
- pgvector: Opt6에서 활성화하거나 embedding을 생성하지 않는다.
- 기존 추천 전용 ES 색인 코드는 즉시 삭제하지 않고 호환 코드로 남긴다. 런타임 추천
  후보 경로만 카탈로그 색인으로 전환한다.

## 진단 로그

후보 단계에서 다음 값을 남겨 Opt5와 Opt6를 비교할 수 있게 한다.

- ES 검색 시간
- ES 직접 매칭 개수와 인기 보완 개수
- ES 원본 hit 수
- 중복 제거 전/후 개수
- 최종 후보 개수와 cap 적용 개수
- fallback 실행 여부, 사유, 시간, 후보 개수
- 후보 생성 전략 버전

## 배포와 재색인

회피 성분 hard filter를 위해 카탈로그 문서에 `ingredient_codes` keyword 필드를
추가한다. DB schema는 바뀌지 않지만 Elasticsearch mapping과 문서가 바뀌므로 배포
후 전체 카탈로그 재색인이 필요하다.

```bash
docker compose exec -T backend \
  python -m app.cli.index_catalog_products_to_elasticsearch --full
```

재색인 완료 후 alias가 새 카탈로그 색인을 가리키는지 확인한 뒤 추천 API를 검증한다.

## 성능 측정 상태

이 문서는 구현 계약이다. Opt6 성능 개선 수치는 아직 측정하지 않았으며 달성했다고
간주하지 않는다. 구현 머지와 서버 재색인 후 동일한 8만 상품 benchmark 조건으로
사용자가 별도 측정한다.
