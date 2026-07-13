# Home Cold-start Ranking Draft

## 목적

첫 방문자는 아직 피부 고민, 피부 타입, 민감도, 구매 이력이 없습니다. 이 상태에서 홈 상품을 `맞춤 추천`으로 부르면 안 됩니다. 홈에는 개인화 전 단계의 `추천 예시 상품`만 노출합니다.

## P2 홈 노출 섹션

P2 홈에는 아래 3개 섹션만 우선 노출합니다.

- 보습·장벽 예시
- 진정 예시
- 미백·톤 예시

이 3개 섹션은 첫 방문자에게 보여도 비교적 안전하고, 상품 포지션과 성분 근거가 잘 맞습니다.

`지금 인기 있는 제품` 섹션은 시장 인기 지표가 들어오면 함께 노출합니다. 단, 현재 기본 상품 데이터에는 판매량·평점·리뷰수 지표가 없으므로 지금 산출물에는 포함하지 않습니다.

## 2차 후보 섹션

- 여드름·피지 예시
- 주름·탄력 예시
- 각질 예시

위 3개 섹션은 P2 첫 화면에서는 보류합니다.

- 여드름·피지: BHA, Zinc PCA, Tea Tree 같은 축 특화 성분 후보를 더 보강한 뒤 노출합니다.
- 주름·탄력: 미백 포지션 상품이 아데노신 때문에 주름 섹션에 올라오는 경우를 더 걸러야 합니다.
- 각질: 레티놀 상품이 각질 후보로 잡히는 문제가 있어 AHA/BHA/PHA 중심으로 로직을 보정해야 합니다.

## 기본 필터

상품은 아래 조건을 모두 만족해야 홈 예시 후보가 됩니다.

- `products.is_recommendable = true`
- 가격 존재
- 대표 이미지 존재
- 상품 성분 데이터 존재

주의: `data/product_inventory.csv`는 P2 커머스 흐름 검증용 `AUTO_SEED` mock 재고입니다. 실제 판매 재고가 아니므로 홈 콜드스타트 추천 후보 산출과 점수에는 사용하지 않습니다.

## 점수 요소

| 요소 | 설명 |
|---|---|
| 축별 성분 근거 | 해당 효능축과 연결된 canonical ingredient의 effect_score와 성분 표시 순서를 반영합니다. |
| 함량 coverage | 직접 함량, 고시 범위, 기능성 앵커, 법정 상한, 1% 마커 등 `concentration_coverage_estimates.csv`의 함량 관련 정보 부여 타입을 반영합니다. |
| 가격 접근성 | 8천~3만5천원 구간을 홈 예시 상품에 적합한 가격대로 봅니다. |
| 시장 인기 | 리뷰수, 평점, 판매량/판매랭킹, 최근 행동 신호가 들어오면 `market_popular` 섹션에만 사용합니다. |
| 위험성 페널티 | risk_flags가 걸린 성분은 개인화 전 홈 노출에서 `severity_score * 5`만큼 감점합니다. |
| 다양성 제한 | 한 섹션 안에서 같은 브랜드 1개, 같은 카테고리 최대 2개까지 노출합니다. |
| 상품 포지션 | 상품명/포지션이 해당 섹션과 맞는지 함께 봅니다. 성분만 맞아도 상품명이 다른 효능축으로 보이면 제외합니다. |

## 함량 coverage v2 반영

`화장품 전성분 함량 정보 부여율(Coverage) 추정 로직 설계서 v2`를 홈 후보 산출 앞단에 반영했습니다.

산출 파일:

- `data/reconciliation/concentration_coverage_estimates.csv`

현재 구현한 coverage 타입:

| 타입 | 홈 후보 반영 방식 |
|---|---|
| `exact` | 상품 원문/OCR성 수치가 `product_ingredients.csv`에 직접 잡힌 경우. matched ingredient에 강한 가산 |
| `range` | 기능성 표시와 고시 범위가 맞는 경우. exact는 아니므로 중간 가산 |
| `regulatory_anchor` | 기능성 표시 + 고시 단일 앵커 성분 존재. exact가 아니므로 중간 가산 |
| `legal_upper_bound` | 보존제/UV필터 등 법정 상한. 실제 효능 함량이 아니므로 매우 약하게만 사용 |
| `marker_upper_bound` | 페녹시에탄올, 카보머, 잔탄검, EDTA, 토코페롤 등 1% 마커 이후 성분. internal 휴리스틱이므로 매우 약하게만 사용 |
| `lower_bound` | 향료 이후 알레르기 착향제 표시기준. 효능 가산에는 거의 쓰지 않음 |
| `prior_estimate` | 제형 기반 정제수 prior. 홈 추천 가산에는 쓰지 않음 |

중요한 제한:

- 이 값은 `함량 확정률`이 아니라 `함량 관련 정보 부여율`입니다.
- `legal_upper_bound`, `marker_upper_bound`, `regulatory_anchor`는 실제 함량이 아닙니다.
- 홈 후보 점수에서는 `exact`, `range`, `regulatory_anchor`만 의미 있게 가산하고, 법정 상한/마커/ prior는 과확정을 피하기 위해 약하게만 처리합니다.
- 현재 별표2 전체 원료군을 모두 매핑한 완성본은 아니며, 홈 후보 검증에 필요한 1차 구현입니다.
- 1% 마커 성분 이후에 등장한 원료가 `exact` 1% 초과로 파싱되면 전성분 표시순서와 충돌하므로 exact로 인정하지 않습니다. 이런 값은 마케팅 문구나 세트 구성품/하위 제형 문구가 섞인 파싱 노이즈일 수 있습니다.

## 중요한 정책

- `market_popular`는 가격·성분·이미지 품질을 인기처럼 포장하지 않습니다. 반드시 별도 시장 신호(`product_market_signals.csv` 또는 DB equivalent)가 있을 때만 산출합니다.
- `market_popular`의 최근 행동 신호는 14일 rolling window 기준입니다. 평점은 리뷰 수 50개를 신뢰 기준으로 둔 Bayesian 보정을 사용하고, 판매 랭킹만 있을 때는 log 기반 역순 점수를 사용합니다.
- 같은 상품에 같은 `ingredient_id`가 여러 번 등장하면 한 번만 계산합니다.
- 글리세린은 홈 예시 후보의 대표 근거 성분으로 쓰지 않습니다.
- 나이아신아마이드는 보습·진정 섹션에서는 대표 근거 성분으로 쓰지 않고, 미백·톤 섹션에서도 트라넥사믹애씨드·알부틴·글루타티온·비사보롤 같은 미백 앵커와 함께 있을 때만 보조로 봅니다.
- 판테놀은 보습·진정 양쪽에 걸릴 수 있으므로, 상품명 포지션과 다른 앵커 성분을 함께 확인합니다.
- 여드름·피지, 주름·탄력, 각질 축은 나이아신아마이드 같은 범용 성분만으로 후보에 올리지 않고 축 특화 성분이 필요합니다.
- 이 후보는 개인화 추천이 아니며, 사용자가 고민/피부 조건을 입력하면 추천 API 결과로 대체합니다.

## 산출물

- `data/reconciliation/concentration_coverage_estimates.csv`
- `data/reconciliation/home_cold_start_p2_candidates.csv`
- `data/reconciliation/home_cold_start_candidates.csv`

`home_cold_start_p2_candidates.csv`는 사람이 손으로 고른 고정 목록이 아니라, 현재 `data/` 스냅샷에서 스크립트로 재계산한 P2 홈용 후보 산출물입니다. `home_cold_start_candidates.csv`는 6개 효능축 전체를 본 1차 분석용 초안입니다.

## 재계산 방법

상품 크롤링/정제 데이터가 업데이트되면 아래 순서로 다시 산출합니다.

```bash
python data/scripts/build_concentration_coverage_estimates.py
python data/scripts/build_home_cold_start_candidates.py
```

입력 데이터:

- `data/products.csv`
- `data/product_prices.csv`
- `data/product_ingredients.csv`
- `data/ingredient_effect.csv`
- `data/ingredient_effect_ranges.csv`
- `data/risk_flags.csv`
- `data/product_market_signals.csv` (선택, 있으면 `market_popular` 산출)

출력 데이터:

- `data/reconciliation/concentration_coverage_estimates.csv`
- `data/reconciliation/home_cold_start_candidates.csv`
- `data/reconciliation/home_cold_start_p2_candidates.csv`

P2에서는 CSV를 materialized snapshot처럼 사용하지만, 이후에는 데이터 import/크롤링 업데이트 후 같은 스크립트를 배치나 CI에서 실행해 최신 15개를 다시 계산하는 방향으로 확장합니다.

## 재현성 규칙

동일한 입력 데이터와 동일한 스크립트 버전이면 동일한 15개가 산출되어야 합니다. 점수가 같은 후보가 생겨도 결과가 흔들리지 않도록 아래 순서로 tie-breaker를 둡니다.

1. `home_example_score` 높은 순
2. `axis_score` 높은 순
3. `coverage_score` 높은 순
4. `risk_penalty` 낮은 순
5. `price` 낮은 순
6. `category` 오름차순
7. `brand` 오름차순
8. `product_id` 오름차순

따라서 상품 데이터가 바뀌지 않았다면 누가 실행해도 같은 결과가 나와야 합니다. 상품/가격/성분/효능/위험 데이터가 바뀌면 같은 로직으로 최신 후보 15개가 다시 계산됩니다.

## risk penalty

홈 첫 화면은 개인화 전이라 민감성 여부를 모르는 사용자에게도 노출됩니다. 따라서 `data/risk_flags.csv`의 `severity_score`를 약한 감점으로 반영합니다.

```text
risk_penalty = SUM(risk_flags.severity_score for matched ingredients) * 5
```

예:

- low `0.3` -> `1.5`점 감점
- medium `0.6` -> `3.0`점 감점
- high `0.8` -> `4.0`점 감점

이 값은 개인화 추천의 민감성 감점과 별개입니다. 홈 콜드스타트에서는 위험 성분이 있는 상품을 완전히 제외하지 않고, 같은 점수대에서 조금 아래로 내리는 용도입니다.

## P2 후보 보정

P2 홈용 후보에는 아래 보정을 추가했습니다.

- 인기 지표가 있으면 `market_popular` 섹션을 먼저 산출하고, 없으면 생략합니다.
- 보습·장벽, 진정, 미백·톤 3개 섹션만 남깁니다.
- 같은 상품이 여러 섹션에 중복 노출되지 않도록 전역 dedupe합니다.
- 한 섹션 안에서 같은 브랜드는 1개만 노출합니다.
- 한 섹션 안에서 같은 카테고리는 최대 2개까지만 노출합니다.
- 보습·장벽 섹션에서는 톤업, 화이트닝, 미백, 잡티, 기미, 진정, 수딩, 시카, 센텔라, 탄력 포지션 상품을 제외합니다.
- 진정 섹션에서는 미백, 잡티, 기미, 각질, 레티놀, 여드름·트러블 포지션 상품을 제외합니다.
- 미백·톤 섹션에서는 각질, BHA/AHA, 레티놀, 트러블 포지션 상품을 제외합니다.
- 각 섹션은 상품명에 해당 포지션 키워드가 있어야 합니다. 예: 보습·장벽은 수분/보습/장벽/베리어/히알루론, 진정은 진정/수딩/시카/카밍/붉은기, 미백·톤은 미백/잡티/기미/톤/TXA/글루타티온.
- 보습·장벽 섹션에서는 `흔적` 포지션 상품도 제외합니다. 흔적/잡티 포지션은 미백·톤 쪽에서만 허용합니다.

## 다음 결정 필요

- 섹션당 노출 개수: 3개 또는 5개
- 개인화 입력 후 홈 예시 후보를 숨길지, 추천 결과 아래에 보조 섹션으로 남길지
