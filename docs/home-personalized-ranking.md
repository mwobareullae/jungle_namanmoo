# Home Personalized Ranking Draft

## 목적

로그인 사용자는 피부 타입, 민감도, 저장된 고민/회피 성분을 가질 수 있습니다. 따라서 로그인 홈은 비로그인 홈의 `추천 예시 상품`을 그대로 쓰지 않고, 사용자 프로필을 반영한 `프로필 기반 홈 추천`으로 대체합니다.

이 문서는 프론트 화면 설계가 아니라 R4 AI/추천 영역의 상품 선별 기준입니다.

## 비로그인 홈과 차이

| 상태 | 홈 상품 기준 | 문구 원칙 |
|---|---|---|
| 비로그인 | 개인화 전 cold-start 후보 | 추천 예시 |
| 로그인 + 피부 프로필 없음 | cold-start 후보 + 프로필 입력 CTA | 추천 예시 |
| 로그인 + 피부 프로필 있음 | skin profile + concern effect + 성분 근거 + 함량 coverage | 맞춤 후보 |
| 로그인 + 행동 이력 있음 | 프로필 기반 추천에 최근 본/찜/장바구니 신호를 약하게 보정 | 맞춤 후보 |

P2 1차에서는 행동 이력까지 쓰지 않고, 피부 프로필과 고민축만 사용합니다.

## P2 입력값

| 입력 | 소유 | P2 사용 |
|---|---|---|
| `member_id` | Commerce/Auth | 로그인 사용자 식별. 추천 계산 자체에는 직접 사용하지 않음 |
| `skin_type` | User profile | 건성, 지성, 복합성, 중성, 수부지 |
| `sensitivity` | User profile | 보통, 민감 |
| `concern_effect_ids` | AI/Profile | 사용자의 고민을 6효능축으로 변환한 값 |
| `avoid_ingredient_ids` | User profile | 사용자가 피하고 싶은 성분. P2에서는 hard exclude |

## P2 노출 섹션

| 섹션 | 설명 | 기준 |
|---|---|---|
| `profile_focus` | 내 피부 기준 추천 | 고민축, 피부 타입, 민감도, 성분 근거, 함량 coverage, 가격을 모두 반영한 종합 추천 |
| `market_popular` | 지금 인기 있는 제품 | 리뷰수, 평점, 판매량/판매랭킹, 최근 행동 신호를 본 시장 인기 후보 |
| `evidence_confident` | 근거가 뚜렷한 추천 | 함량 표기와 성분 근거가 비교적 선명해 설명하기 좋은 후보 |
| `price_value` | 가격까지 좋은 추천 | 개인화 후보 중 가격 접근성까지 함께 본 후보 |

민감도는 별도 섹션으로 분리하지 않습니다. `profile_focus` 점수 안에서 이미 `sensitivity_fit_score`와 `risk_penalty`로 반영합니다. 별도 `민감도 고려` 섹션을 만들면 첫 번째 종합 추천이 민감도를 고려하지 않은 것처럼 보일 수 있으므로 P2 회원 홈에서는 제외합니다.

`market_popular`는 시장 인기 신호가 들어온 뒤에만 산출합니다. 현재 `products.csv`, `product_prices.csv`, `product_inventory.csv`만으로는 판매량·리뷰수·평점을 알 수 없으므로, 가격이나 이미지 존재 여부를 인기처럼 포장하지 않습니다.

## 기본 필터

상품은 아래 조건을 모두 만족해야 로그인 홈 후보가 됩니다.

- `products.is_recommendable = true`
- 가격 존재
- 대표 이미지 존재
- 상품 성분 데이터 존재
- P2 홈 범위에서는 `product_id`가 `prod_oy_`로 시작하는 국내/올리브영 기반 상품만 사용
- 사용자의 `avoid_ingredient_ids`에 걸린 상품은 제외

주의: `data/product_inventory.csv`는 현재 `AUTO_SEED` mock 재고이므로 로그인 홈 후보 산출에도 사용하지 않습니다.

## 점수 요소

| 요소 | 설명 |
|---|---|
| `axis_score` | 해당 효능축과 연결된 canonical ingredient의 effect_score와 성분 표시 순서 |
| `coverage_score` | `concentration_coverage_estimates.csv`의 exact/range/regulatory_anchor 등 함량 관련 정보 |
| `profile_fit_score` | `product_skin_profiles.csv`의 피부 타입별 적합도 |
| `sensitivity_fit_score` | `product_skin_profiles.csv`의 민감 피부 적합도 |
| `price_score` | 홈 노출에 적합한 가격 접근성 |
| `market_popularity_score` | 리뷰수, 평점, 판매량/판매랭킹, 최근 행동 신호를 결합한 인기 점수 |
| `risk_penalty` | 민감 사용자는 risk flag 성분을 더 강하게 감점 |

## 섹션별 점수식

모든 점수는 0~100 스케일로 정규화한 뒤 계산합니다.

```text
profile_focus =
  axis_score * 0.45
  + coverage_score * 0.18
  + profile_fit_score * 0.25
  + sensitivity_fit_score * 0.05
  + price_score * 0.07
  - risk_penalty

evidence_confident =
  axis_score * 0.35
  + coverage_score * 0.35
  + profile_fit_score * 0.15
  + sensitivity_fit_score * 0.05
  + price_score * 0.10
  - risk_penalty

price_value =
  axis_score * 0.30
  + coverage_score * 0.12
  + profile_fit_score * 0.20
  + sensitivity_fit_score * 0.08
  + price_score * 0.30
  - risk_penalty
```

`price_value`는 사용자의 `secondary_effect_id`까지 열어 가격 접근성이 좋은 보조 후보를 찾습니다. 예를 들어 `수부지·잡티` 사용자는 미백·톤을 1순위로 보되, 가격 좋은 보습·장벽 후보도 세 번째 섹션에 노출할 수 있습니다.

## 인기 섹션 점수식

`market_popular`는 개인 맞춤 점수를 다른 이름으로 다시 보여주는 섹션이 아닙니다. 시장에서 실제로 많이 검증된 상품을 보여주는 탐색 섹션입니다.

미래 mock 또는 크롤링 데이터는 `data/product_market_signals.csv`에 아래 형태로 들어올 수 있습니다.

| 컬럼 | 의미 |
|---|---|
| `product_id` | 상품 ID |
| `review_count` | 리뷰 수 |
| `average_rating` | 평균 평점, 0~5 스케일 |
| `sales_count` | 판매량. 있으면 가장 직접적인 인기 신호 |
| `sales_rank` | 판매 랭킹. `sales_count`가 없을 때 사용, 낮을수록 좋음 |
| `recent_view_count` | 최근 14일 조회 수 |
| `wishlist_count` | 최근 14일 찜 수 |
| `cart_add_count` | 최근 14일 장바구니 담기 수 |
| `source` | 데이터 출처 또는 mock 출처 |
| `updated_at` | 스냅샷 시점 |

점수식:

```text
market_popularity_score =
  review_count_score * 0.30
  + bayesian_rating_score * 0.25
  + sales_score * 0.30
  + recent_signal_score * 0.15
```

구현 원칙:

- 리뷰수·판매량·최근 행동 수치는 `log1p` 정규화로 스케일을 줄입니다.
- 평점은 리뷰 수가 적은 5.0 상품이 과대평가되지 않도록 Bayesian 보정을 사용합니다. `confidence_reviews = 50`으로 시작합니다.
- `sales_count`가 있으면 우선 사용하고, 없으면 `sales_rank`를 log 기반 역순 점수로 사용합니다.
- 최근 행동 신호는 14일 rolling window 기준입니다. 기간 제한이 없으면 최근 관심도가 아니라 누적 관심도가 되므로 P2 계약에서는 14일로 고정합니다.
- 없는 점수 요소는 0점 처리하지 않고, 남은 요소의 가중치를 재정규화합니다.
- `product_inventory.csv`는 현재 `AUTO_SEED` mock 재고이므로 인기 신호로 사용하지 않습니다.
- 회원 홈에서도 `avoid_ingredient_ids`에 걸리는 상품은 인기 섹션에서 제외할 수 있습니다.

세부 계산:

```text
review_count_score =
  100 * log1p(review_count) / log1p(max_review_count)

adjusted_rating =
  review_count / (review_count + 50) * average_rating
  + 50 / (review_count + 50) * global_average_rating

bayesian_rating_score =
  adjusted_rating / 5 * 100

sales_score =
  if sales_count exists:
    100 * log1p(sales_count) / log1p(max_sales_count)
  else:
    100 * (1 - log1p(sales_rank - 1) / log1p(max_sales_rank - 1))

recent_signal_raw =
  recent_view_count
  + wishlist_count * 3
  + cart_add_count * 5

recent_signal_score =
  100 * log1p(recent_signal_raw) / log1p(max_recent_signal_raw)
```

가중치 변경 이력:

- v1 draft: `review_count_score 0.35`, `recent_signal_score 0.10`
- v2 current: `review_count_score 0.30`, `recent_signal_score 0.15`
- 변경 이유: 외부 인기 신호만으로 고정 랭킹이 되지 않도록, 향후 내부 행동 신호(조회·찜·장바구니)의 반영 여지를 조금 늘림

## 다양성 규칙

- 같은 시나리오 안에서 같은 상품은 한 번만 노출
- 한 섹션 안에서 같은 브랜드는 1개만 노출
- 한 섹션 안에서 같은 카테고리는 최대 2개까지만 노출
- `market_popular`가 산출되면 같은 시나리오 안에서 다른 개인화 섹션과 상품이 중복되지 않게 먼저 점유합니다.
- 동점이면 아래 순서로 고정 정렬

```text
personalized_home_score desc
axis_score desc
coverage_score desc
profile_fit_score desc
risk_penalty asc
price asc
category asc
brand asc
product_id asc
```

동일한 입력 데이터와 동일한 스크립트 버전이면 누가 실행해도 같은 후보가 나와야 합니다.

## 산출물

대표 프로필 시나리오 4개를 두고 샘플 산출물을 생성합니다. 이 파일은 실제 사용자 데이터가 아니라 로직 검수용 fixture입니다.

- `data/scripts/build_home_personalized_candidates.py`
- `data/scripts/home_market_popularity.py`
- `data/reconciliation/home_personalized_profile_candidates.csv`

대표 시나리오:

| 시나리오 | 피부 타입 | 민감도 | 주 고민축 |
|---|---|---|---|
| `dry_sensitive_barrier` | 건성 | 민감 | 보습·장벽 |
| `oily_acne_sebum` | 지성 | 보통 | 여드름·피지 |
| `dehydrated_oily_brightening` | 수부지 | 보통 | 미백·톤 |
| `combination_sensitive_calming` | 복합성 | 민감 | 진정 |

## 재계산 방법

```bash
python data/scripts/build_concentration_coverage_estimates.py
python data/scripts/build_home_personalized_candidates.py
```

## 현재 검토 포인트

- `oily_acne_sebum` 시나리오는 P2 국내 상품 범위에서 15개를 모두 채우지 못하고 14개만 산출됩니다. 이는 여드름·피지 축 특화 성분(BHA, Zinc PCA, Tea Tree 등)이 충분한 국내 후보가 아직 얇다는 신호입니다.
- `data/product_market_signals.csv`가 아직 없으면 `market_popular` 섹션은 산출되지 않습니다. mock 인기 지표가 추가되면 같은 스크립트에서 자동으로 붙습니다.
- 행동 이력 기반 보정은 P2 1차에서는 제외합니다. 최근 본 상품, 찜, 장바구니 신호는 이벤트 로그/커머스 데이터가 안정된 뒤 P3에서 약한 보정값으로 추가합니다.
- 로그인 홈은 추천 API 결과를 대체하지 않습니다. 사용자가 새 고민을 직접 입력하면 `/api/recommendations` 결과가 우선입니다.
