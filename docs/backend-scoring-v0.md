# 백엔드 추천 스코어링 v0

이 문서는 현재 백엔드가 실제 추천 API에서 사용하는 점수 계산식을 기록한다.
값은 MVP 검증용 기본값이며, 팀 합의 후 조정 가능해야 한다.

## 총점 공식

```text
total_score =
  ingredient_effect_score   * 0.35
+ ingredient_evidence_score * 0.25
+ skin_profile_score        * 0.15
+ concentration_fit_score   * 0.08
+ functional_claim_score    * 0.05
+ search_match_score        * 0.07
+ price_score               * 0.05
- risk_penalty
```

- 각 축 점수는 기본적으로 `0.0~1.0`이다.
- API 응답의 `score_breakdown`은 프론트가 읽기 쉽게 `0~100` 정수로 변환된다.
- `risk_penalty`는 총점에서 직접 차감되는 점수다.

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

- 축별 weight: 효능, 근거, 피부, 함량, 기능성, 검색, 가격
- 기능성 claim 기본점과 매칭점
- 함량 bucket 점수
- confidence 보정 강도
- 민감도 risk penalty 매핑과 cap
- `source_authority_score` 산정 기준
