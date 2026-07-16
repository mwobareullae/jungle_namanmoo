# 뭐바를래 기술 보고서 최종 초안

작성일: 2026-07-10
상태: Final Draft — 추천 품질 및 최적화 결과 입력 전
분류: **필수 문서 1/2 — 전체 맥락과 기술적 판단 기준**
범위: P2 자사몰
기준 환경: EC2 `t3.large`(FastAPI, Elasticsearch, Redis 준비), RDS PostgreSQL + pgvector, S3/CloudFront, Vercel
기준 데이터: 상품 약 80,000건

> 권장 읽기 순서: 이 문서로 서비스 목표·추천 평가·성능 문제를 이해한 뒤 `performance-kpi-draft.md`에서 측정 조건을 확인한다.

---

## 목차

- [0. 서비스 목표와 의의](#0-서비스-목표와-의의)
- [1. 핵심 차별점: 성분표를 추천 근거로 바꾸기](#1-핵심-차별점-성분표를-추천-근거로-바꾸기)
- [2. 추천 알고리즘 설계](#2-추천-알고리즘-설계)
- [3. 추천이 적합했는지 측정하기](#3-추천이-적합했는지-측정하기)
- [4. 8만 상품에서 실시간 추천하기](#4-8만-상품에서-실시간-추천하기)
- [5. 성능 개선 실험 계획](#5-성능-개선-실험-계획)
- [6. 서비스 아키텍처와 선택 이유](#6-서비스-아키텍처와-선택-이유)
- [7. 최종 기술적 챌린지](#7-최종-기술적-챌린지)
- [8. 최종 성과 작성 형식](#8-최종-성과-작성-형식)
- [9. 발표 전 완료 체크리스트](#9-발표-전-완료-체크리스트)

---

# 0. 서비스 목표와 의의

## 0.1 우리가 해결하려는 문제

화장품 사용자는 전성분표에서 어떤 성분이 들어 있는지는 확인할 수 있다. 하지만 실제 구매 결정에는 다음 질문이 남는다.

- 이 성분이 내 피부 고민에 왜 필요한가?
- 그 효능을 뒷받침하는 근거가 있는가?
- 성분이 들어 있기만 한 것인가, 의미 있는 함량 구간인가?
- 내 피부 타입과 민감도에서는 어떤 위험을 고려해야 하는가?
- 비슷한 상품 중 왜 이 상품이 더 위에 추천되었는가?

기존의 `성분 있음/주의` 정보만으로는 이 질문을 하나의 구매 결정으로 연결하기 어렵다.

## 0.2 뭐바를래의 목표

> 사용자가 자연어로 피부 고민을 입력하면, 고민을 표준 효능으로 해석하고 성분·함량·근거·피부 적합도를 계산해 추천 순위를 만들며, 그 이유를 다시 설명할 수 있는 뷰티 커머스를 만든다.

뭐바를래의 핵심은 생성형 AI가 상품을 임의로 고르는 것이 아니다.

```text
LLM/규칙 parser
자연어 고민을 구조화
          ↓
검색 엔진
8만 상품에서 후보를 축소
          ↓
Scoring engine
성분·효능·근거·함량·피부 적합도를 계산
          ↓
추천 결과
점수와 근거 경로를 저장하고 사용자에게 설명
```

## 0.3 서비스의 기술적 의의

### 첫째, 성분 데이터를 상품 설명이 아니라 ranking feature로 사용한다

성분 이름을 표시하는 데서 끝나지 않고 다음 값을 추천 점수로 변환한다.

- 성분과 기대 효능의 관련성
- 효능 근거의 신뢰 수준
- 공개된 성분 함량과 유효 구간
- 기능성 화장품 근거
- 피부 타입과 민감도 적합도
- 위험 성분 감점

### 둘째, 추천을 설명 가능한 데이터로 보존한다

추천 결과에는 단순한 자연어 설명만 남기지 않는다.

- `scoring_version`
- 적용 weight profile
- score breakdown
- 핵심 성분과 효능
- concentration bucket과 warning
- evidence level과 출처
- 추천 ID와 rank

따라서 추천 결과가 나온 뒤에도 “왜 이 상품이 위에 있었는가”를 다시 추적할 수 있다.

### 셋째, 추천 실험을 실제 커머스 흐름과 연결한다

```text
고민 입력
→ 추천
→ 상품 상세
→ 장바구니
→ checkout preview
→ 주문/결제 mock
```

추천 ID와 추천 순위가 상품 상세와 장바구니까지 이어지므로, 이후 추천 노출이 클릭·장바구니·구매로 연결됐는지 측정할 수 있다.

## 0.4 P2의 완료 목표

P2는 마켓플레이스 확장이 아니라 다음 두 가지를 실제 동작 상태로 증명하는 단계다.

1. 상품 8만 건에서 검색과 추천이 동작한다.
2. Auth부터 Cart, Order, Payment mock까지 최소 커머스 흐름이 연결된다.

---

# 1. 핵심 차별점: 성분표를 추천 근거로 바꾸기

## 1.1 정보 제공과 추천의 차이

| 일반적인 성분 정보 | 뭐바를래의 추천 판단 |
| --- | --- |
| 어떤 성분이 들어 있음 | 어떤 피부 고민의 어떤 효능과 연결되는지 계산 |
| 주의 성분 표시 | 피부 민감도에 따라 위험 감점 |
| 성분 목록 제공 | 함량이 meaningful/optimal/excessive 중 어디인지 평가 |
| 제품 설명 표시 | 논문·고시 등 근거 수준을 score에 반영 |
| 동일한 상품 목록 | 고민과 피부 맥락에 따라 순위 계산 |

외부 서비스를 직접 비교하는 문구는 발표 전 최신 기능을 확인한 뒤 사용한다. 확인되지 않은 경쟁 서비스의 한계를 단정하지 않고, 뭐바를래가 실제 구현한 기능을 중심으로 설명한다.

## 1.2 추천 근거 경로

```text
사용자 고민
“속은 당기는데 겉은 기름지고 자극 없이 진정되고 싶어요.”
          ↓
표준 고민
속건조 · 피지 · 민감
          ↓
기대 효능
보습 장벽 · 진정 · 피지 케어
          ↓
성분과 함량
관련 성분 · 농도 · 유효 구간
          ↓
근거
논문 · DOI/PMID · 식약처 고시
          ↓
상품 ranking
총점 · score breakdown · 위험 감점
```

## 1.3 반드시 지킬 표현

뭐바를래가 평가하는 근거는 해당 `성분↔효능` 연결에 대한 근거다. 해당 상품 자체의 임상 효능을 증명한다고 표현하지 않는다.

함량도 모든 상품에서 알 수 있다고 말하지 않는다.

- 함량을 공개하거나 정규화할 수 있는 상품: 유효 구간 평가
- 함량을 알 수 없는 상품: unknown 상태와 낮은 confidence 표시
- 전체 함량 데이터 coverage와, 데이터가 있을 때 판정 성공률을 분리

---

# 2. 추천 알고리즘 설계

## 2.1 자연어 고민 구조화

추천 요청은 다음 단계로 해석한다.

1. 규칙 parser가 명확한 고민·가격·카테고리·브랜드·제외 조건을 추출한다.
2. LLM이 동의어, 문맥, 부정 표현과 복합 고민을 보완한다.
3. 결과를 표준 고민·효능·구매 조건 schema로 제한한다.
4. 위험하거나 해석이 모호한 표현은 억지로 추천 근거에 넣지 않고 `unmatched_terms`와 review 대상으로 보존한다.

LLM은 입력을 구조화하는 역할을 하며 최종 상품 순위를 직접 결정하지 않는다.

## 2.2 후보 추출

8만 상품을 매 요청마다 모두 scoring하지 않기 위해 다음 후보 소스를 결합한다.

- Elasticsearch keyword search
- PostgreSQL pgvector semantic search
- 구매 조건 hard filter
- `products.is_recommendable = true` 추천 가능 상품 filter
- retrieval 장애 시 제한된 fallback

후보 추출의 목표는 최종 정답을 만드는 것이 아니라, 적합 상품을 놓치지 않으면서 scoring 대상 수를 줄이는 것이다.

추천 후보 품질은 추천 가능 상품 카탈로그를 분모로 한 `Recall@50`으로 평가한다. `is_recommendable = false`인 상품은 정답 레이블에서 제외하거나 별도 제외 사례로 분류하고, 제외 사유 분포를 함께 기록한다.

추천 가능 여부 컬럼과 seed 값만 바뀐 경우 embedding을 다시 만들 필요는 없다. Elasticsearch mapping이나 candidate filter schema를 함께 변경할 때만 reindex 필요 여부를 별도로 판단한다.

## 2.3 현재 ranking 축

현재 실제 ranking 계산에서 사용하는 기본 coefficient는 다음과 같다.

| 축 | 기본 coefficient | 의미 |
| --- | ---: | --- |
| 성분-효능 | 0.32 | 사용자 기대 효능과 관련 성분의 연결 점수 |
| 효능 근거 | 0.23 | 근거 점수와 출처 신뢰도 |
| 피부 적합도 | 0.14 | 피부 타입과 민감도 적합도 |
| 함량 적합도 | 0.08 | 성분 함량의 유효 구간 |
| 기능성 근거 | 0.05 | 기능성 화장품 claim과 confidence |
| 검색 일치도 | 0.07 | keyword/vector 검색 관련성 |
| 가격 적합도 | 0.04 | 사용자의 구매 가격 조건 |
| 시장 신호 | 0.02 | 조회·장바구니·구매·리뷰 등 상품 시장 신호 |
| 최근 피부 테스트 | 0.05 | 최신 피부 테스트 결과와의 적합도 |
| 행동 개인화 | 0.08 | 인증 사용자의 유효한 행동 affinity |

민감 피부 위험 성분은 별도의 penalty로 최종 점수에서 차감한다.

검색 의도가 강한 요청은 별도 weight profile을 적용해 search match 비중을 높인다. 피부 테스트 또는 행동 맥락이 없으면 해당 weight를 0으로 만들고 나머지 weight를 다시 정규화한다. 결과에는 어떤 weight profile을 사용했는지 함께 저장한다.

## 2.4 함량 평가

함량 정보가 있는 성분은 효능별 기준 구간과 비교한다.

```text
unknown
below_meaningful
meaningful
optimal
above_optimal
excessive
```

함량이 높을수록 무조건 좋은 것으로 처리하지 않는다. optimal 구간을 넘거나 excessive 기준에 해당하면 점수를 낮추고 warning을 표시할 수 있다.

## 2.5 설명 가능성

상품별 score breakdown에는 다음 정보가 포함된다.

- ingredient effect score
- ingredient evidence score
- concentration fit score와 bucket
- skin type/sensitivity score
- functional claim score
- keyword/vector/search match score
- price score
- market signal score
- skin-test context score
- behavior personalization score
- risk penalty와 warning
- scoring version과 weight profile

## 2.6 현재 구현과 다음 확장 구분

현재 scoring version은 `v7_review_quality_v3`이다. 피부 타입·민감도·최신 피부 테스트와 행동 affinity에 더해, 점수 대상 외부 리뷰의 사전 집계 품질과 유사 프로필 affinity를 ranking에 반영한다. 자사몰 리뷰는 공개 정보에는 남지만 점수에서 제외한다. 행동 데이터가 없으면 행동 weight를 0으로 만들고 나머지 축을 재정규화하며, 리뷰 원문은 추천 요청 중 조회하지 않는다.

이는 구현 상태에 대한 설명이며 효과가 검증됐다는 뜻은 아니다. 동일 test set에서 행동 축을 끈 결과와 비교하는 ablation으로 품질 개선과 latency 비용을 확인한 뒤 발표 수치에 포함한다.

Redis도 인프라와 설정은 준비되어 있으나 실제 cache 경로가 구현·검증된 뒤에만 성능 개선 결과로 포함한다.

---

# 3. 추천이 적합했는지 측정하기

## 3.1 왜 추천 평가는 어려운가

추천에는 하나의 정답 상품이 없다.

- 같은 고민에도 적합한 상품이 여러 개일 수 있다.
- 사용자는 노출되고 구매한 상품만 리뷰할 수 있다.
- 인기 상품은 리뷰가 많아 평가에서도 유리하다.
- 높은 별점이 효능이 아니라 배송·향·패키지 때문일 수 있다.
- 하나의 리뷰 안에 “보습은 좋지만 트러블이 났다”처럼 긍정과 부정이 공존할 수 있다.

따라서 리뷰를 절대적인 ground truth로 사용하지 않고, 실제 고민과 사용 경험이 연결된 `silver label`로 사용한다.

## 3.2 리뷰 기반 silver-label 생성

```text
원본 리뷰
→ 피부 타입·고민·효능별 문장 분리
→ 사용 전 고민과 사용 후 결과 분리
→ 효능별 긍정/부정 판정
→ 상품명·브랜드명·정답 노출 표현 제거
→ 표준 고민·효능 tag 변환
→ relevance grade와 confidence 부여
→ 사람 표본 검수
→ 고정된 평가 데이터셋
```

### Relevance grade

| grade | 기준 |
| ---: | --- |
| 3 | 고민과 구체적인 개선 또는 재구매 경험이 연결됨 |
| 2 | 피부 타입과 관련 효능의 긍정 경험이 명확함 |
| 1 | “촉촉하다”, “좋다”처럼 관련성은 있으나 근거가 약함 |
| 0 | 배송·향·용기 등 추천 효능과 무관함 |
| -1 | 해당 고민에서 악화·자극·부정 경험이 명확함 |

### 평가 데이터 최소 schema

```text
review_id
product_id
concern_tags
effect_tags
skin_type
polarity
relevance_grade
label_confidence
leakage_flags
split
```

실제 CSV/JSON 계약을 확정할 때는 `docs/data/data-contract.md`를 함께 갱신한다.

리뷰 사용 권한을 확인하고 작성자 식별 정보와 원문에 포함된 개인정보를 제거한다.

### Silver-label 데이터 품질 KPI

추천 지표보다 먼저 평가 레이블 자체가 신뢰 가능한지 측정한다.

| KPI | 의미 | 목표 초안 |
| --- | --- | ---: |
| Product mapping rate | 리뷰를 내부 `product_id`와 연결한 비율 | 95% 이상 |
| Concern extraction precision | 추출한 고민이 리뷰 내용과 일치하는 비율 | 90% 이상 |
| Effect sentiment precision | 효능별 긍정·부정 판정 정확도 | 90% 이상 |
| Leakage rate | 상품명·브랜드명 등 정답 단서가 입력에 남은 비율 | 0% |
| Human agreement | 두 검수자의 레이블 일치도 | Cohen's κ 0.70 이상 |
| Label coverage | 전체 리뷰 중 relevance grade를 부여할 수 있는 비율 | 측정값과 제외 사유 공개 |
| Grade distribution | `-1~3` 레이블 분포 | 구간별 건수 공개 |
| Eligibility mapping rate | 레이블 상품의 추천 가능 여부를 판정한 비율 | 100% |

`Label coverage`를 무리하게 높이지 않는다. 모호한 리뷰를 억지로 레이블링하는 것보다 제외 사유를 남기고 precision을 지키는 편이 추천 평가에 유리하다. 평가 시점에 추천 불가 상품으로 판정된 리뷰는 ranking 실패로 계산하지 않고 `recommend_exclude_reason`과 함께 별도 집계한다.

## 3.3 리뷰 replay KPI

리뷰에서 정제한 사용 전 고민만 추천 입력으로 사용한다.

### 개별 리뷰 평가

| KPI | 의미 | 목표 초안 |
| --- | --- | --- |
| HitRate@10 | 원래 긍정 경험 상품이 Top-10에 등장한 비율 | 인기순·BM25 baseline 상회 |
| MRR@10 | 원래 긍정 경험 상품이 얼마나 상위에 등장했는지 | baseline 상회 |
| Recall@50 | 후보군 50개에서 긍정 상품을 놓치지 않은 비율 | 0.90 이상 |

### 고민 그룹 평가

동일한 표준 고민 리뷰를 묶고 상품별 relevance grade를 집계한다.

| KPI | 의미 | 목표 초안 |
| --- | --- | ---: |
| Concern-group NDCG@10 | 고민별 다중 적합 상품의 순위 품질 | 0.80 이상 |
| Negative exposure@10 | grade -1 상품이 같은 고민 Top-10에 노출되는 비율 | baseline 대비 감소 |

## 3.4 리뷰 평가의 누출과 편향 방지

- 별점 자체가 아니라 고민·효능별 sentiment를 레이블로 사용한다.
- 상품명, 브랜드명, 상품 고유 문구를 입력에서 제거한다.
- 성분명이 정답 상품을 사실상 특정하면 제거하거나 leakage flag를 둔다.
- review 수와 popularity를 기준으로 head/mid/tail 결과를 분리한다.
- 같은 리뷰의 중복·요약·파생 문장이 train과 test에 동시에 들어가지 않게 한다.
- 추천 parser와 동일한 LLM으로 label을 만들 경우 오류가 서로 닮을 수 있으므로 사람이 표본을 검수한다.
- review label을 weight tuning에 사용한다면 시간 기준으로 train/dev/test를 분리하고 test를 tuning에 사용하지 않는다.

## 3.5 사람이 만든 gold set

리뷰의 구매·노출 편향을 보완하기 위해 독립적인 gold set을 사용한다.

권장 구성:

- 자연어 고민 100~200문장
- 명확한 표현, 동의어, 복합 고민, 부정 표현, 위험 표현
- 피부 타입, 민감도, 가격, 제외 성분 조합
- 최소 2명이 독립적으로 annotation하고 불일치 항목 합의

| KPI | 목표 |
| --- | ---: |
| Concern extraction F1 | 0.90 이상 |
| Effect extraction F1 | 0.90 이상 |
| Purchase constraint accuracy | 95% 이상 |
| Hard constraint violation | 0% |
| Expert relevance NDCG@10 | 0.80 이상 |

## 3.6 차별점을 증명하는 ablation test

동일한 review/gold test에서 추천 축을 단계적으로 추가한다.

```text
인기순
→ BM25/keyword
→ 성분 포함 여부
→ 성분 + 효능
→ 성분 + 효능 + 근거
→ 성분 + 효능 + 근거 + 함량
→ 전체 scoring
```

각 단계에서 다음 값을 비교한다.

- HitRate@10
- MRR@10
- NDCG@10
- Recall@50
- hard constraint violation
- negative exposure@10

근거 축과 함량 축을 제거했을 때 품질이 하락하는지를 확인하는 것이 뭐바를래의 차별점을 가장 직접적으로 증명한다.

## 3.7 설명 가능성 KPI

| KPI | 목표 |
| --- | ---: |
| Score breakdown 제공률 | 100% |
| Top-5 evidence path coverage | 95% 이상 |
| Source traceability | 95% 이상 |
| 함량 데이터 보유 상품의 concentration 판정 성공률 | 99% 이상 |
| 표시 이유와 실제 상위 score 축의 일치율 | 95% 이상 |

## 3.8 실제 서비스 행동 평가

offline 평가 이후에는 다음 전환을 확인한다.

- 추천 노출 대비 클릭률
- 클릭 대비 장바구니 전환율
- 장바구니 대비 구매 전환율
- 추천 후 찜/장바구니 제거 및 부정 행동률

review replay, gold set, online behavior 중 하나만으로 추천 품질을 단정하지 않는다.

## 3.9 측정 도구와 산출물 분리

성능 평가와 추천 품질 평가는 목적과 실행 방식이 다르므로 하나의 k6 실행에 섞지 않는다.

```text
k6
→ p50/p95/p99 · 오류율 · req/s · iterations/s · 자원 사용률

offline recommendation evaluator
→ label QA · HitRate · MRR · Recall · NDCG · ablation · slice별 편향

서비스 이벤트
→ 노출 · 클릭 · 장바구니 · 구매 · 부정 행동 전환
```

권장 추천 평가 산출물:

```text
evaluation-runs/<timestamp>_<dataset-version>_<scoring-version>/
├── dataset-summary.json
├── label-qa.json
├── overall-metrics.json
├── slice-metrics.json
├── ablation-metrics.json
├── failed-cases.jsonl
└── report.md
```

`report.md`에는 dataset version, scoring version, Git SHA, review split, label 분포와 제외 사유를 기록한다.

---

# 4. 8만 상품에서 실시간 추천하기

## 4.1 최초 문제 상태

2026-07-08 실행은 정상 baseline이 아니라 병목이 이미 발생한 실패 상태다.

| 항목 | 결과 |
| --- | ---: |
| 환경 | EC2 t3.xlarge, 10 VU, 4분 |
| 상품 | 79,957건 |
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

이 수치는 최초 문제 상태를 설명하는 자료로만 사용한다. 당시 환경은 t3.xlarge에서 backend limit 6GiB, Docker PostgreSQL과 frontend container까지 포함했다. 현재 목표 환경은 t3.large에서 외부 RDS와 Vercel을 사용하는 구성이므로 최종 Before/After는 동일 환경에서 다시 측정한다.

backend가 실제로 2.78GiB까지 사용한 실행에 2GiB limit을 적용하면 OOM 가능성이 있다. 따라서 Compose 기본값 2GiB를 실제 적정값으로 확정하지 않고, t3.large의 1차 검증값을 3584MiB로 둔 뒤 최적화 후 다시 산정한다.

## 4.2 확인된 병목

### 홈 API

최종 응답은 섹션별 소수 상품이지만 내부에서는 다음 데이터를 먼저 읽었다.

- 상품 약 79,516행
- 이미지 수만 행
- 성분/효능 join 최대 약 39만행
- 전체 후보를 Python에서 scoring·sorting

핵심 문제는 “최종 10~20개를 보여주기 위해 전체 상품을 hydrate”한 것이다.

최신 `dev`에는 기존 `/api/home/sections`를 제거하고 다음 섹션별 API와 contract test가 구현되어 있다.

```text
/api/home/layout
/api/home/market-popular
/api/home/evidence-picks
/api/home/for-you
```

목적은 느린 섹션의 장애 전파를 막고, 섹션별 관측·lazy loading·skeleton·cache 정책을 분리하는 것이다. k6가 신규 endpoint를 backend보다 먼저 반영했기 때문에 2026-07-10 smoke의 404는 계약 전환 순서에서 발생했다. 최신 `dev` 배포 후에는 migration·seed와 contract preflight를 통과한 새 실행으로 성능을 다시 측정한다.

신규 구조의 효과는 endpoint latency만 따로 보는 것으로 끝내지 않는다. 브라우저 병렬 호출의 홈 준비시간, 섹션별 error 격리, 전체 요청 수·CPU·DB query time 합계와 기존 묶음형 문제 상태를 함께 비교한다.

### 추천 API

추천 생성은 다음 stage에서 지연됐다.

- intent parse: 약 12~35초
- candidate pool: 약 2~12초
- scoring: 약 2~9초

일부 실행에서는 Elasticsearch와 pgvector 후보가 0이고 `legacy_id_order` 후보 500개에 의존했다.

### 상품 검색

Elasticsearch 사용률이 낮고 DB fallback에서 다음 작업이 발생했다.

- 여러 문자열 컬럼에 `%term%` 검색
- 전체 결과 조회
- Python score 계산과 정렬
- 반복 coverage count

## 4.3 성능 목표

| KPI | 목표 |
| --- | ---: |
| 전체 오류율 | 1% 미만 |
| health p95 | 300ms 이하 |
| fast read p95 | 1초 이하 |
| home p95 | 1.5초 이하 |
| product search p95 | 2초 이하 |
| recommendation core p95 | 3초 이하 |
| write p95 | 1.5초 이하 |
| OOM/restart | 0건 |
| target load | 50 VU, 10분 PASS |

외부 LLM이 포함된 E2E 추천은 core 추천과 분리해 p95 8초 이하를 1차 목표로 둔다.

## 4.4 검색·추천 내부 KPI

| KPI | 목표 |
| --- | ---: |
| Elasticsearch index/alias 정상 | 테스트 전 100% |
| pgvector embedding coverage | 99% 이상 |
| 검색 DB fallback 비율 | 1% 미만 |
| 추천 legacy-only fallback 비율 | 1% 미만 |
| intent parse p95, 외부 LLM 제외 | 300ms 이하 |
| candidate pool p95 | 500ms 이하 |
| scoring p95 | 1초 이하 |

## 4.5 서버와 데이터 계층 KPI

| 계층 | KPI | 목표 |
| --- | --- | ---: |
| EC2 | CPU | 평균 70% 이하, 5분 최대 90% 이하 |
| EC2 | CPUCreditBalance | 20 이상, 고갈 없음 |
| EC2 | disk used | 70% 미만 |
| FastAPI | container memory | limit의 80% 미만 |
| Elasticsearch | container memory | limit의 80% 미만 |
| RDS | CPU | 평균 60% 이하, 최대 80% 이하 |
| RDS | connection | 최대 연결 수의 70% 미만 |
| RDS | idle in transaction | 2회 연속 샘플에서 1개 이상이면 FAIL |
| RDS | slow query | API 요청당 0.2건 이하, 1초 초과 0건 |

## 4.6 컨테이너 메모리와 인프라 분리 결정

P2의 t3.large 1차 설정은 다음과 같다.

```text
FastAPI limit       3584MiB
Elasticsearch limit 2GiB
Elasticsearch heap  1GiB
Redis limit         512MiB
Redis maxmemory     256MiB
```

이 값은 최종 적정값이 아니라 기존 2.78GiB peak를 OOM 없이 다시 검증하기 위한 임시값이다. 전체 hydrate 제거와 검색 경로 정상화 후 backend peak가 2.4GiB 이하이면 3GiB로 낮추고, 2.8GiB 이상이 지속되면 t3.large 단일 구성의 한계로 판단한다.

발표 전에는 FastAPI·Elasticsearch·Redis를 한 EC2에 유지한다. 인프라 분리는 다음 순서로 판단한다.

```text
현재 구성 관측
→ 쿼리·후보군 최적화
→ 필요하면 단일 EC2 상향
→ ES가 독립 병목일 때 ES만 분리
→ Redis/관리형 서비스는 실제 사용량 확인 후 P3 검토
```

Redis는 cache 경로와 eviction이 확인되기 전에는 분리하지 않는다. ES는 heap 75% 이상 지속, rejected request, indexing 시 backend p95 급증, CPU credit 고갈이 반복될 때 분리 실험 대상으로 올린다.

---

# 5. 성능 개선 실험 계획

## 5.1 최적화 판단 원칙

최적화 항목은 도입 목록이 아니라 baseline에서 병목이 확인됐을 때 검증하는 후보로 관리한다. 단일 요청의 40초 지연과 시스템 처리량·connection 문제를 구분해 다음 순서로 실험한다.

```text
구간별 시간·실행계획 측정
→ 쿼리와 인덱스 최적화
→ 반복 read Redis cache
→ connection pool 조정 또는 PgBouncer 검증
→ 필요할 때만 read replica
```

| 최적화 후보 | 판단 | 적용 조건 | Before/After 검증 |
| --- | --- | --- | --- |
| N+1·JOIN·조회 범위 튜닝 | 최우선 | 과다 query/row, slow query 확인 | query 수, DB time, 반환 row, p95/p99 |
| 일반/pgvector 인덱스 | 높음 | Seq Scan, 정렬, vector full scan 확인 | 실행계획, CPU/I/O, latency, Recall@50 |
| Redis cache | 높음 | 원본 쿼리 개선 후 반복 read 확인 | cold/warm p95, hit rate, DB 부하, 정합성 |
| application pool/PgBouncer | 조건부 | connection wait·생성 비용·고갈 확인 | wait p95, connection 수, timeout, transaction 오류 |
| RDS read replica | P3 확장 | 다른 최적화 후에도 read CPU/I/O 지속 포화 | read throughput, replica lag, 비용, 정합성 |

PgBouncer는 느린 쿼리 자체를 빠르게 만드는 수단으로 설명하지 않는다. read replica도 단일 요청 latency가 아니라 읽기 처리량 확장 수단으로 분류한다.

## 5.2 1차 고도화: 홈 전체 hydrate 제거

가설:

> 최종 후보 ID를 먼저 제한하고 필요한 상품만 hydrate하면 DB row 수와 Python sorting 비용이 줄어든다.

검증 지표:

- 홈 p95/p99
- DB 반환 row 수
- slow query/request
- RDS CPU
- 다른 API latency 회귀

목표:

```text
홈 p95 60초 문제 상태 → 동일 환경 After → 목표 1.5초 이하
```

## 5.3 2차 고도화: Elasticsearch/pgvector 경로 정상화

가설:

> 검색과 추천 후보를 top-K로 제한하면 PostgreSQL fallback과 전체 scoring 비용이 줄어든다.

검증 지표:

- ES/pgvector 성공률
- DB fallback 비율
- Recall@50
- 검색 p95/p99
- RDS query 수와 CPU
- `EXPLAIN (ANALYZE, BUFFERS)`와 Seq Scan 여부
- index size와 build time

HNSW/IVFFlat은 pgvector가 실제 candidate retrieval 경로이고 vector full scan이 확인된 경우에만 비교한다. 두 인덱스는 latency뿐 아니라 Recall@50과 RDS CPU/I/O를 함께 측정한다. Elasticsearch가 후보 검색을 담당한다면 ES mapping·filter·top-K와 PostgreSQL fallback 정상화가 우선이다.

## 5.4 3차 고도화: 추천 pipeline 분해

가설:

> intent, retrieval, matching, scoring, save를 분리 측정하고 외부 LLM을 격리하면 실제 추천 core 병목을 확인할 수 있다.

검증 지표:

- `intent_parse_ms`
- `candidate_pool_ms`
- `search_match_ms`
- `scoring_ms`
- `result_save_ms`
- `response_load_ms`

## 5.5 4차 고도화: 상세/인기상품 조회 최적화

- 최종 상품 ID에 대해서만 이미지와 가격 조회
- 상품당 대표 이미지 한 건만 반환
- 최저가 전체 집계 반복 제거
- API당 query 수로 N+1·중복 조회 확인
- 불필요한 JOIN과 반환 row 수 축소
- 원본 쿼리 개선 후 반복 read에 Redis cache 적용
- cache key에 dataset/scoring version 포함
- cold/warm p95, hit rate, TTL, eviction, 무효화 정합성 검증

## 5.6 5차 고도화: connection pool 검증

먼저 SQLAlchemy/application pool의 size, overflow, wait time, active/idle connection을 측정한다. connection wait·생성 비용·고갈이 확인된 경우에만 pool 값을 조정하거나 PgBouncer를 별도 실험한다.

검증 지표:

- connection wait p95
- active/idle/maximum connection
- connection timeout
- API p95/p99
- transaction 오류
- transaction pooling 사용 시 session 상태와 prepared statement 회귀

## 5.7 P3 확장: 읽기 전용 요청 분산

쿼리·인덱스·cache 개선 후에도 RDS read CPU/I/O가 지속 포화될 경우 read replica를 검토한다. replica lag 허용 범위와 eventual consistency가 가능한 API를 먼저 정의하며, 현재 P2의 40초 단일 요청을 해결하는 1차 최적화로 사용하지 않는다.

## 5.8 6차 고도화: Cart/Checkout 동시성

읽기 API가 target을 통과한 뒤 별도 write profile에서 검증한다.

- write p95 1.5초 이하
- 오류율 1% 미만
- 재고·가격·주문 불변식 위반 0건
- transaction/lock timeout 0건

## 5.9 테스트 매트릭스

| 단계 | 데이터 | 부하 | 시간 | 목적 |
| --- | ---: | ---: | ---: | --- |
| Contract preflight | 1천/8만 | API당 1회 | 1분 이내 | route/status/schema 검증 |
| Smoke | 8만 | 1 VU | 1분 | 테스트 도구 검증 |
| Baseline | 8만 | 10 VU | 10분 | 개선 전후 비교 |
| Target | 8만 | 20→50 VU | 각 5분 | P2 목표 부하 검증 |
| Endpoint capacity | 8만 | arrival-rate 증가 | 단계별 5분 | 최대 지속 RPS 산출 |
| Stress | 8만 | 50→100 VU | 각 5분 | 포화점과 회복 확인 |
| Write load | 8만 | 별도 profile | 10분 | 거래 불변식 검증 |
| Soak | 8만 | 10 VU | 60분 | 누수와 장기 안정성 |

각 Before/After는 동일 조건으로 3회 측정하고 p95 중앙값을 대표값으로 사용한다. 세 결과의 편차가 10%를 넘으면 원인을 확인한 뒤 다시 실행한다.

2026-07-10의 1천 건 smoke는 신규 홈 API 계약을 선반영한 k6와 당시 기존 `/api/home/sections`만 제공하던 backend 사이에서 404가 119건 발생했으므로 성능 근거에서 제외한다. 최신 `dev`에는 신규 backend와 contract test가 반영됐지만, 이를 배포하고 migration `20260710_0029`·seed·contract preflight를 통과한 새 실행만 성능 결과로 사용한다.

---

# 6. 서비스 아키텍처와 선택 이유

```text
Vercel / React
      ↓
EC2 t3.large
Caddy → FastAPI
         ├─ Elasticsearch: keyword 후보 검색
         ├─ Redis: cache 적용 준비
         └─ OpenAI: 고민 해석·서술 보조
      ↓
RDS PostgreSQL + pgvector
상품 · 성분 · 효능 · 함량 · 근거 · 사용자 · 주문 · vector 후보

S3 / CloudFront
상품 이미지
```

## 선택 이유

### PostgreSQL

- 추천 근거 데이터와 커머스 transaction을 함께 관리
- 데이터 관계와 계약을 명확히 유지
- pgvector로 semantic candidate retrieval 지원

### Elasticsearch

- 상품명·브랜드·카테고리·성분·효능 keyword 검색
- 가격·브랜드·카테고리 hard filter
- 8만 상품을 scoring하기 전에 top-K 후보 축소

### OpenAI

- 비정형 자연어 고민의 문맥 해석
- 규칙 parser가 놓치는 동의어·부정·복합 표현 보완
- 최종 ranking 결정권은 deterministic scoring engine에 유지

### Redis

- 반복되는 홈/검색/추천 응답 비용을 줄이기 위한 인프라
- 현재 활성 cache 경로는 구현·검증 후 결과에 포함

### P2 배포 경계

- EC2 t3.large 한 대에 Caddy·FastAPI·Elasticsearch·Redis를 유지한다.
- RDS PostgreSQL+pgvector와 S3/CloudFront는 외부 AWS 서비스, frontend는 Vercel을 사용한다.
- ES·Redis를 다른 일반 EC2로 분리하는 작업은 P2 필수 최적화에 포함하지 않는다.
- 자원 경합이 측정되면 먼저 단일 인스턴스 상향을 비교하고, ES만 독립 병목일 때 분리를 검토한다.

### S3/CloudFront

- 상품 이미지 전달을 API 서버와 분리
- 정적 이미지 트래픽이 FastAPI/EC2 자원을 사용하지 않게 구성

---

# 7. 최종 기술적 챌린지

## 챌린지 1. 자연어 고민을 구조화하고 정답 없는 추천을 평가 가능하게 만들기

문제:

- 비정형 고민을 계산 가능한 schema로 바꿔야 한다.
- 추천에는 하나의 정답이 없다.
- 리뷰는 실제 경험이지만 노출·구매·인기 편향이 있다.

접근:

- Rule + LLM hybrid parser
- 표준 고민·효능·구매 조건 schema
- review silver label과 human gold set
- HitRate/MRR/NDCG와 online behavior의 다단계 평가

## 챌린지 2. 논문과 함량을 상품 순위로 바꾸되 설명 가능하게 유지하기

문제:

- 근거의 형태와 신뢰도가 다르다.
- 함량이 높다고 무조건 좋은 것이 아니다.
- score 축이 많아질수록 추천 이유가 불투명해질 수 있다.

접근:

- 성분-효능과 evidence score 분리
- meaningful/optimal/excessive 함량 구간
- 피부 적합도와 위험 penalty
- scoring version, weight profile, evidence 저장
- ablation으로 근거와 함량의 실제 기여 검증

## 챌린지 3. 8만 상품에서도 실시간 추천하기

문제:

- 최종 10개를 위해 상품 7.9만 건과 성분 수십만 행을 읽었다.
- 홈 p95 60초, 추천 52초, 검색 32초까지 증가했다.
- retrieval 장애가 PostgreSQL fallback 부하로 전파됐다.

접근:

- Elasticsearch/pgvector top-K candidate retrieval
- 후보 ID 선별 후 필요한 데이터만 hydrate
- 추천 stage별 latency 관측
- VU user journey와 arrival-rate capacity test 분리
- 동일 조건 3회 측정으로 개선 원인 검증

---

# 8. 최종 성과 작성 형식

## 8.1 보고서 첫 화면

```text
결론

상품 8만 건, t3.large, 50 VU, 10분 기준

추천 품질
- Review HitRate@10: Popularity baseline A → 전체 scoring B
- MRR@10: A → B
- Concern-group NDCG@10: A → B
- Hard constraint violation: A% → 0%
- Top-5 evidence path coverage: A% → B%

시스템 성능
- 전체 p95: A초 → B초
- 오류율: A% → B%
- HTTP 처리량: A req/s → B req/s
- 최대 지속 처리량: A req/s → B req/s
- OOM/restart: 0건
```

## 8.2 개선 단계별 기록

```text
## N차 고도화: 변경 제목

### 테스트 조건
- Git SHA
- 데이터 건수
- 인스턴스
- profile/부하/시간
- LLM 및 cache 상태

### 문제 상황
- 사용자 증상
- p95/p99
- 오류율과 처리량
- 병목 query/stage

### 가설
- 왜 느리거나 부정확하다고 판단했는가
- 어떤 KPI가 변하면 가설이 맞는가

### 변경 사항
- 코드/쿼리/인덱스/scoring 변경

### 검증 결과
| KPI | Before | After | 변화율 | 목표 | 판정 |
| --- | ---: | ---: | ---: | ---: | --- |
| HitRate@10 | | | | | |
| NDCG@10 | | | | | |
| p95 | | | | | |
| 오류율 | | | | | |
| HTTP req/s | | | | | |
| DB fallback | | | | | |

### 부작용과 회귀
- 다른 고민/카테고리 추천 품질
- hard constraint 위반
- latency와 memory 증가
- cache 정합성

### 결론
- 가설 채택/기각
- 다음 병목
```

## 8.3 발표에서 사용할 최종 한 문장

> 뭐바를래는 성분이 들어 있는지를 보여주는 데서 끝나지 않고, 고민에 필요한 효능과 함량·근거를 계산해 상품 순위를 만들었습니다. 리뷰에서 복원한 실제 고민으로 추천 적합성을 검증하고, 8만 상품에서도 이 결과를 실시간으로 제공하도록 파이프라인을 최적화했습니다.

---

# 9. 발표 전 완료 체크리스트

## 추천 품질

- [ ] 리뷰 사용 권한 확인 및 개인정보 제거
- [ ] 리뷰의 사용 전 고민과 사용 후 긍정·부정 경험 분리
- [ ] 상품명·브랜드명·정답 노출 표현 제거
- [ ] review train/dev/test 또는 고정 test 분리
- [ ] Product mapping rate와 label coverage 계산
- [ ] Concern extraction/Effect sentiment precision 표본 검수
- [ ] Leakage rate 0% 확인
- [ ] Human agreement(Cohen's κ) 계산
- [ ] relevance grade 분포와 제외 사유 기록
- [ ] head/mid/tail popularity 구간별 결과 계산
- [ ] HitRate@10, MRR@10, Recall@50 계산
- [ ] Concern-group NDCG@10과 Negative exposure@10 계산
- [ ] 인기순·BM25·성분-only·근거·함량 ablation 실행
- [ ] gold set F1, constraint accuracy, NDCG 계산
- [ ] Top-5 evidence path coverage 계산
- [ ] 함량 전체 coverage와 판정 성공률 분리

## 시스템 성능

- [ ] k6 route와 최신 API 계약 일치
- [ ] t3.large, 8만 건 smoke PASS
- [ ] 동일 조건 Before/After 3회 실행
- [ ] p95/p99, error rate, req/s, iterations/s 기록
- [ ] ES/pgvector/fallback 비율 기록
- [ ] 추천 stage duration 기록
- [ ] RDS/EC2/ES/Redis 자원 지표 기록
- [ ] OOM/restart/connection 고갈 없음

## 발표 자료

- [ ] 목표값과 측정 완료값 시각적으로 구분
- [ ] 최초 t3.xlarge 실패 수치와 최종 t3.large 결과를 직접 비교하지 않음
- [ ] 개선되지 않은 값은 `측정 중`으로 표시
- [ ] 모든 결과에 Git SHA와 report 경로 연결
- [ ] 행동 개인화 효과를 검증 완료로 과장하지 않고 Redis cache는 미구현으로 구분
- [ ] 논문 근거를 제품 자체 임상 검증으로 표현하지 않음

---

# 근거 파일

- 최초 8만 건 결과: `perf-runs/20260708-113413_baseline_full-80000/report.md`
- 최초 결과 분석: `perf-runs/20260708-113413_baseline_full-80000/baseline-analysis.md`
- k6 사용자 여정: `tests/k6/commerce-smoke.js`
- 부하테스트 실행/리포트: `scripts/perf/`
- 추천 pipeline: `apps/backend/app/services/recommendation_pipeline.py`
- 후보 추출: `apps/backend/app/services/candidate_pool.py`
- 상품 검색: `apps/backend/app/services/product_search_service.py`
- 추천 scoring: `apps/backend/app/services/scoring.py`
- 추천 API schema: `apps/backend/app/schemas/recommendation.py`
- 발표 PPT 구성안: `docs/final-presentation-outline-draft.md`
