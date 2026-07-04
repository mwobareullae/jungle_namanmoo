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
- P2/MVP에서 레포에 들어가는 정규화 CSV는 10만 상품 import 전 검증용 dry-run seed로 취급합니다.
- 10만 상품 원본 feed는 바로 운영 테이블에 넣지 않고 staging 검증, bulk upsert, QA 리포트 단계를 거친 뒤 정규화 CSV/DB에 반영합니다.

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
| `data/ingredient_aliases.csv` | CSV | raw 성분 표기와 canonical 성분 ID의 매핑 |
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
| `data/product_prices.csv` | CSV | P2 자사몰 판매가와 상품 상세 URL |
| `data/product_inventory.csv` | CSV | P2 자사몰 재고와 판매 상태 |
| `data/product_image_assets.csv` | CSV | P2 자사몰 대표/상세 이미지 자산 |
| `data/vector_docs.csv` | CSV | 추후 검색/임베딩 인덱싱용 문서 |

팀원5는 P2 자사몰 seed 기준 상품, 가격, 재고, 이미지, 성분, 검색 문서를 함께 제공합니다.

현재 레포의 `data/*.csv`는 P2 1P 자사몰과 10만 상품 import를 검증하기 위한 정규화 결과물입니다. 최종 10만 feed 원본 자체가 아니라, 백엔드 seed/import와 추천/검색 dry-run에 바로 사용할 수 있는 검증된 subset으로 봅니다.

## P2/MVP 대량 카탈로그 계약

새 명세서 기준 P2/MVP는 작은 수동 상품 목록이 아니라, 1P 자사몰 구매 흐름과 대량 상품 검색/추천 기반을 함께 검증합니다. 따라서 데이터 계약은 아래 두 층으로 나눕니다.

| 층 | 목적 | 소유 |
| --- | --- | --- |
| 정규화 seed | `data/products.csv` 등 레포 CSV. P2 데모, seed, 추천/검색 dry-run에 사용 | R5 세민 |
| 대량 feed/import | 10만 상품 원본 feed를 staging으로 적재, 검증, upsert, rollback하는 운영 경로 | R5 세민, R3 원우, R6 지운 |

대량 feed/import 원칙:

- R5는 feed 입력 컬럼, 정규화 규칙, QA 기준, 실패 row 포맷을 정의합니다.
- R3는 DB 모델, staging table, bulk upsert, transaction/rollback, API 실행을 소유합니다.
- R6는 import job 모니터링, worker, storage, 실패 리포트, 알림을 소유합니다.
- R4는 검색/추천 index source와 후보 생성 품질을 소유합니다.
- 대량 feed는 `Product`, `Seller`, `ProductPrice`, `Inventory`, `ProductImage`, `ProductIngredient`, `VectorDoc`로 나뉘어 들어가야 합니다.
- 10만 상품에서 추천/검색을 할 때 매 요청마다 전체 상품 full scan을 하지 않는 구조를 전제로 합니다.

### Product / Seller / Price / Inventory / Image 관계

| 객체 | 의미 | P2 기준 |
| --- | --- | --- |
| `Product` | canonical 상품 master. 브랜드, 상품명, 카테고리, 성분/이미지의 기준 | `data/products.csv` |
| `Seller` | 상품 판매 주체 | P2는 기본 seller `mwobareullae`를 사용하고 `products.seller_id`로 연결 |
| `ProductPrice` | 자사몰 판매가와 상품 상세 경로 | `product_prices.csv` |
| `Inventory` | 판매 가능 수량과 품절/숨김 상태 | P2는 `product_id` 기준 재고 |
| `ProductImage` | 대표/상세 이미지 자산 | `product_image_assets.csv` 작업 큐를 서버가 storage로 이관 |
| `ProductIngredient` | 상품과 성분의 연결, 표시 순서, 함량 | 추천 근거와 함량 분석의 원천 |
| `VectorDoc` | 검색/임베딩 대상 문서 | 상품명, 브랜드, 카테고리, 핵심 성분, 효능 설명 기반 |

P2의 `product_prices.csv` 한 행은 외부몰 가격비교가 아니라 단일 셀러 자사몰의 판매가 seed로 해석합니다. 외부 API와 프론트 handoff는 `product_id`를 기준으로 전달하고, P2/MVP에서는 별도 `offer_id`를 만들지 않고 `product_id`와 기본 seller 기준으로 가격/재고/주문을 처리합니다. 다중 셀러가 같은 상품을 경쟁 판매하는 구조가 생기면 그때 `offers`를 재검토합니다.

### 10만 feed 최소 입력 컬럼

대량 feed 원본은 사이트별로 다를 수 있으므로, staging 전 최소 입력 기준을 아래처럼 둡니다.

| 컬럼 | 필수 | 설명 |
| --- | --- | --- |
| `source_name` | Y | 원본 출처. 예: `oliveyoung`, `manual_feed` |
| `source_product_key` | Y | 원본 상품 식별자 |
| `brand` | Y | 브랜드명 |
| `name` | Y | 상품명 |
| `category` | Y | 지원 카테고리. `toner`, `serum`, `cream`, `lotion` 등 |
| `price` | Y | P2 자사몰 판매가 seed로 사용할 가격 |
| `thumbnail_source_url` | Y | 대표 이미지 원본 URL |
| `detail_image_source_urls` | N | 상세 이미지 원본 URL 목록 |
| `ingredients_raw` | N | 전성분 원문. 없으면 상품은 보존하되 기본 추천 제외 |
| `volume_text` | N | 용량 원문 |
| `sales_status_raw` | N | 원본 판매 상태 |

### staging validation 결과

staging 검증은 row 단위로 성공/실패를 남겨야 합니다. 실패 row는 아래 포맷으로 다운로드하거나 관리자 화면에서 확인할 수 있어야 합니다.

| 컬럼 | 설명 |
| --- | --- |
| `import_job_id` | import 실행 ID |
| `batch_id` | chunk/batch ID |
| `row_no` | 원본 feed row 번호 |
| `source_ref` | `source_name:source_product_key` 형태의 원본 참조 |
| `field` | 오류가 발생한 필드 |
| `code` | 오류 코드. 예: `MISSING_REQUIRED`, `INVALID_CATEGORY`, `IMAGE_PLACEHOLDER`, `PRICE_INVALID`, `DUPLICATE_CANDIDATE` |
| `message` | 사람이 읽을 수 있는 오류 설명 |
| `raw_ref` | 원본 값 또는 원본 파일 위치 |
| `severity` | `critical`, `warning`, `info` |

### QA acceptance criteria

10만 import를 완료로 보기 위한 최소 기준입니다.

| 항목 | 기준 |
| --- | --- |
| 필수 컬럼 누락 | release seed 기준 `critical=0` |
| 상품 ID 참조 무결성 | `products.csv` 기준 참조 파일 누락 `0건` |
| 가격 이상 | 음수/0원/비정상 문자열 `0건`, 의심 가격은 warning으로 분리 |
| 대표 이미지 | placeholder/깨진 URL은 기본 release seed에서 제외 또는 `FAILED` 처리 |
| 전성분 누락 | 상품은 보존 가능하나 `is_recommendable=false`, `missing_ingredients`로 분리 |
| 중복 상품 | canonical 후보를 남기고 대표 노출 상품 외에는 `duplicate_variant_hidden` 처리 |
| 추천 후보 | 기본 추천은 `is_recommendable=true`만 사용 |
| 실패 row | 실패 사유와 재처리 가능 여부가 남아야 함 |

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

### `data/ingredient_aliases.csv`

상품 라벨의 raw 성분명을 `ingredients.csv`의 canonical 성분 ID로 연결하는 선택 입력 파일입니다. 파일이 없으면 seed는 alias 없이 진행합니다.

| 컬럼 | 설명 |
| --- | --- |
| `alias` | 실제 상품 라벨에 등장 가능한 성분 표기 |
| `canonical_id` | 매핑 대상 성분 ID. `ingredients.csv`의 `ingredient_id`를 참조 |
| `alias_type` | 표기 유형: `ko`, `en`, `inci`, `abbrev`, `typo`, `synonym` |
| `confidence` | 매핑 신뢰도: `high`, `medium`, `low`. 기존 산출물 호환을 위해 입력값 `med`는 seed 시 `medium`으로 정규화 |
| `source` | 매핑 근거. 예: `INCI`, `식약처 성분사전`, `KCIA` |

동일한 정규화 alias가 둘 이상의 `canonical_id`에 매핑되면 충돌로 보고 seed 전에 수정합니다.
Seed는 입력 CSV에 있는 alias를 insert/update하지만, CSV에서 삭제된 기존 DB alias를 자동 삭제하지 않습니다. 삭제가 필요한 경우 별도 정리 작업으로 처리합니다.

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
| `is_recommendable` | 기본 AI 추천 후보 포함 여부. `true`면 일반 추천 후보, `false`면 카탈로그에는 남기되 기본 추천에서는 제외 |
| `recommend_exclude_reason` | `is_recommendable=false`인 이유. 예: `male_targeted`, `all_in_one`, `eye_neck_specific`, `spot_treatment`, `missing_ingredients`, `data_quality_review`, `duplicate_variant_hidden`, `mixed_set_composition`. 여러 값은 `;`로 구분 |
| `skin_type_tags` | 권장 피부 타입 태그 |
| `thumbnail_url` | 대표 이미지 URL |
| `image_urls` | 상세 이미지 URL 목록 |
| `functional_review_text` | 선택. 올리브영 상품정보 제공고시의 기능성 화장품 심사필/보고 문구 원문 |
| `functional_cosmetic_status` | 선택. 기능성 화장품 여부 분류. `FUNCTIONAL_CONFIRMED`, `FUNCTIONAL_REVIEWED`, `FUNCTIONAL_REPORTED`, `FUNCTIONAL_CLAIMED`, `NOT_FUNCTIONAL`, `UNKNOWN` |
| `functional_cosmetic_claims` | 선택. 기능성 종류. 예: `미백;주름개선` |
| `functional_claim_confidence` | 선택. 기능성 종류 분류 신뢰도. `high`, `medium`, `low`, `unknown`, `not_applicable` |
| `functional_claim_basis` | 선택. 기능성 종류를 그렇게 분류한 근거. 예: 제공고시 직접 확인, 상품명/성분 기반 추정 |

기능성 종류 분류 원칙:

- 제공고시에 기능 종류가 직접 적힌 경우만 `high`로 봅니다.
- 제공고시에는 기능성 심사/보고 문구만 있고, 상품명/상세 키워드와 기능성 후보 성분이 함께 맞는 경우는 `medium`으로 봅니다.
- 일부 근거만 있는 경우는 `low`로 두며, 추천 로직에서 강한 가산점으로 쓰지 않습니다.
- 여드름성 피부 완화는 세정/사용 조건이 함께 필요한 축이므로 자동 확정하지 않고 보수적으로 분류합니다.

추천 후보 분류 원칙:

- `products.csv`는 자사몰 카탈로그이므로 상품을 가능한 한 보존합니다.
- DB 등록 최소 조건은 상품명, 브랜드명, 지원 카테고리(`toner`, `serum`, `cream`, `lotion`), 판매가, 대표 이미지입니다.
- 전성분은 DB 등록 필수 조건이 아닙니다. 전성분이 없으면 상품은 카탈로그에 남기되 `is_recommendable=false`, `recommend_exclude_reason=missing_ingredients`로 둡니다.
- 다만 기본 AI 추천은 사용자가 일반적인 기초 제품을 기대한다는 전제로 동작하므로, 남성 전용, 올인원, 눈가/목 전용, 국소 스팟 제품은 `is_recommendable=false`로 둡니다.
- 스팟 제품은 보수적으로 분류합니다. `스팟 크림/젤/패치/밤/트리트먼트` 또는 20ml/g 이하 국소 사용 제품은 제외하되, `다크 스팟 세럼`, `잡티 스팟 앰플`처럼 일반 세럼/앰플로 볼 수 있는 상품은 추천 후보에 남깁니다.
- 본품 외 다른 화장품 성분이 섞일 수 있는 세트/키트/캘린더/증정 기획 상품은 `mixed_set_composition`으로 기본 추천에서 제외합니다. 예: 본품 토너에 증정 크림/세럼/폼 성분이 함께 들어올 수 있는 구성입니다.
- 같은 전성분/브랜드/카테고리로 묶이는 중복 옵션 중 대표가 아닌 상품은 `duplicate_variant_hidden`으로 기본 추천에서 제외할 수 있습니다. 상품 상세와 관리자 카탈로그에는 남깁니다.
- 제외 상품도 상품 상세, 관리자 확인, 향후 조건부 추천 확장에는 사용할 수 있도록 삭제하지 않습니다.
- 기본 추천 API/스코어링은 우선 `is_recommendable=true`인 상품만 후보로 사용합니다.

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

P2 기준에서는 외부 가격비교가 아니라 `뭐바를래` 1P 자사몰 판매가를 저장합니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `mall_name` | 판매 주체. P2에서는 `뭐바를래` |
| `price` | 자사몰 판매가. 초기 seed는 올리브영 수집가를 기준으로 사용 가능 |
| `product_url` | 자사몰 상품 상세 경로. 예: `/products/prod_xxx` |
| `is_lowest` | P2에서는 가격비교가 아니므로 기본 `true` |
| `currency` | 통화, 기본 `KRW` |

가격 수집 정책:

- 올리브영은 초기 기준 수집처이며, 수집 가격은 P2 자사몰 판매가 seed로 사용합니다.
- P2에서는 네이버/외부몰 가격을 `product_prices.csv`에 넣지 않습니다.
- 외부 판매처 비교는 P5 마켓플레이스 또는 가격비교 확장 단계에서 별도 offer 구조로 다룹니다.

### `data/product_inventory.csv`

P2 자사몰 장바구니, checkout, 관리자 재고 확인을 위한 seed 파일입니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `stock_quantity` | 현재 판매 가능 재고 수량 |
| `sales_status` | 자사몰 판매 상태. `ON_SALE`, `SOLD_OUT`, `HIDDEN` |
| `safety_stock` | 안전 재고 수량 |
| `inventory_source` | 재고 생성 방식. 예: `AUTO_SEED`, `AUTO_SEED_NO_PRICE`, `ADMIN` |
| `updated_at` | 재고 기준 시각. 수집 시각 또는 관리자 수정 시각 |

주의:

- 현재 `AUTO_SEED` 재고는 P2 장바구니, checkout, 관리자 흐름 검증용 mock 데이터입니다.
- 홈 추천의 `market_popular` 인기 점수에는 사용하지 않습니다.

### `data/product_market_signals.csv` (선택)

홈의 `지금 인기 있는 제품` 섹션을 계산하기 위한 시장 인기 신호 파일입니다. 현재 필수 seed 파일은 아니며, mock 또는 크롤링 지표가 들어온 뒤 사용합니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `review_count` | 리뷰 수 |
| `average_rating` | 평균 평점. 0~5 스케일 |
| `sales_count` | 판매량. 있으면 가장 직접적인 인기 신호 |
| `sales_rank` | 판매 랭킹. `sales_count`가 없을 때 사용하며 낮을수록 좋음 |
| `recent_view_count` | 최근 14일 조회 수 |
| `wishlist_count` | 최근 14일 찜 수 |
| `cart_add_count` | 최근 14일 장바구니 담기 수 |
| `source` | 데이터 출처. 예: `mock`, `crawler`, `event_log` |
| `updated_at` | 지표 스냅샷 기준 시각 |

인기 점수 원칙:

- 인기 섹션은 이 파일 또는 동일한 DB 필드가 있을 때만 산출합니다.
- 가격, 이미지 존재, 성분 점수, `AUTO_SEED` 재고를 인기 신호처럼 쓰지 않습니다.
- 리뷰수, 판매량, 최근 행동 수치는 `log1p` 정규화합니다.
- 평점은 리뷰 수 50개를 신뢰 기준으로 둔 Bayesian 보정을 사용합니다.
- 판매량이 없고 판매 랭킹만 있으면 log 기반 역순 랭킹 점수를 사용합니다.

### `data/product_image_assets.csv`

P2 자사몰 상품 상세 화면에서 사용할 대표 이미지와 상세 광고 이미지를 서버가 저장하기 위한 작업 큐입니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `image_type` | 이미지 종류. `thumbnail` 또는 `detail` |
| `display_order` | 같은 상품, 같은 이미지 종류 안에서의 노출 순서 |
| `source_image_url` | 서버가 다운로드할 원본 이미지 URL |
| `storage_key` | 자사몰 저장소 기준 파일 경로. S3 key 또는 서버 정적 파일 경로로 사용 |
| `public_url` | 배치 큐 확인용 예정 경로. MVP 서비스 DB에는 저장하지 않음 |
| `upload_status` | 배치 큐 확인용 이미지 처리 상태. `PENDING_UPLOAD`, `UPLOADED`, `FAILED` |

서버 처리 규칙:

- 팀원5는 이미지 파일을 직접 저장하지 않고 `product_image_assets.csv`를 작업 큐로 제공합니다.
- 백엔드/인프라 배치는 `source_image_url`을 다운로드해 `storage_key` 위치에 저장합니다.
- 상품 이미지 노출은 `products.csv`의 `thumbnail_url`, `image_urls`보다 `product_image_assets.csv`를 우선 사용합니다.
- `products.csv`의 `thumbnail_url`, `image_urls`는 원본 수집값 확인용 보조 컬럼입니다.
- P2 초기 데이터의 `public_url`은 `storage_key`와 같은 예정 경로이며, 배치/QA 확인용 메타데이터입니다.
- MVP `product_images` DB 테이블에는 `product_id`, `image_type`, `display_order`, `storage_key`를 저장합니다.
- DB에는 CloudFront 절대 URL을 저장하지 않습니다.
- 프론트는 공개 환경변수 `VITE_IMAGE_CDN_BASE_URL`과 `storage_key`를 조합해 실제 이미지 URL을 만듭니다.
- 대표 이미지는 `VITE_IMAGE_CDN_BASE_URL + "/resized/w400/" + storage_key`로 노출합니다.
- 상세 이미지는 `VITE_IMAGE_CDN_BASE_URL + "/resized/w1200/" + storage_key`로 노출합니다.
- 원본 이미지는 `original/{storage_key}`에 보관하되 외부 공개 URL로 노출하지 않습니다.
- `upload_status`는 초기값 `PENDING_UPLOAD`로 둡니다.
- 저장 성공 시 `UPLOADED`, 실패 시 `FAILED`로 갱신하고 실패 행만 재시도할 수 있어야 합니다.
- 상세 이미지는 `image_type=detail`이고 `display_order` 오름차순으로 노출합니다.

### `data/vector_docs.csv`

| 컬럼 | 설명 |
| --- | --- |
| `doc_id` | 문서 고유 ID |
| `source_type` | `product`, `ingredient`, `evidence` 등 |
| `source_id` | 원본 데이터 ID |
| `text` | 임베딩 또는 검색에 사용할 텍스트 |

## 홈 추천 산출물

홈 추천 산출물은 seed 원천 데이터가 아니라 R4 추천 로직 검수와 프론트/백엔드 계약 확인을 위한 reconciliation snapshot입니다.

### `data/reconciliation/home_cold_start_p2_candidates.csv`

비로그인 또는 피부 프로필이 없는 사용자의 P2 홈 후보입니다.

| 컬럼 | 설명 |
| --- | --- |
| `section_id` | 홈 섹션 ID. 예: `market_popular`, `moisture_barrier`, `calming`, `brightening` |
| `section_label` | 사용자에게 보여줄 섹션명 |
| `effect_id` | 성분 효능축 ID. `market_popular`는 빈 값 가능 |
| `effect_name` | 효능축 이름. `market_popular`는 `시장 인기` |
| `rank` | 섹션 내부 노출 순서 |
| `product_id` | 상품 고유 ID |
| `brand` | 브랜드명 |
| `name` | 상품명 |
| `category` | 상품 카테고리 |
| `price` | 표시 가격 |
| `home_example_score` | 비회원 홈 후보 점수. 시장 인기 섹션은 `market_popularity_score`와 동일 |
| `axis_score` | 효능축 성분 근거 점수. 시장 인기 섹션은 빈 값 가능 |
| `coverage_score` | 함량 coverage 점수. 시장 인기 섹션은 빈 값 가능 |
| `market_popularity_score` | 인기 점수. 인기 데이터가 없거나 예시 섹션이면 빈 값 가능 |
| `review_count_score` | 리뷰 수 정규화 점수 |
| `rating_score` | Bayesian 평점 점수 |
| `sales_score` | 판매량 또는 판매랭킹 점수 |
| `recent_signal_score` | 최근 14일 조회/찜/장바구니 점수 |
| `coverage_types` | 매칭 성분별 함량 coverage 타입 |
| `risk_penalty` | 홈 노출용 위험성분 감점 |
| `matched_ingredients` | 섹션 점수에 기여한 대표 성분 |
| `coverage_basis` | 내부 검수용 함량 근거. 사용자에게 직접 노출하지 않음 |
| `reason_summary` | 프론트 표시용 짧은 추천 사유 |
| `thumbnail_url` | 상품 대표 이미지 URL |

### `data/reconciliation/home_personalized_profile_candidates.csv`

로그인 사용자의 대표 피부 프로필 시나리오별 홈 후보 fixture입니다. 실제 사용자 데이터가 아니라 로직 검수용입니다.

`home_cold_start_p2_candidates.csv` 컬럼에 더해 아래 컬럼을 포함합니다.

| 컬럼 | 설명 |
| --- | --- |
| `scenario_id` | 대표 프로필 시나리오 ID |
| `scenario_label` | 대표 프로필 시나리오 설명 |
| `skin_type` | 피부 타입 |
| `sensitivity` | 민감도 |
| `source_effect_id` | 해당 섹션 산출에 사용한 효능축 ID |
| `source_effect_name` | 해당 섹션 산출에 사용한 효능축 이름 |
| `personalized_home_score` | 회원 홈 후보 점수 |
| `profile_fit_score` | 피부 타입 적합도 점수 |
| `sensitivity_fit_score` | 민감도 적합도 점수 |
| `price_score` | 가격 접근성 점수 |

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
