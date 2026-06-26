# Data Contract

이 문서는 Phase 0에서 팀원3, 팀원4, 팀원5가 제공해야 하는 데이터 산출물의 레포 기준 계약입니다.

엑셀 명세서의 `데이터계약`, `API명세`, `API_JSON예시` 시트를 기준으로 하되, 실제 개발과 리뷰는 이 문서를 우선 확인합니다.

## 기본 원칙

- 실제 데이터는 `data/` 아래에 둡니다.
- 예시 데이터는 `data/examples/` 아래에 둡니다.
- 파일명과 컬럼명은 이 문서의 이름을 우선 사용합니다.
- CSV는 UTF-8 인코딩을 사용합니다.
- 여러 값을 담는 컬럼은 가능하면 JSON 문자열보다 별도 매핑 파일로 분리합니다.
- 민감정보, API key, 실제 운영 secret은 데이터 파일에 넣지 않습니다.
- 상품근거점수와 리뷰매칭점수는 MVP 점수에서 제외합니다.
- 위험성분은 점수 감점이 아니라 별도 주의 표기로 제공합니다.

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
| `data/risk_flags.csv` | CSV | 주의 성분과 표시 문구 |

팀원4는 성분효능점수, 성분근거점수 계산에 필요한 필드를 제공합니다.

### 팀원5: 상품과 상품-성분 데이터

| 파일 | 형식 | 설명 |
| --- | --- | --- |
| `data/products.csv` | CSV | 상품 기본 정보 |
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
| `source` | 근거 출처명 또는 요약 |

### `data/risk_flags.csv`

| 컬럼 | 설명 |
| --- | --- |
| `ingredient_id` | 성분 고유 ID |
| `risk_type` | 주의 유형 |
| `display_text` | 프론트에 표시할 주의 문구 |

### `data/products.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `brand` | 브랜드명 |
| `name` | 상품명 |
| `skin_type_tags` | 권장 피부 타입 태그 |
| `thumbnail_url` | 대표 이미지 URL |
| `image_urls` | 상세 이미지 URL 목록 |

### `data/product_ingredients.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `ingredient_id` | 성분 고유 ID |
| `ingredient_name` | 상품 표기 성분명 |
| `content_confidence` | 함량 신뢰도: `high`, `medium`, `low`, `unknown` |
| `display_order` | 표시 순서 |

### `data/product_prices.csv`

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `lowest_price` | 최저가, 없으면 빈 값 |
| `purchase_url` | 구매 URL, 없으면 빈 값 |
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

## 검수 체크리스트

- [ ] 파일명이 이 문서와 일치한다.
- [ ] 필수 컬럼이 누락되지 않았다.
- [ ] ID 값이 다른 파일의 참조와 일치한다.
- [ ] 실제 secret 또는 개인 정보가 없다.
- [ ] 빈 값 허용 필드는 프론트/백엔드에서 처리 가능한 값으로 남겼다.
- [ ] 예시 파일은 실제 운영 데이터와 섞이지 않는다.
