# 백엔드 추천 스코어링 v6

이 문서는 현재 백엔드가 실제 추천 API에서 사용하는 점수 계산식을 기록한다.
현재 scoring version은 `v6_independent_evidence_top3`이다. 아래 값은 동적 배수를 적용하기 전 기본 가중치다.

## 총점 공식

```text
raw_score =
  ingredient_effect_score       * 0.26
+ ingredient_evidence_score     * 0.18
+ skin_profile_score            * 0.11
+ concentration_fit_score       * 0.07
+ functional_claim_score        * 0.04
+ search_match_score            * 0.06
+ price_score                   * 0.03
+ market_signal_score           * 0.02
+ skin_test_context_score       * 0.04
+ behavior_personalization      * 0.07
+ review_quality_score          * 0.07
+ review_profile_affinity_score * 0.05

total_score = clamp(raw_score, 0, 1) * 100 - risk_penalty
```

- 각 축 점수는 기본적으로 `0.0~1.0`이다.
- API 응답의 `score_breakdown`은 프론트가 읽기 쉽게 `0~100` 정수로 변환된다.
- `risk_penalty`는 총점에서 직접 차감되는 점수다.
- skin-test나 행동 컨텍스트가 없으면 해당 축을 0으로 두고 활성 축을 다시 정규화한다.
- 카테고리·브랜드처럼 강한 상품 검색 의도가 있으면 review `0.07/0.05`는 유지하고 기존 검색 프로필의 비리뷰 축 상대 비율을 88% 안에서 보존한다.

## 리뷰 점수

`review_quality_score`는 `product_review_metrics`의 전체 상품 품질이다. 집계 버전은 `review_quality_v2`이며 별점 75%, 재구매 20%, Bayesian 사진리뷰율 5%를 사용한다. 값이 없는 신호는 가중치 분모에서 제외하고, effective sample confidence로 최종값을 0.5 쪽에 보수 보정한다. 일반/한달 후기 일관성은 진단값으로만 보존한다.

`review_profile_affinity_score`는 상품 전체 대비 유사 프로필 segment의 상대 반응이다.

```text
skin type  0.45
sensitivity 0.15
concern    0.40
```

- 명시 요청·수동 프로필·현재 검색 고민: 강도 `1.0`
- 저장 고민: 강도 `0.75`
- 스킨테스트 추론: 강도 `0.25`
- 원천 segment가 존재하는 `SENSITIVITY=high`만 민감도 타깃으로 사용합니다. 낮음·보통은 민감도 타깃을 만들지 않습니다.
- 실제 타깃이 있는 차원만 위 가중치로 재정규화합니다. 타깃이 전혀 없으면 중립 `0.5`입니다.
- segment effective sample size가 5 미만이면 저장값은 breakdown에 남기되 점수 기여는 `0.5`다.
- segment와 상품 지표는 후보 전체를 bulk query로 읽으며 리뷰 원문은 추천 요청에서 조회하지 않는다.

스킨테스트 구매 기준이 `review`이면 quality `1.35`, affinity `1.15`를 곱한다. 결정 트리거가 `similar_review`이면 quality `1.10`, affinity `1.60`을 곱한다. 배수 적용·정규화 후 두 리뷰 축 합은 최대 `0.18`이다. 이 선택은 `market_signal` 배수를 변경하지 않는다.

## 성분 효능 점수

- 사용자 고민을 효능 축으로 바꾼 뒤, 효능별 관련 성분 상위 3개를 본다.
- 상위 3개 성분 감쇠값은 `1.0 / 0.5 / 0.25`다.
- 효능별 합산은 `cap=1.2`를 적용하고, 최종 축 점수는 `0.0~1.0`으로 clamp한다.
- 사용자가 우선순위 효능을 명확히 말한 경우 해당 효능 weight에 `1.25`를 곱한다.

## 성분 근거 점수

```text
adjusted_evidence = evidence_score / 100 * source_authority_score
```

- `evidence_score`는 성분 근거 CSV의 원 점수다.
- `source_authority_score`는 논문, 고시, 출처 신뢰도를 반영하는 보정값이다.
- 같은 성분/효능에 근거가 여러 개 있으면 보정 후 점수가 높은 근거를 대표로 사용한다.
- 상품의 효능축별 성분근거는 `adjusted_evidence`가 높은 성분 3개를 성분효능 top3와
  독립적으로 선발한다.
- 독립 근거 top3에도 `1.0 / 0.5 / 0.25` 감쇠와 `cap=1.2`, 최종 `1.0` clamp를 적용한다.
- 고객 설명용 `score_evidence`, 추천 사유, `key_ingredients`는 효능점수에 기여한 effect
  top3를 사용한다. 이는 숫자상 `ingredient_evidence_score`를 계산한 근거 top3와 별도다.

## 함량 점수

함량은 벌점이 아니라 독립 축이다. 함량을 공개하지 않은 상품도 0점은 아니지만,
유효 범위와 신뢰도까지 확인된 상품이 더 높은 점수를 받는다.

```text
unknown             0.50
below_meaningful    0.55
meaningful          0.75
optimal             1.00
above_optimal       0.80
excessive           0.60
```

- `unknown`: 함량 미공개 또는 계산 범위 없음
- `below_meaningful`: 유효 최소치 미만
- `meaningful`: 의미 있는 함량
- `optimal`: 적정 함량
- `above_optimal`: 적정보다 높지만 과다 기준은 아님
- `excessive`: 과다 기준 이상, 주의 문구 표시

함량 점수는 `concentration_confidence`와 `range_confidence` 중 더 낮은 신뢰도에 맞춰
0.5 기준점으로 보수 보정한다.

```text
high    1.0
medium  0.8
low     0.5
unknown 0.0

adjusted_score = 0.5 + (raw_score - 0.5) * confidence_multiplier
```

## 피부 타입 점수

- `product_skin_profiles.csv`의 피부 타입별 fit 값을 우선 사용한다.
- 피부타입 점수와 민감도 점수를 `0.6 / 0.4`로 합성한다.
- `confidence`가 낮으면 함량과 같은 방식으로 0.5 기준점 쪽으로 보수 보정한다.

## 기능성 화장품 점수

기능성 화장품 판정은 사용자 고민 효능과 맞을 때만 강하게 반영한다.

```text
0.00 기능성 아님
0.20 기능성 confirmed지만 claim 없음 또는 사용자 효능과 불일치
0.75 claim이 사용자 효능과 일치
1.00 claim이 사용자 우선순위 효능과 일치
```

현재 claim 매핑:

```text
미백     -> effect_brightening
주름개선 -> effect_wrinkle
```

`functional_claim_confidence`가 낮으면 0.2 기준점으로 보수 보정한다.

## Risk 정책

- 모든 사용자에게 risk 성분 주의 문구는 표시한다.
- 일반 사용자에게는 점수 감점을 하지 않는다.
- 민감도 입력이 `높음`이고, risk flag의 `applies_to`에 `sensitive`가 있으면 감점한다.
- 같은 `risk_type`이 여러 번 나오면 가장 큰 감점만 사용한다.
- 감점 총합 cap은 `8점`이다.

```text
high   -6
medium -3
low    -1
```

## API 노출 항목

추천 목록과 상품 상세의 `score_breakdown`에는 다음 주요 항목이 노출된다.

```text
ingredient_effect_score
ingredient_evidence_score
functional_claim_score
concentration_fit_score
concentration_bucket
concentration_warning
skin_profile_score
skin_type_score
sensitivity_score
price_score
keyword_score
vector_score
search_match_score
market_signal_score
review_quality_score
review_quality_applied
review_quality_confidence
review_count
review_profile_affinity_score
review_profile_affinity_applied
review_profile_affinity_dimensions
review_profile_matched_segments
skin_test_context_score
skin_test_context_applied
skin_test_context_axes
skin_test_context_matched_axes
skin_test_context_query_conflict_axes
skin_test_context_manual_conflict_axes
behavior_personalization_score
behavior_personalization_applied
behavior_personalization_sources
behavior_personalization_source_scores
behavior_personalization_affinity_components
behavior_personalization_negative_guard_score
behavior_personalization_event_counts
base_weights
adjusted_weights
applied_multipliers
risk_penalty
risk_flag_count
risk_warnings
risk_policy
```

## 조정 필요 후보

- 축별 weight: 효능, 근거, 피부, 함량, 기능성, 검색, 가격, 인기, 스킨테스트, 행동, 리뷰 품질, 리뷰 affinity
- 기능성 claim 기본점과 매칭점
- 함량 bucket 점수
- confidence 보정 강도
- 민감도 risk penalty 매핑과 cap
- `source_authority_score` 산정 기준
