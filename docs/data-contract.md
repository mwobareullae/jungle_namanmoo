# Data Contract

이 문서는 Phase 0에서 팀원3, 팀원4, 팀원5가 제공해야 하는 데이터 산출물의 레포 기준 계약입니다.

엑셀 명세서의 `데이터계약`, `API명세`, `API_JSON예시` 시트를 기준으로 하되, 실제 개발과 리뷰는 이 문서를 우선 확인합니다.

## 기본 원칙

- 실제 데이터는 `data/` 아래에 둡니다.
- 예시 데이터는 `data/examples/` 아래에 둡니다.
- 파일명과 컬럼명은 이 문서의 이름을 우선 사용합니다.
- CSV는 UTF-8 인코딩을 사용합니다.
- 여러 값을 담는 컬럼은 가능하면 JSON 문자열보다 별도 매핑 파일로 분리합니다.
- 점수형 컬럼은 별도 설명이 없으면 `0.0~1.0` 범위를 사용합니다.
- 민감정보, API key, 실제 운영 secret은 데이터 파일에 넣지 않습니다.
- 상품근거점수와 리뷰매칭점수는 MVP 점수에서 제외합니다.
- 위험성분은 점수 감점이 아니라 별도 주의 표기로 제공합니다.
- 확장 컬럼은 파일에 포함하되 값은 비워둘 수 있습니다. 값이 들어오면 v1 스코어링에서 반영합니다.
- 함량 컬럼은 `product_ingredients.csv`에 포함하되, 함량이 공개되지 않은 행은 빈 값과 `unknown`으로 둡니다.

## 담당자별 산출물

### 팀원3: 고민 태그와 효능 매핑

| 파일 | 형식 | 설명 |
| --- | --- | --- |
| `data/tags.json` | JSON | 사용자 고민에서 추출 가능한 표준 고민 태그 |
| `data/concern_to_effect.json` | JSON | 고민 태그와 추천 효능의 매핑 |

팀원3은 `unmatched_terms` 판단 기준도 함께 문서화합니다.

### 팀원4: 성분 효능과 근거 데이터

| 파일 | 형식 | 설명 |
| --- | --- | --- |
| `data/ingredients.csv` | CSV | 성분 기본 정보 |
| `data/ingredient_effect.csv` | CSV | 성분과 효능의 매핑 |
| `data/ingredient_evidence.csv` | CSV | 성분 효능 근거와 근거 등급 |
| `data/ingredient_effect_ranges.csv` | CSV | 성분-효능별 유효/적정/과다 함량 범위 |
| `data/risk_flags.csv` | CSV | 주의 성분과 표시 문구 |

팀원4는 성분효능점수, 성분근거점수 계산에 필요한 필드를 제공합니다.

### 팀원5: 상품과 상품-성분 데이터

| 파일 | 형식 | 설명 |
| --- | --- | --- |
| `data/products.csv` | CSV | 상품 기본 정보 |
| `data/product_skin_profiles.csv` | CSV | 상품별 피부타입/민감도 적합 점수 |
| `data/product_ingredients.csv` | CSV | 상품과 성분의 매핑 |
| `data/product_prices.csv` | CSV | 상품 가격과 구매 URL |
| `data/vector_docs.csv` | CSV | 추후 검색/임베딩 인덱싱용 문서 |

팀원5는 MVP 기준 상품 10개 이상을 제공합니다.

## 파일별 필드

### `data/tags.json`

```json
[
  {
    "tag_id": "concern_pore",
    "name": "모공",
    "synonyms": ["모공", "넓은 모공", "모공 늘어짐"]
  }
]
```

### `data/concern_to_effect.json`

```json
[
  {
    "tag_id": "concern_pore",
    "effect_id": "effect_sebum_control",
    "effect_name": "피지 조절",
    "weight": 1.0
  }
]
```

### `data/ingredients.csv`

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `name_ko` | 성분 한글명 |
| `name_en` | 성분 영문명 |
| `description` | 성분 설명 |
| `source_url` | 성분 정보 출처 URL (선택, 비어 있을 수 있음) |

### `data/ingredient_effect.csv`

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `effect_id` | 효능 고유 ID |
| `effect_name` | 효능명 |
| `effect_score` | 성분효능점수 계산용 기본 점수 |

### `data/ingredient_evidence.csv`

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `effect_id` | 효능 고유 ID |
| `evidence_level` | 근거 등급: `high`, `medium`, `low` |
| `evidence_score` | 성분근거점수 계산용 점수 |
| `source_title` | 근거 출처명 (논문/식약처 고시 제목 등) |
| `source_url` | 근거 출처 URL (선택, 비어 있을 수 있음) |
| `summary` | 근거 요약 |
| `source_type` | 선택. `paper`, `mfds`, `official`, `manufacturer`, `commerce`, `unknown` |
| `pmid` | 선택. PubMed PMID |
| `doi` | 선택. 논문 DOI |
| `source_authority_score` | 선택. 출처 신뢰도 보정값 `0.0~1.0` |

`source_authority_score`는 추후 아래처럼 근거 점수 보정에 사용할 수 있습니다.

```text
adjusted_evidence_score = evidence_score / 100 * source_authority_score
```

### `data/ingredient_effect_ranges.csv`

성분 함량 점수화를 위한 확장 파일입니다. MVP v0에서는 아직 필수로 사용하지 않지만, 나중에 `concentration_fit_score` 계산에 사용합니다.

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `effect_id` | 효능 고유 ID |
| `unit` | 함량 단위. 예: `%`, `ppm`, `ppb`, `mg/g` |
| `meaningful_min` | 효과가 있다고 보기 시작하는 최소 함량 |
| `optimal_min` | 적정 범위 시작 함량 |
| `optimal_max` | 적정 범위 끝 함량 |
| `excessive_min` | 과다/주의로 볼 수 있는 시작 함량. 근거가 없으면 빈 값 |
| `range_confidence` | 범위 판단 신뢰도: `high`, `medium`, `low`, `unknown` |
| `source_type` | `paper`, `mfds`, `official`, `manufacturer`, `commerce`, `unknown` |
| `source_url` | 범위 판단 근거 URL |
| `note` | 범위 판단 메모 |

추후 함량 점수는 아래 단계형 점수로 시작합니다.

```text
unknown       -> 0.5
below         -> 0.2
meaningful    -> 0.7
optimal       -> 1.0
excessive     -> 0.4 + 주의 문구
```

### `data/risk_flags.csv`

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `risk_type` | 주의 유형 |
| `display_text` | 프론트에 표시할 주의 문구 |
| `severity` | 주의 심각도: `high`, `medium`, `low` |
| `severity_score` | 선택. 주의 강도 보정값 `0.0~1.0` |
| `applies_to` | 선택. 적용 대상. `sensitive;pregnancy;photosensitivity`처럼 `;`로 구분 |
| `condition` | 선택. 어떤 조건에서 주의해야 하는지 |
| `source_type` | 선택. `paper`, `mfds`, `official`, `manufacturer`, `commerce`, `unknown` |
| `source_url` | 선택. 주의 정보 출처 |

위험성분은 기본적으로 점수에서 직접 감점하지 않습니다. 다만 추후 민감도 적합성 계산과 주의 문구 노출에 사용합니다.

### `data/products.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `brand` | 브랜드명 |
| `name` | 상품명 |
| `category` | 상품 카테고리. 예: `toner`, `serum`, `cream`, `lotion` |
| `skin_type_tags` | 권장 피부 타입 태그 |
| `thumbnail_url` | 대표 이미지 URL |
| `image_urls` | 상세 이미지 URL 목록 |

### `data/product_skin_profiles.csv`

상품별 피부타입/민감도 개인화 점수를 위한 확장 파일입니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `dry_fit` | 건성 적합도 `0.0~1.0` |
| `oily_fit` | 지성 적합도 `0.0~1.0` |
| `combination_fit` | 복합성 적합도 `0.0~1.0` |
| `normal_fit` | 중성 적합도 `0.0~1.0` |
| `dehydrated_oily_fit` | 수부지 적합도 `0.0~1.0` |
| `sensitive_fit` | 민감 피부 적합도 `0.0~1.0` |
| `sensitivity_tag` | `민감추천`, `민감가능`, `민감주의`, `정보없음` |
| `confidence` | 판단 신뢰도: `high`, `medium`, `low`, `unknown` |
| `reason` | 판단 근거. 예: `보습 장벽 컨셉`, `피지 케어 컨셉` |

추후 피부 프로필 점수는 아래처럼 계산합니다.

```text
skin_profile_score =
  selected_skin_type_fit * 0.6
+ sensitive_fit * 0.4
```

예를 들어 사용자가 `건성`, `민감`이고 상품의 `dry_fit=0.9`, `sensitive_fit=0.8`이면:

```text
skin_profile_score = 0.9 * 0.6 + 0.8 * 0.4 = 0.86
```

### `data/product_ingredients.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `ingredient_id` | 성분 고유 ID |
| `ingredient_name` | 상품 표기 성분명 |
| `content_confidence` | 함량 신뢰도: `high`, `medium`, `low`, `unknown` |
| `display_order` | 표시 순서 |
| `concentration_text` | 선택. 원문 함량 표기. 예: `나이아신아마이드 5%` |
| `concentration_value` | 선택. 숫자로 추출한 함량값 |
| `concentration_unit` | 선택. `%`, `ppm`, `ppb`, `mg/g` 등 |
| `concentration_confidence` | 선택. 함량 추출 신뢰도: `high`, `medium`, `low`, `unknown` |
| `normalized_concentration_value` | 선택. 계산용으로 `%` 단위로 변환한 함량값 |
| `normalized_concentration_unit` | 선택. 계산용 단위. 변환 가능하면 `%`, 변환 불가하면 빈 값 |

함량 처리 원칙:

- 상품 성분 행에 명시된 숫자와 단위만 함량으로 인정합니다.
- 함량이 없으면 전성분 순서로 추정하지 않고 `unknown`으로 둡니다.
- 원문 표기는 `concentration_text`에 그대로 보존합니다.
- 추천 점수 계산용 비교 단위는 `%`로 통일합니다.
  - `ppm`은 `값 / 10000`
  - `ppb`는 `값 / 10000000`
  - `mg/g`는 `값 / 10`
  - `IU/g`처럼 단순 변환이 어려운 단위는 정규화 값을 비웁니다.

### `data/product_prices.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `mall_name` | 판매처명 |
| `price` | 판매가 |
| `product_url` | 구매 URL |
| `is_lowest` | 최저가 여부: `true`, `false` |
| `currency` | 통화, 기본 `KRW` |

### `data/vector_docs.csv`

| 컬럼 | 설명 |
| --- | --- |
| `doc_id` | 문서 고유 ID |
| `source_type` | `product`, `ingredient`, `evidence` 등 |
| `source_id` | 원본 데이터 ID |
| `text` | 임베딩 또는 검색에 사용할 텍스트 |

## MVP 점수 정책

- 성분효능점수는 효능 단위로 계산합니다.
- 같은 효능이 여러 고민에서 중복 도출되어도 효능 자체는 한 번만 반영합니다.
- 하나의 효능에 여러 유효 성분이 있으면 상위 3개 성분을 반영합니다.
- 상위 3개 성분은 `1.0 / 0.5 / 0.25` 감쇠계수를 적용합니다.
- 상품근거점수와 리뷰매칭점수는 MVP에서 제외합니다.
- 위험성분은 감점하지 않고 `주의 성분 있음`처럼 별도 표시합니다.
- v0 스코어링은 `성분효능`, `성분근거`, `피부프로필`, `검색매칭`, `가격`을 사용합니다.
- 함량 점수는 v1 확장 항목입니다. 다만 `product_ingredients.csv`의 함량 컬럼과 `ingredient_effect_ranges.csv`는 지금부터 수집합니다.
- 피부타입/민감도 개인화는 `product_skin_profiles.csv`가 채워지는 즉시 `skin_profile_score`에 반영할 수 있습니다.

## 검수 체크리스트

- [ ] 파일명이 이 문서와 일치한다.
- [ ] 필수 컬럼이 누락되지 않았다.
- [ ] ID 값이 다른 파일의 참조와 일치한다.
- [ ] 실제 secret 또는 개인 정보가 없다.
- [ ] 빈 값 허용 필드는 프론트/백엔드에서 처리 가능한 값으로 남겼다.
- [ ] 예시 파일은 실제 운영 데이터와 섞이지 않는다.
