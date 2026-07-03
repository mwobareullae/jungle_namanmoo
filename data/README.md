# Data

팀원3, 팀원4, 팀원5가 제공하는 실제 데이터 산출물을 두는 위치입니다.

`data/examples/`는 입력 형식 예시이고, 실제 데이터는 `data/` 바로 아래에 같은 파일명으로 둡니다.

## 현재 데이터의 성격

현재 `data/*.csv`는 P2 1P 자사몰과 10만 상품 import를 검증하기 위한 정규화 seed입니다.

- 현재 레포에 들어가는 CSV는 최종 10만 원본 feed가 아니라, 백엔드 seed/import와 추천/검색 dry-run에 바로 사용할 수 있는 검증된 결과물입니다.
- 올리브영 등 외부 출처는 초기 수집 기준일 뿐, P2 서비스에서는 `뭐바를래` 자사몰 상품처럼 취급합니다.
- 10만 상품 확장은 원본 feed를 바로 운영 테이블에 넣지 않고, staging validation, bulk upsert, QA 리포트, rollback 가능성을 거친 뒤 반영합니다.
- 대량 import 입력 계약과 실패 row 포맷은 `docs/data-contract.md`의 `P2/MVP 대량 카탈로그 계약`을 기준으로 합니다.

## 최종 디렉터리 구조

```text
data/
  README.md
  examples/

  tags.json
  concern_to_effect.json

  ingredients.csv
  ingredient_effect.csv
  ingredient_evidence.csv
  ingredient_effect_ranges.csv
  risk_flags.csv

  products.csv
  product_skin_profiles.csv
  product_ingredients.csv
  product_prices.csv
  product_inventory.csv
  product_image_assets.csv
  vector_docs.csv
```

## 담당 파일

팀원3: 사용자 고민을 태그와 효능으로 바꾸는 데이터

```text
tags.json
concern_to_effect.json
```

팀원4: 성분, 효능, 근거, 주의 성분 데이터

```text
ingredients.csv
ingredient_effect.csv
ingredient_evidence.csv
ingredient_effect_ranges.csv
risk_flags.csv
```

팀원5: 상품, 상품 성분, 가격, 검색 문서 데이터

```text
products.csv
product_skin_profiles.csv
product_ingredients.csv
product_prices.csv
product_inventory.csv
product_image_assets.csv
vector_docs.csv
```

팀원5 데이터는 P2 자사몰 seed와 10만 feed dry-run의 기준입니다. `products.csv`, `product_prices.csv`, `product_inventory.csv`, `product_image_assets.csv`는 각각 Product, 기본 Offer seed, Inventory seed, Image storage 작업 큐로 해석합니다.

## 공통 규칙

- CSV/JSON은 UTF-8로 저장합니다.
- CSV 첫 줄은 반드시 컬럼명입니다.
- 여러 값을 한 칸에 넣을 때는 `;`로 구분합니다.
  - 예: `건성;중성;수부지`
- ID는 영문 snake_case 또는 숫자 포함 ID로 고정합니다.
  - 예: `prod_001`, `ing_panthenol`, `concern_pore`, `effect_calming`
- 점수는 0~100 정수로 둡니다.
- `weight`는 0.0~1.0 숫자로 둡니다.
- 피부타입 적합도, 민감도 적합도, 출처 신뢰도처럼 `*_fit`, `*_score`로 끝나는 확장 점수는 0.0~1.0 숫자로 둡니다.
- 실제 API key, 개인 정보, 운영 secret은 넣지 않습니다.

## 피부타입 태그 규칙

- `product_skin_profiles.csv`는 모든 상품에 대해 건성/지성/복합성/중성/수부지/민감성 적합도 점수를 0.0~1.0으로 저장합니다.
- `products.csv`의 `skin_type_tags`는 추천 필터에 바로 쓰는 강한 태그만 저장합니다.
- `products.csv`의 `is_recommendable`은 기본 AI 추천 후보에 포함할지 여부를 저장합니다.
- `is_recommendable=false`인 상품은 카탈로그에는 남기되 기본 추천 후보에서는 제외합니다.
- DB 등록 최소 조건은 상품명, 브랜드명, 지원 카테고리, 판매가, 대표 이미지입니다.
- 전성분이 없는 상품도 DB에는 등록할 수 있습니다. 이 경우 기본 추천에서는 제외하고 `recommend_exclude_reason=missing_ingredients`로 저장합니다.
- 제외 사유는 `recommend_exclude_reason`에 저장합니다. 예: `male_targeted`, `all_in_one`, `eye_neck_specific`, `spot_treatment`, `missing_ingredients`, `data_quality_review`, `duplicate_variant_hidden`, `mixed_set_composition`.
- `spot_treatment`는 국소 스팟 제품에만 사용합니다. 잡티/다크스팟 세럼·앰플처럼 일반 얼굴 전체 사용 상품으로 볼 수 있는 제품은 기본 추천 후보에 남깁니다.
- `mixed_set_composition`은 본품 외 다른 화장품 성분이 함께 섞일 수 있는 세트/키트/캘린더/증정 기획 상품에 사용합니다. 상품은 카탈로그에 남기되 기본 추천 후보에서는 제외합니다.
- 피부타입 적합도는 상품명, 상세페이지의 제품 주요 사양/사용방법 문구, 성분 효능, 성분 리스크를 함께 보고 자동 생성합니다.
- 상세페이지 문구는 마케팅 표현일 수 있으므로 최종 점수를 덮어쓰지 않고 보정 근거로만 사용합니다.
- 피부타입 판단 근거가 애매한 상품은 `skin_type_tags`를 비워둡니다.
- 빈 `skin_type_tags`는 데이터 누락이 아니라, 피부타입 추천에서 기본 점수로 중립 처리한다는 의미입니다.
- 기능성 세럼처럼 피부타입보다 미백/주름/트러블 고민 축이 더 중요한 상품은 피부타입 태그가 비어 있을 수 있습니다.

## 기능성 화장품 표시 규칙

- 올리브영 상품정보 제공고시에 있는 `기능성 화장품 식품의약품안전처 심사필 여부` 문구는 `products.csv`에 함께 저장합니다.
- 원문은 `functional_review_text`에 그대로 보존합니다.
- 내부 분류값은 `functional_cosmetic_status`에 저장합니다.
  - `FUNCTIONAL_CONFIRMED`: `심사(또는 보고)를 필함`처럼 기능성 화장품 절차를 거쳤다고 확인되는 상품
  - `FUNCTIONAL_REVIEWED`: 기능성 화장품 심사 관련 문구가 있는 상품
  - `FUNCTIONAL_REPORTED`: 기능성 화장품 보고 관련 문구가 있는 상품
  - `FUNCTIONAL_CLAIMED`: 미백/주름개선 등 기능성 표현은 있으나 심사/보고 문구까지는 명확하지 않은 상품
  - `NOT_FUNCTIONAL`: `해당사항 없음`처럼 기능성 화장품이 아니라고 표시된 상품
  - `UNKNOWN`: 제공고시에서 기능성 여부를 확인하지 못한 상품
- 기능성 종류는 `functional_cosmetic_claims`에 `;`로 구분해 저장합니다.
  - 예: `미백;주름개선`
- 기능성 종류의 신뢰도는 `functional_claim_confidence`에 저장합니다.
  - `high`: 제공고시 원문에서 기능 종류가 직접 확인된 경우
  - `medium`: 기능성 심사/보고 문구가 있고 상품명/상세 키워드와 기능성 후보 성분이 함께 맞는 경우
  - `low`: 일부 추정 근거만 있는 경우
  - `unknown`: 기능성 여부는 확인됐지만 종류를 특정할 근거가 부족한 경우
  - `not_applicable`: 기능성 화장품이 아닌 경우
- 기능성 종류를 분류한 이유는 `functional_claim_basis`에 저장합니다.
- 여드름성 피부 완화는 세정/사용 조건이 필요한 축이므로 자동 확정하지 않고 보수적으로 분류합니다.

## 가격 데이터 규칙

- P2는 가격비교 서비스가 아니라 1P 자사몰이므로 `product_prices.csv`에는 `뭐바를래` 자사몰 판매가만 저장합니다.
- 올리브영은 초기 기준 수집처이며, 수집 가격은 자사몰 판매가 seed로 사용합니다.
- `mall_name`은 P2에서 `뭐바를래`로 둡니다.
- `product_url`은 외부 URL이 아니라 `/products/{product_id}` 형태의 자사몰 상품 상세 경로를 사용합니다.
- `product_prices.csv` 한 행은 P2 단일 셀러 자사몰의 기본 Offer seed로 해석합니다.
- 별도 `offer_id`가 필요한 경우 백엔드가 `product_id` 기준 기본 offer를 생성하거나 매핑합니다.
- 네이버/외부몰 가격 비교는 P5 마켓플레이스 또는 가격비교 확장 단계에서 별도 offer 구조로 다룹니다.

## 재고 데이터 규칙

- `product_inventory.csv`는 P2 장바구니, checkout, 관리자 재고 확인을 위한 자사몰 재고 seed입니다.
- `sales_status`는 `ON_SALE`, `SOLD_OUT`, `HIDDEN` 중 하나를 사용합니다.
- 실제 재고를 보유한 것이 아니므로 초기 재고는 자동 seed로 생성할 수 있습니다.
- 가격이 없는 상품은 판매 가능 상태로 보지 않고 `HIDDEN`으로 둘 수 있습니다.

## 이미지 자산 규칙

- `product_image_assets.csv`는 P2 자사몰에서 사용할 대표 이미지와 상세 이미지를 서버가 저장하기 위한 이미지 다운로드 작업 큐입니다.
- `image_type=thumbnail`은 대표 이미지, `image_type=detail`은 상품 상세 광고/설명 이미지입니다.
- 한 상품에 상세 이미지가 여러 장 있을 수 있으므로 `display_order`로 노출 순서를 정합니다.
- 프론트/백엔드는 상품 이미지 노출 시 `products.csv`의 `thumbnail_url`, `image_urls`보다 `product_image_assets.csv`를 우선 사용합니다.
- `products.csv`의 `thumbnail_url`, `image_urls`는 원본 수집값 확인용 보조 컬럼입니다.
- 서버는 `source_image_url`을 읽어 이미지를 다운로드하고 `storage_key` 경로에 저장합니다.
- `storage_key`는 S3 key 또는 서버 정적 파일 경로로 사용할 수 있는 자사몰 내부 저장 경로입니다.
- `public_url`은 현재 `storage_key`와 같은 예정 경로이며, 실제 서비스에서는 `CDN_BASE_URL + storage_key` 형태로 노출합니다.
- `upload_status`의 초기값은 `PENDING_UPLOAD`입니다.
- 서버 이미지 적재 성공 시 `upload_status=UPLOADED`, 실패 시 `upload_status=FAILED`로 갱신합니다.
- `source_image_url`은 서버가 이미지를 처음 저장할 때 필요한 원본 URL이므로 P2 데이터에는 보존합니다. 운영 안정화 후 제거 여부는 별도 결정합니다.

## 상품 성분 함량 규칙

- `product_ingredients.csv`는 성분명과 표시 순서뿐 아니라 가능한 경우 함량 표기도 함께 저장합니다.
- 함량이 명시되지 않은 성분은 `concentration_text`, `concentration_value`, `concentration_unit`을 비워두고 `concentration_confidence=unknown`으로 둡니다.
- 전성분 표시 순서만 보고 함량을 억지로 추정하지 않습니다.
- `concentration_text`는 상품 정보에 적힌 원문 표기를 그대로 보존합니다.
  - 예: `나이아신아마이드 5%`, `병풀추출물 2970ppm`
- `concentration_value`는 숫자만 저장하고, 원문 단위는 `concentration_unit`에 따로 저장합니다.
- 계산용 비교값은 `normalized_concentration_value`, `normalized_concentration_unit`에 저장합니다.
- 계산용 단위는 `%`로 통일합니다.
  - `%`는 그대로 사용합니다.
  - `ppm`은 `값 / 10000`으로 변환합니다.
  - `ppb`는 `값 / 10000000`으로 변환합니다.
  - `mg/g`는 `값 / 10`으로 변환합니다.
  - `IU/g`처럼 단순 `%` 변환이 어려운 단위는 원문만 보존하고 정규화 값은 비워둡니다.

## ID 연결 규칙

- `products.csv`의 `product_id`는 `product_ingredients.csv`, `product_prices.csv`, `product_inventory.csv`, `product_image_assets.csv`, `vector_docs.csv`에서 그대로 사용합니다.
- `products.csv`의 `product_id`는 `product_skin_profiles.csv`에서도 그대로 사용합니다.
- `ingredients.csv`의 `ingredient_id`는 `product_ingredients.csv`, `ingredient_effect.csv`, `ingredient_evidence.csv`, `risk_flags.csv`, `vector_docs.csv`에서 그대로 사용합니다.
- `ingredients.csv`의 `ingredient_id`는 `ingredient_effect_ranges.csv`에서도 그대로 사용합니다.
- `tags.json`의 `tag_id`는 `concern_to_effect.json`에서 그대로 사용합니다.
- `ingredient_effect.csv`의 `effect_id`는 `ingredient_evidence.csv`, `ingredient_effect_ranges.csv`, `concern_to_effect.json`에서 같은 의미로 사용합니다.

## 다시 수집하지 않으려면 꼭 필요한 정보

상품:

```text
상품 ID, 브랜드, 상품명, 카테고리, 권장 피부 타입,
대표 이미지, 상세 이미지, 판매몰, 가격, 구매 링크,
재고, 판매상태, 피부타입 적합도, 민감도 적합도, 판단 근거
```

성분:

```text
성분 ID, 한글명, 영문명, 설명,
효능, 효능 점수, 근거 수준, 근거 점수,
근거 제목, 근거 URL, 근거 요약, 출처 타입,
주의 문구, 주의 적용 조건,
성분-효능별 유효/적정/과다 함량 범위
```

검색:

```text
상품명, 브랜드, 성분, 효능, 설명을 합친 검색용 문장
```

## 예시

입력 형식은 `data/examples/`의 파일을 기준으로 맞춥니다.

실제 데이터를 채울 때는 `data/examples/products.csv`를 복사해서 `data/products.csv`를 만들고 내용을 늘리면 됩니다.
