# Data

팀원3, 팀원4, 팀원5가 제공하는 실제 데이터 산출물을 두는 위치입니다.

`data/examples/`는 입력 형식 예시이고, 실제 데이터는 `data/` 바로 아래에 같은 파일명으로 둡니다.

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
vector_docs.csv
```

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
- 피부타입 적합도는 상품명, 상세페이지의 제품 주요 사양/사용방법 문구, 성분 효능, 성분 리스크를 함께 보고 자동 생성합니다.
- 상세페이지 문구는 마케팅 표현일 수 있으므로 최종 점수를 덮어쓰지 않고 보정 근거로만 사용합니다.
- 피부타입 판단 근거가 애매한 상품은 `skin_type_tags`를 비워둡니다.
- 빈 `skin_type_tags`는 데이터 누락이 아니라, 피부타입 추천에서 기본 점수로 중립 처리한다는 의미입니다.
- 기능성 세럼처럼 피부타입보다 미백/주름/트러블 고민 축이 더 중요한 상품은 피부타입 태그가 비어 있을 수 있습니다.

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

- `products.csv`의 `product_id`는 `product_ingredients.csv`, `product_prices.csv`, `vector_docs.csv`에서 그대로 사용합니다.
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
피부타입 적합도, 민감도 적합도, 판단 근거
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
