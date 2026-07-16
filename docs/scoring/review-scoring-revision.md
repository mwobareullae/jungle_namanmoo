# 리뷰 스코어링 실데이터 정합 개정

이 문서는 `review_quality_v3`와 리뷰 프로필 affinity의 실제 계산 계약을 기록합니다. 리뷰는 성분 효능의 임상 근거가 아니라 상품 사용 경험과 유사 프로필 반응을 보조하는 별도 신호입니다.

## 상품 리뷰 품질

리뷰 1건의 가중치는 다음과 같습니다.

```text
review_weight = scoring_eligibility × month_use_weight
              × verified_weight × helpful_weight

helpful_weight = 1 + 0.10 × min(log(1 + helpful_count) / log(21), 1)
```

- 자사몰 `source=mubarelle`: `scoring_eligibility=0`. 리뷰 원문·목록·공개 요약에는 남기지만 상품 품질, 카테고리 prior, 프로필 affinity에는 사용하지 않습니다.
- OliveYoung seed: `month_use_weight=1.0`, `verified_weight=1.0`. 현재 전량 한달후기이고 구매인증 원본값이 없어 변별 신호로 쓰지 않습니다.
- 기타 외부 소스는 신호의 실재가 확인된 경우 한달사용 `1.15`, 구매확인 `1.10`을 적용합니다.
- 작성일과 사진 존재 표식은 정보·표시·진단용으로 보존하지만 점수에는 사용하지 않습니다.

점수 대상 외부 리뷰에 한해 카테고리 prior strength 20으로 별점·재구매율의 Bayesian 값을 구합니다. 상품 품질 신호는 다음 가중 평균입니다.

```text
quality_signal = available_weighted_average(
  rating_score          × 0.80,
  repurchase_score      × 0.20
)

confidence = n_eff / (n_eff + 20)
review_quality_score = clamp(0.5 + confidence × (quality_signal - 0.5), 0, 1)
```

없는 신호는 0.5로 채우지 않고 분모에서 제외합니다. 일반/한달 후기 일관성 값은 진단용 컬럼에 남지만 품질 합성에는 들어가지 않습니다.

사진 표식은 상품 정보와 데이터 QA를 위해 집계할 수 있지만 품질점수에는 반영하지 않습니다.

## 프로필 affinity

```text
SKIN_TYPE    0.45
SENSITIVITY  0.15
SKIN_CONCERN 0.40
```

실제 타깃이 생긴 차원만 분모에 포함해 재정규화합니다. 원천 데이터에서 생성 가능한 민감도 segment는 `high`뿐이므로 사용자 민감도가 높음일 때만 `SENSITIVITY=high` 타깃을 만듭니다. 낮음·보통은 민감도 차원을 중립 0.5로 끼워 넣지 않고 제외합니다. 모든 차원에 타깃이 없으면 최종 affinity는 0.5입니다.

segment effective sample size가 5 미만이면 원래 값은 진단 정보에 남기되 추천 기여는 0.5로 처리합니다.

자사몰 `mubarelle` 리뷰의 프로필 라벨은 원본 정보로 보존하지만 affinity segment 집계에서는 제외합니다.

## 배포 계약

1. v3 코드 배포. DB migration은 없습니다.
2. `rollup_product_reviews --full` 실행
3. v3 행 수와 0~1 범위 확인
4. 저장된 추천 결과·캐시 무효화 여부 확인

DB 테이블·컬럼·API 구조는 바꾸지 않습니다. v7 추천 로더는 `score_version=review_quality_v3`인 행만 사용하므로 전체 rollup 전의 이전 버전 행은 중립 처리됩니다. 배포 완료 판정에는 기존 `score_version` 컬럼을 사용합니다.
