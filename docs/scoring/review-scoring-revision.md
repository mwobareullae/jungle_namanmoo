# 리뷰 스코어링 실데이터 정합 개정

이 문서는 `review_quality_v2`와 리뷰 프로필 affinity 개정의 실제 계산 계약을 기록합니다. 리뷰는 성분 효능의 임상 근거가 아니라 상품 사용 경험과 유사 프로필 반응을 보조하는 별도 신호입니다.

## 상품 리뷰 품질

리뷰 1건의 가중치는 다음과 같습니다.

```text
review_weight = source_weight × month_use_weight × verified_weight
              × helpful_weight × recency_weight

helpful_weight = 1 + 0.10 × min(log(1 + helpful_count) / log(21), 1)
recency_weight = 0.5 + 0.5 × 2^(-age_days / 730)
```

- OliveYoung seed: `month_use_weight=1.0`, `verified_weight=1.0`. 현재 전량 한달후기이고 구매인증 원본값이 없어 변별 신호로 쓰지 않습니다.
- 자사몰 구매 리뷰: `review_type=GENERAL`, 실제 주문이 확인된 `verified_purchase=true`에 `1.10`을 적용합니다.
- 작성일이 없으면 `recency_weight=0.75`입니다.

카테고리 prior strength 20으로 별점·재구매율·사진리뷰율의 Bayesian 값을 구합니다. 상품 품질 신호는 다음 가중 평균입니다.

```text
quality_signal = available_weighted_average(
  rating_score          × 0.75,
  repurchase_score      × 0.20,
  photo_rate_score      × 0.05
)

confidence = n_eff / (n_eff + 20)
review_quality_score = clamp(0.5 + confidence × (quality_signal - 0.5), 0, 1)
```

없는 신호는 0.5로 채우지 않고 분모에서 제외합니다. 일반/한달 후기 일관성 값은 진단용 컬럼에 남지만 품질 합성에는 들어가지 않습니다.

현재 seed 851,429건 중 사진 표식 true는 115,723건(13.591621%)입니다. `photo_rate_score`는 이 비율을 높고 낮음 그대로 반영하는 작은 5% 축이며, 효능 증거로 해석하지 않습니다.

## 프로필 affinity

```text
SKIN_TYPE    0.45
SENSITIVITY  0.15
SKIN_CONCERN 0.40
```

실제 타깃이 생긴 차원만 분모에 포함해 재정규화합니다. 원천 데이터에서 생성 가능한 민감도 segment는 `high`뿐이므로 사용자 민감도가 높음일 때만 `SENSITIVITY=high` 타깃을 만듭니다. 낮음·보통은 민감도 차원을 중립 0.5로 끼워 넣지 않고 제외합니다. 모든 차원에 타깃이 없으면 최종 affinity는 0.5입니다.

segment effective sample size가 5 미만이면 원래 값은 진단 정보에 남기되 추천 기여는 0.5로 처리합니다.

## 배포 계약

1. v2 코드 배포. DB migration은 없습니다.
2. `rollup_product_reviews --full` 실행
3. v2 행 수와 0~1 범위 확인
4. 저장된 추천 결과·캐시 무효화 여부 확인

Bayesian 사진리뷰율은 rollup 중 계산해 기존 `review_quality_score`에 합성하며 별도 DB 컬럼으로 저장하지 않습니다. 원본 리뷰에서 언제든 재현할 수 있습니다. 전체 rollup이 끝나기 전에는 v1과 v2가 함께 존재할 수 있으므로 배포 완료 판정에 기존 `score_version` 컬럼을 사용합니다.
