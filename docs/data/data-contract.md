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
- 상품 근거와 리뷰 품질·유사 프로필 affinity는 현재 추천 점수에 반영합니다.
- 위험성분은 모든 사용자에게 표시하고, 민감도 `높음` 사용자에게만 제한된 penalty를 적용합니다.
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
| `data/ingredient_canonical_mappings.csv` | CSV | pending source 또는 broad exact 표기를 승인된 canonical 성분 ID로 연결하는 매핑 |
| `data/effect_outcome_dictionary.csv` | CSV | 논문 결과 표현을 기존 6효능에 안전하게 연결하기 위한 검수 용어 사전 |
| `data/effect_direction_dictionary.csv` | CSV | 결과 변화 표현을 증가·감소·무효·불확실로 분류하는 검수 방향 사전 |
| `data/ingredient_effect.csv` | CSV | 성분과 효능의 매핑 |
| `data/ingredient_evidence.csv` | CSV | 성분 효능 근거와 근거 등급 |
| `data/ingredient_effect_ranges.csv` | CSV | 성분-효능별 유효/적정/과다 함량 범위 |
| `data/risk_flags.csv` | CSV | 주의 성분과 표시 문구 |

팀원4는 성분효능점수, 성분근거점수 계산에 필요한 필드를 제공합니다.

### 팀원5: 상품과 상품-성분 데이터

| 파일 | 형식 | 설명 |
| --- | --- | --- |
| `data/products.csv` 또는 `data/products/*.csv` | CSV | 상품 기본 정보. 대량 seed는 동일 헤더의 분할 CSV 사용 가능 |
| `data/product_skin_profiles.csv` | CSV | 상품별 피부타입/민감도 적합 점수 |
| `data/product_ingredients.csv` 또는 `data/product_ingredients/*.csv` | CSV | 상품과 성분의 매핑. 대량 seed는 동일 헤더의 분할 CSV 사용 가능 |
| `data/product_prices.csv` | CSV | P2 자사몰 판매가와 상품 상세 URL |
| `data/product_inventory.csv` | CSV | P2 자사몰 재고와 판매 상태 |
| `data/product_image_assets.csv` | CSV | P2 자사몰 대표/상세 이미지 자산 |
| `data/vector_docs.csv` | CSV | 추후 검색/임베딩 인덱싱용 문서 |
| `data/storefront_product_reviews/*.csv` | CSV | 상품 상세에 노출할 리뷰 원문 split 데이터 |
| `data/product_review_summary.csv` | CSV | 상품별 리뷰 요약 통계 |
| `data/product_review_profile_stats.csv` | CSV | 상품별 피부 프로필 기준 리뷰 통계 |
| `data/product_review_signals.csv` | CSV | 리뷰 기반 추천 보조 신호. 실제 scoring 반영은 R4 확인 후 별도 적용 |

팀원5는 P2 자사몰 seed 기준 상품, 가격, 재고, 이미지, 성분, 검색 문서를 함께 제공합니다.

현재 레포의 `data/*.csv`는 P2 1P 자사몰과 10만 상품 import를 검증하기 위한 정규화 결과물입니다. 최종 10만 feed 원본 자체가 아니라, 백엔드 seed/import와 추천/검색 dry-run에 바로 사용할 수 있는 검증된 subset으로 봅니다.

대량 CSV는 GitHub 단일 파일 100MB 제한을 피하기 위해 같은 헤더의 분할 파일로 둘 수 있습니다. 예를 들어 `data/products.csv` 대신 `data/products/products_000.csv`, `data/products/products_001.csv`를 둘 수 있습니다. 백엔드 loader는 단일 파일이 있으면 단일 파일을 읽고, 단일 파일이 없으면 같은 이름의 디렉터리 안 `*.csv`를 파일명 오름차순으로 모두 읽습니다. 단일 파일과 분할 디렉터리가 동시에 있으면 중복 적재 위험이 있으므로 오류로 처리합니다.

## P2/MVP 대량 카탈로그 계약

새 명세서 기준 P2/MVP는 작은 수동 상품 목록이 아니라, 1P 자사몰 구매 흐름과 대량 상품 검색/추천 기반을 함께 검증합니다. 따라서 데이터 계약은 아래 두 층으로 나눕니다.

| 층 | 목적 | 소유 |
| --- | --- | --- |
| 정규화 seed | `data/products.csv` 또는 `data/products/*.csv` 등 레포 CSV. P2 데모, seed, 추천/검색 dry-run에 사용 | R5 세민 |
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
| `Product` | canonical 상품 master. 브랜드, 상품명, 카테고리, 성분/이미지의 기준 | `data/products.csv` 또는 `data/products/*.csv` |
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
| 상품 ID 참조 무결성 | 상품 CSV 기준 참조 파일 누락 `0건` |
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

### `data/ingredient_canonical_mappings.csv`

대용량 `product_ingredients.csv` 원본을 다시 쓰지 않고, 검수 완료된 pending source ID 또는 broad 성분의 exact 표기를 canonical 성분으로 해석하기 위한 선택 입력 파일입니다.

| 컬럼 | 설명 |
| --- | --- |
| `source_ingredient_id` | 원본 상품-성분 연결의 성분 ID. 전체 매핑은 `ing_pending_` ID, exact override는 기존 broad canonical ID 사용 가능 |
| `source_ingredient_name` | pending ID 전체를 옮길 때는 공란. 기존 broad ID 중 KCIA 표준명 또는 공식 구명칭과 exact 일치하는 표기만 분리할 때는 원문 성분명 |
| `canonical_id` | 매핑 대상 정식 성분 ID. `ingredients.csv`에 존재하고 `ing_pending_`이 아니어야 함 |
| `mapping_type` | `official_exact`, `existing_identity`, `exact_name_override`. `exact_name_override`의 exact는 source 원문과 승인된 표준명/구명칭 간 일치를 뜻하며 canonical 표시명과의 문자열 동일성을 뜻하지 않음 |
| `confidence` | 자동 적용 파일에는 `high`만 허용 |
| `source` | 매핑 근거. KCIA 성분코드와 standard/legacy name 구분을 함께 기록 |

Seed는 상품-성분 적재 시 먼저 `(source_ingredient_id, source_ingredient_name)` exact override를 확인하고, 없으면 source ID 전체 매핑을 적용합니다. 이미 DB에 남아 있는 해당 source 연결은 같은 트랜잭션에서 먼저 삭제한 뒤 현재 원본 CSV를 기준으로 broad 또는 exact canonical 연결을 다시 upsert합니다. 매핑이 없는 pending ID는 기존과 동일하게 유지합니다.

이 파일은 검수 완료 매핑만 담는 append-oriented 정본입니다. 기존 매핑을 제거하거나 대상을 바꿀 때는 과거 canonical 연결 정리가 필요하므로 별도 데이터 정리와 검증을 수행해야 합니다.

### canonicalization 80% 배치 산출물

- `data/reconciliation/ingredient_canonicalization_top4000_80pct.csv`는 기존 exact/wildcard 매핑을 적용한 뒤에도 남는 pending source ID를 상품행 빈도순으로 정리한 검수 인벤토리입니다.
- `data/reconciliation/ingredient_canonicalization_proposals_80pct.csv`는 KCIA 표준명·영문명·구명칭 exact 일치 중 상품 성분행 커버리지가 80%에 도달하는 지점까지만 `selected_for_target=Y`로 선택합니다.
- `data/reconciliation/ingredient_canonicalization_validation.json`은 전체 상품 성분행에서 실제 매핑 커버리지와 중복 collapse 수를 재계산한 결과입니다.
- 같은 구명칭이 둘 이상의 최신 canonical을 가리키면 exact override와 alias 자동 재배정을 건너뛰고 broad 또는 pending 상태로 남깁니다.

### 성분 우선 논문 카탈로그 (현재 검토 방식)

논문 검토는 성분×6효능 조합을 먼저 만들지 않습니다. 상품 사용량 상위 canonical
성분을 먼저 고르고, 정확한 성분명과 피부 문맥으로 PubMed를 검색한 뒤 성분별 최대
3편을 선택합니다. 논문의 원문 결과 문장을 보존한 다음에만 기존 효능축 또는 새 효능
후보로 분류합니다.

- `ingredient_paper_targets_500.csv`: 상품 사용량 상위 500개 성분, 실제 검색어·검색식,
  검색 결과 수와 선택 논문 수를 기록합니다.
- `ingredient_paper_candidates_500.csv`: 성분별 최대 3편의 대표 검토 후보입니다. 제목에
  정확한 성분명이 있으면 `title_exact`, 초록에 있으면 `abstract_exact`로 구분합니다.
  논문 역할은 `direct_effect`, `safety_evidence`, `formulation_evidence`,
  `mechanism_evidence`, `reference_evidence`를 복수로 기록할 수 있습니다.
- `ingredient_paper_outcomes_500.csv`: 잘리지 않은 결과 문장과 사후 분류를 보존합니다.
  `mapped_existing_effect`, `new_effect_candidate`, `mechanism_only`, `unclear` 중 하나를
  사용하며, 직접 관계·리뷰 요약·기전 문맥도 별도 기록합니다. 방향은 대표
  `direction`과 효능별 상세 `direction_by_effect_json`, 충돌 여부 `direction_conflict`,
  규칙 버전 `direction_policy_version`을 함께 기록합니다.
- `ingredient_new_effect_candidates.csv`: 기존 6축에 억지로 넣지 않은 결과를 효능명별로
  집계한 관찰 목록입니다. 이 파일의 항목은 새 효능축 승인이나 점수 반영을 뜻하지 않습니다.
- `ingredient_paper_screening_all_500.csv`: 검색된 논문 전체의 역할, 대표 선택 여부와
  제외 사유를 보존하는 감사 파일입니다. 대표 3편에 들지 않은 행은 근거 정본이나 점수
  입력이 아니며, 자동 필터가 무엇을 제외했는지 재검토할 때만 사용합니다.
- `ingredient_evidence_adjudication_466.csv`: 기존 런타임 점수 성분 34개를 제외한
  상위 466개 성분의 **기계 초기 선별 원장**입니다. 최종 과학 판정이 아니며 모든
  행은 `status_scope=machine_screening_only`입니다. 모든 성분이 한 행을 가지며
  `score_candidate_positive`, `score_candidate_supporting`, `negative_or_null`,
  `new_effect_candidate`, `abstract_insufficient`, `formulation_only`,
  `reject_wrong_scope`, `no_evidence_found` 중 하나를 `primary_status`로 기록합니다.
  `no_evidence_found`는 논문을 찾지 못한 경우와 초록 정보가 부족한 경우를 섞지 않기
  위한 명시적 상태입니다.
- `ingredient_evidence_representatives_466.csv`: 위 466개 성분별 대표 논문 최대 3편과
  C03~C14 기계 판정, 통계 표지, 방향, 정정 표지, 전문 확인 상태를 보존합니다.
  `score_candidate_*`도 전문 확인 전에는 `candidate_unverified`이며 런타임 점수에
  자동 반영되지 않습니다.
- `ingredient_evidence_adjudication_466_summary.json`: 기존 34개 + 신규 검토 466개 =
  총 500개 포트폴리오의 초기 선별 집계와 검색하지 못한 외부 소스를 기록합니다.
  `adjudication_complete=false`, 전문 확인·효능 매핑·방향 판정 건수를 함께 기록해
  초기 선별 결과를 최종 점수 가능 개수로 오인하지 않도록 합니다.

복합제·운반체·성분 목록의 단순 언급은 직접 단일성분 효능으로 연결하지 않지만
`formulation_evidence`로는 보존할 수 있습니다. 식품·포장 문맥, 경로 불일치와 분석법처럼
피부 근거 역할이 없는 논문만 대표 후보에서 제외합니다. 연구설계는 인체 국소 SR/메타(1), RCT(2), 대조·비무작위 임상(3),
관찰·사용시험(4), 적출·인공피부(5), 동물(6), in vitro(7), 일반 리뷰·참고(8)로
기계 분류하되, 전 행은 `candidate_unverified`이고 `score_change=none`입니다.
기존 `ingredient_effect.csv`, `ingredient_evidence.csv`, DB와 추천 점수는 변경하지 않습니다.
이 문장은 v1/v1.1 기계 선별 산출물 자체의 동작을 설명합니다. 이후 별도 승인된
`mwbl-legacy-scale-500-v1` 확장은 이 기계 선별의 `not_scoreable` 또는 사람 승인 상태를
런타임 차단 조건으로 사용하지 않고 점수 데이터를 갱신했습니다.

#### 성분 근거 필터 계약 v1.1

정본 규칙은 `docs/ingredient-evidence-filter-contract-v1.1.md`입니다. v1.1은 v1의
평탄화된 `primary_status`를 점수 판정 정본으로 사용하지 않고, 서로 독립적인 상태축을
보존합니다. `primary_status`가 남아 있는 경우 화면·이전 도구 호환을 위한 파생 표시값일
뿐이며 scoring 입력으로 사용할 수 없습니다.

v1.1 대상 manifest는 기존 v1 원장의 순서 있는 466개 ID를 동결해 승계합니다. 상위 500개
입력과 런타임 34개의 실제 교집합은 28개여서 비런타임 후보는 472개이며, 후순위 6개는
기존 v1 용량 기준 밖입니다. 따라서 대상 수를 단순히 `500-34`로 재계산하지 않습니다.

- `eligibility_status`: 성분·경로·설계·단일성분 분리·논문 유효성 적격 여부
- `verification_status`: 전문 확인, 초록 전용, 정정 대기, 유효성 보류 상태
- `applicability_status`: 일반 피부, 질환 한정, 유발시험 한정, 안전성 전용 범위
- `effect_mapping_status`: 기존 효능 매핑, 새 효능 후보, 미매핑 결과 여부
- `outcome_direction`: 결과 단위의 `positive`, `negative`,
  `no_detectable_difference`, `unclear`, `not_applicable`
- `score_status`: `score_candidate_positive`, `score_candidate_supporting`,
  `not_scoreable`
- `review_status`: `candidate_unverified`, `reviewer1_complete`,
  `reviewer2_complete`, `adjudicated`
- `runtime_score_change`: 이번 v1.1 재검색·재판정에서는 항상 `none`

전문을 확인하지 않은 긍정·보조 신호는 `machine_signal_status`에 보존하지만
`score_status=not_scoreable`로 둡니다. `no_evidence_found`는 효능 최종 상태가 아니라
소스별 `search_status=zero_results`로 기록합니다. 모든 검색 소스는 `success`,
`success_protocol_capped`, `zero_results`, `partial`, `technical_failure`,
`access_unavailable`, `not_attempted`
중 하나와 실패 사유·검색식·검색 건수·페이지 수집 완료 여부를 남깁니다.
v1.1은 frozen 466을 여섯 소스에서 새로 검색하고 `input_provenance`,
`query_contract_status`, `rerun_required`를 함께 기록합니다. 승인어 전용 검색임을 검증하지
못했거나 선언한 retrieval 프로토콜이 부분·실패·미실행이면 `rerun_required=Y`이며 C02
검색 완료로 간주하지 않습니다. `success_protocol_capped`는 사전 고정한 relevance cap까지
오류 없이 수집한 상태이며 `pagination_complete=false`를 유지합니다. 공식 API 자격 또는
robots 정책 때문에 현재 실행자가 해결할 수 없는 접근 제한은 근거와 사유를 기록한 뒤
`access_unavailable`, `rerun_required=N`으로 닫을 수 있습니다.

v1 산출물은 덮어쓰지 않습니다. v1.1은 아래 논리 경로로 생성합니다.

- `ingredient_evidence_adjudication_466_v1_1.csv`: 성분별 v1.1 상태 요약
- `ingredient_evidence_representatives_466_v1_1.csv`: 대표 출판물과 논문 단위 제한·검증 상태
- `ingredient_evidence_outcome_results_466_v1_1.csv`: 성분×연구×비교×결과×시점 판정 원장
- `ingredient_evidence_search_runs_466_v1_1.csv`: 성분×소스 검색 실행 원장
- `ingredient_evidence_adjudication_466_v1_1_summary.json`: manifest·사전 SHA와 전체 집계
- `ingredient_evidence_v1_1_validation.json`: 466×6 검색, 키 유일성, 승인 질의,
  `candidate_unverified`, 런타임 불변식의 자동 검증 결과

대용량 v1.1 산출물은 Git 런타임 경로에 직접 커밋하지 않습니다. 최종 산출물은
GitHub Release `ingredient-evidence-v1.1-bdata-20260713`의 SHA 고정 artifact에 보존하고,
저장소에는 `data/reconciliation/ingredient_evidence_v1_1_artifact.json` 포인터만 둡니다.
이 artifact는 `candidate_unverified` 감사 자료이며 런타임 seed나 표시·광고 근거가
아닙니다. 검색 패키지는 83개 무결성 검사를 통과했지만 KCI는 robots 정책 때문에
466개 전부 `access_unavailable`입니다. Git에서 분리한 B-data는 본 archive 74개와
보충 archive 2개, 총 76개이며 두 archive 모두 SHA-256을 고정합니다.

원시 fresh 검색의 논리 경로는 `data/reconciliation/v1_1_fresh/`이며 동일 artifact 안에
소스별로 보존합니다.

- `{source}_query_log_466_v1_1_fresh.csv`: 각 소스의 성분별 정확히 466행 실행 원장.
  공통 필드는 `query_id`, `source`, `ingredient_rank`, `ingredient_id`, `approved_search_terms`,
  `search_query`, `query_sha256`, `started_at_utc`, `completed_at_utc`, `raw_hit_count`,
  `retrieval_cap`, `returned_count`, `pagination_status`, `pagination_complete`,
  `request_status`, `error_message`, `query_contract_status`, `rerun_required`,
  `review_status`, `runtime_score_change`, `pipeline_version`입니다.
- `{source}_candidates_466_v1_1_fresh.csv`: 성분×소스 record 후보 원장입니다. PMID·PMCID·DOI·
  source record ID가 없으면 정규화 제목으로 식별하며, `title`, `abstract`, `journal`,
  `publication_date/year`, `authors`, `source_url`, `search_query`, `review_status`,
  `runtime_score_change`를 보존합니다.
- `{source}_search_summary_466_v1_1_fresh.json`: 실행·오류·cap·후보 건수와 입력/출력 SHA 집계입니다.

`ingredient_evidence_outcome_results_466_v1_1.csv`에서는 결과 문장, 효능 매핑, 방향,
통계 contrast를 같은 `outcome_result_id`에 연결합니다. 초록에서 확인할 수 없는 군,
시점, 효과추정치, CI, p값은 추정하지 않고 `not_extracted` 또는 빈 값으로 보존합니다.
논문 단위의 다른 문장에 p값이 있다는 이유로 해당 결과를 통계적으로 지지된 것으로
승격하지 않습니다.
초록 단계 ID는 `outcome_id_status=provisional_abstract`이며 전역 유일한 결정적 SHA-256
기반 ID입니다. 전문에서 비교·지표·시점을 정규화한 뒤 최종 ID로 바꿀 때 매핑을 보존합니다.

재현성을 위해 모든 v1.1 행은 다음 해시를 기록합니다.

- 정확한 466개 대상 manifest의 `manifest_version`, `manifest_sha256`
- `data/ingredients.csv`와 `data/ingredient_aliases.csv`의 순서 고정 bundle SHA-256
- `data/effect_outcome_dictionary.csv` SHA-256
- `data/effect_direction_dictionary.csv` SHA-256

사전 bundle SHA는 summary에 포함된 파일 순서와 개별 파일 SHA로 다시 계산할 수 있어야
합니다. AI가 제안한 성분·결과 표현은 사전에 자동 추가하지 않으며, 독립 검수와 지정된
사람의 최종 판정 전에는 `unmapped_outcome` 또는 검토 후보로만 남깁니다.

### `data/effect_outcome_dictionary.csv`

논문 제목·초록·결과 문장의 표현을 기존 6효능에 연결할 때 사용하는 단일 정본입니다.
성분명 동의어를 관리하는 `ingredient_aliases.csv`와 목적이 다릅니다. 검색에 사용할 수 있는
넓은 표현과 실제 효능 매핑에 사용할 수 있는 측정 결과를 분리합니다.

| 컬럼 | 설명 |
| --- | --- |
| `effect_id` | 기존 6효능 ID |
| `outcome_concept_id` | 같은 측정 개념을 묶는 내부 ID |
| `term` | 논문에서 사용하는 결과·지표·척도·기기·기전 표현 |
| `term_type` | `outcome`, `metric`, `scale`, `abbreviation`, `instrument`, `method`, `context`, `mechanism` |
| `positive_direction` | 유리한 변화 방향. `increase`, `decrease`, `parameter_specific`, `not_applicable` |
| `required_context` | 짧거나 모호한 표현에 함께 있어야 하는 문맥. `|`로 복수 표현 |
| `forbidden_context` | 함께 있으면 매핑하지 않는 문맥. `|`로 복수 표현 |
| `discovery_use` | 논문 검색식 확장에 사용할 수 있으면 `Y` |
| `mapping_use` | 측정 결과 문장에서 기존 효능으로 매핑할 수 있으면 `Y` |
| `source_type` | 용어 근거 유형. `guideline`, `measurement_guidance`, `validation_study`, `internal_mapping_policy`, `internal_guardrail` |
| `source_reference` | PMID 또는 공식 문서 URL |
| `review_status` | `approved`, `context_only`, `mechanism_only`, `ambiguous_review` |
| `notes` | 오인 방지 조건과 검수 메모 |

운영 규칙:

- `mapping_use=Y`는 결과·지표·척도·문맥 조건을 충족한 승인 표현에만 허용합니다.
- 매칭은 NFKC 정규화 후 영문·숫자 토큰 경계로 수행합니다. 부분 문자열은 매칭하지 않습니다.
- 같은 구간에서 승인 표현이 겹치면 가장 긴 표현만 채택하고, 최종 `effect_id`는 중복 제거합니다.
- `mapping_use=N`인 짧은 문맥·기기·기전 용어는 더 긴 `mapping_use=Y` 결과를 무효화하지 않습니다.
- 기기명(`Mexameter`, `PRIMOS`, `D-Squame`)은 어떤 채널을 측정했는지 알 수 없으므로 단독 매핑하지 않습니다.
- 해부·질환·기전 표현(`stratum corneum`, `dermatitis`, `tyrosinase`, `collagen`)은 검색에는 사용할 수 있지만 단독 효능으로 확정하지 않습니다.
- 약어(`IGA`, `ITA`)는 `required_context`가 같은 문장에 있을 때만 매핑합니다.
- `positive_direction`은 각 **term**의 유리한 값 방향이며 `outcome_concept_id` 전체에 일괄 적용하지 않습니다.
- 이 파일은 결과 개념을 6효능에 매핑할 뿐, 논문이 실제로 증가·감소·무효를 보고했는지 판정하는 방향 어휘 사전은 아닙니다. 기계 방향 판정은 별도 후보 필드이며 사람 승인 전 점수에 쓰지 않습니다.
- 각질 지표는 증가·감소의 의미가 프로토콜마다 달라 전부 `parameter_specific`입니다. v1 각질축은 자동 긍정 판정 없이 수동 검토만 허용합니다.
- 외부 문헌 출처는 해당 지표·척도·측정 개념의 근거를 뜻합니다. 문자열을 같은 효능으로 묶은 내부 결정은 `internal_mapping_policy`, 단독 매핑 금지는 `internal_guardrail`로 구분합니다.
- `discovery_use`는 기존 성분×효능쌍 주간 검색식 확장에 사용합니다. 성분 우선 검색은 확증편향을 막기 위해 이 컬럼을 사용하지 않고 성분명+피부 문맥으로 검색합니다.
- `forbidden_context`는 `skin barrier recovery`와 `barrier recovery time`처럼 방향이 달라지는 검증된 문장 충돌에만 사용합니다. 식품·치과·경구·복합제 등 넓은 범위 배제는 논문 단위 필터가 담당합니다.
- 이 사전은 후보 발견·결과 분류용이며 `ingredient_effect.csv`, `ingredient_evidence.csv` 또는 런타임 점수를 직접 변경하지 않습니다.
- `effect_outcome_dictionary.py` 검증을 통과한 사전만 수집·매핑 스크립트에서 사용합니다.
- 사전의 6개 `effect_id`는 `ingredient_effect.csv`와 `concern_to_effect.json` 양쪽에 모두 존재해야 합니다.

### `data/effect_direction_dictionary.csv`

결과 문장의 변화어를 지표별 유리한 방향과 결합해 `positive`, `negative`, `null`,
`unclear` 후보를 만드는 내부 언어 정책입니다. 이 사전은 과학 근거 출처가 아니라
재현 가능한 기계 판정 규칙이며 모든 결과는 사람 승인 전 `candidate_unverified`입니다.

| 컬럼 | 설명 |
| --- | --- |
| `cue_id` | 방향 표현 고유 ID |
| `term` | 논문 결과 문장의 변화·무효·불확실 표현 |
| `cue_type` | `increase`, `decrease`, `improvement`, `worsening`, `null`, `uncertain` |
| `priority` | 겹치는 표현의 판정 우선순위. 무효·불확실 표현이 단순 변화어보다 높음 |
| `required_context` | 같은 문장에 필요한 문맥. `|`로 복수 표현 |
| `forbidden_context` | 함께 있으면 적용하지 않는 문맥 |
| `source_type` | `internal_language_policy` 또는 `internal_statistical_policy` |
| `source_reference` | 현재 `POLICY:effect-direction-v1` |
| `review_status` | 검수된 행은 `approved` |
| `notes` | 표현의 판정 의미와 제한 |

판정 규칙:

- 결과 지표와 방향 표현은 같은 세미콜론 절 안에서 최대 10토큰 이내인 경우만 연결합니다.
- `no significant difference`, `not significantly lower` 같은 긴 표현은 내부의 `lower`보다 우선합니다.
- `no`, `not`, `never`, `without`, `failed`, `lacked`, `absence of`가 방향 표현 앞 4토큰 안에 있으면 부정 스코프로 처리해 `null`로 보냅니다. `and`, `but`, `while`, `whereas`는 부정 스코프 경계입니다.
- `may improve`, `trend toward`, `suggested` 같은 hedge 표현은 단순 `improve`, `lower`보다 우선하며 `unclear`입니다. 다만 같은 절에 명확한 `significant(ly)`, 유의한 p값, CI 또는 효과크기 표지가 있고 구체적 변화어가 있으면 변화 결과를 우선합니다.
- `lower arm`, `higher concentration`, `elevated temperature`처럼 비교어 다음에 해부·용량·환경 명사가 오는 경우는 방향 큐로 사용하지 않습니다.
- 지표의 `positive_direction=increase`이면 실제 증가가 positive이고 감소가 negative입니다. `decrease` 지표는 반대로 판정합니다.
- `improvement`와 `worsening`은 명시적 저자 방향으로 처리하지만 `parameter_specific` 각질 지표는 자동 positive/negative로 승격하지 않습니다.
- 한 문장에 여러 지표가 있으면 지표별 방향을 `direction_by_effect_json`에 보존합니다. 같은 효능 안에서 방향이 갈리면 대표 `direction=unclear`, `direction_conflict=Y`입니다.
- 방향 표현이 없거나 연결 거리가 멀면 추측하지 않고 `unclear`로 둡니다.
- v1 방향 사전은 영어 초록 전용입니다. 한국어 초록은 별도 한국어 사전 승인 전 자동 방향 판정 대상에서 제외하고 `unclear` 또는 수동 검토로 보냅니다.
- 이 사전은 후보 방향만 만들며 DB·런타임 점수·승인 상태를 변경하지 않습니다.

### 성분 우선 논문 점수 적격성 검토

`assess_ingredient_score_eligibility.py`는 대표 논문 유무와 무관하게 PubMed 결과가 있는
성분 전체를 같은 규칙으로 재검사합니다. 이 단계는 런타임 점수 입력이 아니라 검토용
분류이며, 모든 결과는 `candidate_unverified`와 `runtime_score_change=none`을 유지합니다.

- `ingredient_score_eligibility_370.csv`: 성분별로 긍정 효능, 위험 감점, 기전 보조,
  새 효능축, 제형·참고·안전 신호 여부와 최종 검토 결정을 기록합니다.
- `ingredient_score_claim_candidates.csv`: 판정에 사용한 PMID, 원문 결과 문장, 효능축,
  방향과 권장 사용 범위를 보존합니다.
- `ingredient_score_eligibility_summary.json`: 대표 후보가 있던 성분과 원시 검색 결과만
  있던 성분을 나눠 결정 건수를 집계합니다.

인체 국소 1~4등급의 직접 긍정 결과만 효능 점수 검토 후보가 될 수 있습니다. 불확실한
표현, 복합제, 일반 리뷰와 제형 근거는 단일성분 긍정 점수가 아닙니다. 명확한 인체 국소
이상반응 제목만 위험 감점 검토 후보로 분리하며, 일반적인 안전성 언급은 점수로 쓰지
않습니다. 기전 연구는 단독 효능 점수가 아니라 보조 근거로만 기록합니다.

### 다중 소스 논문 점수 퍼널

`prepare_ingredient_multisource_targets.py`는 초기 500개 중 PubMed 제목·초록에서 정확한
성분명이 한 번도 확인되지 않은 18개를 **논문 검토 대상에서만** 제외합니다. canonical
성분과 상품 연결은 삭제하지 않습니다. 유지 대상은 `ingredient_paper_targets_482.csv`,
제외 감사표는 `ingredient_paper_targets_excluded_18.csv`입니다.

`search_ingredient_evidence_multisource.py`는 482개를 소스별로 검색하고 원본 메타데이터와
쿼리 로그를 분리 저장합니다. 현재 482개 전체가 완료된 공통 소스는 PubMed, Europe PMC의
비-PubMed 레코드, Crossref입니다. OpenAlex 부분 결과는 전체 비교에서 제외하며 KCI/RISS는
API 키가 설정되지 않으면 실행하지 않습니다.

- `ingredient_multisource_<source>_482.csv`: 소스별 논문 후보 메타데이터
- `ingredient_multisource_<source>_query_log_482.csv`: 성분별 요청 성공·검색 건수 감사표
- `ingredient_multisource_screening_482.csv`: PMID·DOI·제목 중복 제거 후 논문별 필터 판정
- `ingredient_multisource_score_eligibility_482.csv`: 성분별 최초 탈락 필터와 최종 후보 여부
- `ingredient_multisource_filter_funnel_482.csv`: 필터별 탈락 수와 잔존 수
- `ingredient_multisource_summary_482.json`: 소스 범위·한계·집계 결과

필터는 같은 논문에 순차 적용합니다. 다른 논문들의 장점을 합쳐 통과시키지 않습니다.
순서는 정확한 성분 형태, 인체 피부 도포, 비복합제, 검수된 결과 사전 기준 기존 6효능 직접 측정, 긍정 방향,
불확실 표현 제외, tier 1~4 단독 근거입니다. 모든 결과는 `candidate_unverified`이고 런타임
점수 변경은 없습니다.

### 이전 조합 우선 실험 산출물

`ingredient_effect_pubmed_screening.csv`, `ingredient_research_portfolio_500.csv`,
`ingredient_effect_portfolio_500.csv`, `ingredient_effect_business_score_proposal_500.csv`,
`ingredient_effect_business_score_impact_500.json`은 6축 조합 우선 접근을 검토한 실험
산출물입니다. 현재 성분 우선 논문 카탈로그의 입력이나 런타임 정본으로 사용하지 않습니다.

### 레거시 스케일 500성분 점수 확장

2026-07-13 변경 후보는 `기존 34 + 동결 신규 466`의 정확한 500개 집합을 같은 legacy 점수
스케일로 평가합니다. 기존 34개·72쌍은 그대로 유지하고 신규
153개·173쌍을 추가해 현재 `ingredient_effect.csv`는 **187개 성분·245쌍**입니다.
`ingredient_evidence.csv`는 기존 72행과 신규 구조화 논문 35행을 합친 **107행**입니다.

- 공식 기능 prior 144쌍: 좁은 CosIng 6효능 기능만 사용하며 effect 점수만 부여
- 구조화 논문 override 35쌍: primary 70, supporting 50, limited_medical 35로 legacy scale 변환
- 공식 기능 prior만 있는 쌍: 임상 근거점수 0, `ingredient_evidence` 행 없음
- `review_status`, 전문 확인, 사람 adjudication: 런타임 점수 차단 조건으로 사용하지 않음
- 사용자 추천 사유: 근거가 없는 prior를 `효능 근거`라고 부르지 않고 `공식 성분 기능 분류 기반`으로 표시

상세 규칙과 실제 상품 도달률은 `docs/scoring/legacy-scale-500-scoring.md`, 재현 입력·SHA와
전수 결과는 `data/reconciliation/legacy_scale_500/`을 정본으로 봅니다.

성분효능 top3와 성분근거 top3는 독립 선발합니다. 성분효능은 `effect_score`, 성분근거는
`evidence_score × source_authority_score`를 기준으로 각각 상위 3개를 고르고
`1.0 / 0.5 / 0.25` 감쇠를 적용합니다. 기존 운영 34개·72쌍에서 확장 187개·245쌍으로
전환하는 10,164개 추천 가능 상품 전수검증에서 효능·근거·합산점수 감소는 6개 축 모두
0건입니다. 고객 설명용 `score_evidence`, 추천 사유, `key_ingredients`는 effect top3를
계속 사용하며 숫자상 성분근거 top3와는 별도 개념입니다.

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
| `source_title` | 사용자에게 노출 가능한 근거 출처명. PMID만 단독으로 두지 않고 `PubMed 등재 연구 자료 (PMID 12345678)`처럼 표시 |
| `source_url` | 근거 출처 URL (선택, 비어 있을 수 있음) |
| `summary` | 상품 상세에 그대로 노출 가능한 사용자용 근거 문장. `role`, `tier`, `status`, `canonical`, `pmid` 같은 내부 관리용 표기는 포함하지 않음 |
| `source_type` | 선택. `paper`, `mfds`, `official`, `manufacturer`, `commerce`, `unknown` |
| `pmid` | 선택. PubMed PMID |
| `doi` | 선택. 논문 DOI |
| `source_authority_score` | 선택. 출처 신뢰도 보정값 `0.0~1.0` |
| `canonical_evidence_key` | 근거 식별키. `PMID:<id>` 우선, PMID가 없으면 `DOI:<normalized-doi>`, 둘 다 없으면 검수된 내부 키 |
| `review_status` | 검수 상태: `candidate_unverified`, `accepted`, `rejected` |
| `result_direction` | 결과 방향: `positive`, `negative`, `null`, `unclear` |
| `score_use_level` | 점수 사용 등급: `primary`, `supporting`, `reference_only` |
| `is_representative` | 고객·관리자 화면의 대표 근거 여부. 현재 백필에서는 모두 `false` |
| `representative_rank` | 대표 순서 `1`~`3`. 대표가 아니면 빈 값 |
| `is_current` | 현재 근거 연결의 활성 여부. 입력에서 사라진 기존 DB 행은 삭제하지 않고 `false`로 전환 |
| `review_note` | 보류·기각·상충·전문 미확보 등 검수 근거 (선택) |
| `reviewed_by` | 검수자 식별자 (선택) |
| `reviewed_at` | timezone이 포함된 ISO 8601 검수 시각 (선택) |

`accepted` 또는 `rejected` 행에는 `reviewed_by`와 `reviewed_at`이 필요합니다. 대표 근거는
`accepted + is_current=true`인 행만 지정할 수 있으며, `representative_rank`는 1~3만 허용합니다.

이 상태 컬럼은 근거 검수 이력을 저장하기 위한 계약입니다. 현재 런타임은 `accepted-only`,
사람 adjudication 또는 전문 확인 게이트를 적용하지 않으며 `review_status`를 점수 필터로
사용하지 않습니다. 대표 근거 노출 자격과 점수 활성 여부는 별개입니다.

점수 계산과 고객 노출은 분리합니다. 상품 상세 API의 근거 제목·요약·출처는
`review_status=accepted`이면서 `is_current=true`인 행만 반환합니다. `candidate_unverified`는
내부 점수 계산에 사용될 수 있어도 고객 화면이나 외부 claim 근거로 노출하지 않습니다.

`source_authority_score`는 추후 아래처럼 근거 점수 보정에 사용할 수 있습니다.

```text
adjusted_evidence_score = evidence_score / 100 * source_authority_score
```

### 신규 논문 후보 DB

주간 PubMed 수집 결과는 기존 `ingredient_evidence`에 바로 넣지 않고
`evidence_discovery_candidates`에 영구 보관합니다. 이 후보 승격 절차는 대표 근거 등록과
외부 클레임 관리를 위한 것이며, 공식 기능 prior의 effect 점수 운영 승인 조건은 아닙니다.

| 컬럼 | 설명 |
| --- | --- |
| `discovery_key` | 수집기가 만든 성분×효능×논문 식별키 |
| `ingredient_id`, `effect_id` | 검수 대상 성분×효능 DB FK |
| `paper_key` | PMID 우선, 없으면 정규화 DOI |
| `pmid`, `doi` | 외부 논문 식별자 |
| `title`, `journal`, `publication_date_text` | 논문 표시용 서지정보 |
| `publication_types`, `authors`, `abstract_excerpt` | 검수 보조 메타데이터 |
| `source_url`, `search_query` | 원문 링크와 실제 검색식 |
| `first_seen_at`, `last_seen_at` | 최초·최근 자동 발견 시각 |
| `review_status` | `candidate_unverified`, `accepted`, `rejected` |
| `review_note`, `reviewed_by_user_id`, `reviewed_at` | 사람 판정 정보 |
| `promoted_evidence_id` | 승인 시 생성·갱신된 `ingredient_evidence.id` |

동일 `(ingredient_id, effect_id, paper_key)`는 한 후보만 허용합니다. 주간 검색에 다시 노출되면
새 행을 만들지 않고 `last_seen_at`과 서지정보만 갱신합니다. 판정 이력은
`evidence_discovery_reviews`에 별도 행으로 보존합니다.

승인 경계:

- `candidate_unverified`: 후보 테이블에만 존재, 점수 미반영
- `rejected`: 후보와 판정 이력만 보존, `ingredient_evidence` 미생성
- `accepted`: 관리자 입력값으로 `ingredient_evidence`를 생성·갱신하고 두 행을 연결
- `negative`, `null`, `unclear`: 현재는 `reference_only + evidence_score=0`만 허용

정본 경계:

- `data/ingredient_evidence.csv`는 기존 검증 근거의 baseline seed 정본이다.
- 자동 수집 이후 신규 후보·판정 이력·승인 근거는 운영 DB가 정본이다.
- seed는 후보에서 승격된 `ingredient_evidence`를 CSV 누락 행으로 보아 비활성화하지 않는다.
- 후보·판정 테이블은 일반 카탈로그 clean seed 대상이 아니며 운영 DB 백업 대상이다.

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

### `data/products.csv` 또는 `data/products/*.csv`

상품 데이터는 기본적으로 `data/products.csv` 단일 파일을 사용할 수 있습니다. 상품 수가 많아 단일 파일이 커지는 경우 `data/products/` 디렉터리에 같은 헤더의 CSV 조각을 나눠 둘 수 있습니다. 현재 loader는 `products.csv`가 없고 `products/` 디렉터리가 있으면 `products/*.csv`를 모두 읽습니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `brand` | 브랜드명 |
| `name` | 상품명 |
| `category` | 상품 카테고리. 예: `toner`, `serum`, `cream`, `lotion` |
| `released_at` | 선택. 실제 출시일 또는 출시 시각. ISO-8601 형식 (`2026-07-12` 또는 `2026-07-12T00:00:00Z`). 신상품 정렬의 우선 기준 |
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

- 상품 CSV는 자사몰 카탈로그이므로 상품을 가능한 한 보존합니다.
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

예를 들어 사용자가 `건성`, `높음`이고 상품의 `dry_fit=0.9`, `sensitive_fit=0.8`이면:

```text
skin_profile_score = 0.9 * 0.6 + 0.8 * 0.4 = 0.86
```

### `data/product_ingredients.csv` 또는 `data/product_ingredients/*.csv`

상품-성분 매핑 데이터는 기본적으로 `data/product_ingredients.csv` 단일 파일을 사용할 수 있습니다. 행 수가 많아 단일 파일이 커지는 경우 `data/product_ingredients/` 디렉터리에 같은 헤더의 CSV 조각을 나눠 둘 수 있습니다. 현재 loader는 `product_ingredients.csv`가 없고 `product_ingredients/` 디렉터리가 있으면 `product_ingredients/*.csv`를 모두 읽습니다.

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

Seed는 상품×성분 pair를 insert/update하지만 CSV에서 사라진 과거 pair를 자동 삭제하지 않습니다. 기존 `ingredient_id`를 새 canonical ID로 바꾸는 배치는 이전 연결이 함께 남지 않도록 clean DB reseed 또는 별도 cleanup을 거쳐야 합니다. 2026-07-11 exact 성분 5종 분리 배치는 clean dev reseed를 전제로 합니다.

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

현재 repo에 포함된 행은 P2 홈 추천 파이프라인 검증용 mock 데이터입니다. `source=mock_p2_home`인 값은 실제 리뷰·판매·행동 로그가 아니며, 화면/추천 로직 연결 확인에만 사용합니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 고유 ID |
| `review_count` | 과거 수집 스냅샷의 리뷰 수. runtime 인기·검색·추천에는 사용하지 않음 |
| `average_rating` | 과거 수집 스냅샷의 평균 평점. runtime에는 사용하지 않음 |
| `sales_count` | 판매량. 있으면 가장 직접적인 인기 신호 |
| `sales_rank` | 판매 랭킹. `sales_count`가 없을 때 사용하며 낮을수록 좋음 |
| `recent_view_count` | 최근 14일 조회 수 |
| `wishlist_count` | 최근 14일 찜 수 |
| `cart_add_count` | 최근 14일 장바구니 담기 수 |
| `source` | 데이터 출처. 예: `mock_p2_home`, `crawler`, `event_log` |
| `updated_at` | 지표 스냅샷 기준 시각 |

인기 점수 원칙:

- 인기 섹션은 이 파일 또는 동일한 DB 필드가 있을 때만 산출합니다.
- 가격, 이미지 존재, 성분 점수, `AUTO_SEED` 재고를 인기 신호처럼 쓰지 않습니다.
- 판매량과 최근 행동 수치는 `log1p` 정규화합니다.
- 리뷰 수와 평점은 `product_reviews`의 rollup 결과만 사용하며 시장 인기 점수에 섞지 않습니다.
- 판매량이 없고 판매 랭킹만 있으면 log 기반 역순 랭킹 점수를 사용합니다.

`product_popularity_metrics.review_count`, `average_rating` 컬럼은 migration 호환을 위해 남아 있지만 deprecated입니다. 상품 상세, 추천, 일반 검색, 인기상품, ES 문서는 `product_review_metrics`만 authoritative source로 사용합니다.

### `data/storefront_product_reviews/*.csv`

P2 자사몰 상품 상세 화면의 리뷰 목록에 사용할 리뷰 원문 데이터입니다. 파일 크기를 줄이기 위해 `data/storefront_product_reviews/` 디렉터리에 같은 헤더의 CSV 조각을 나눠 둘 수 있습니다.

현재 리뷰 데이터는 올리브영 공개 리뷰를 기준으로 수집한 리뷰 seed이며, 리뷰 이미지 URL은 포함하지 않습니다. 한 행은 리뷰 1개를 의미합니다.

| 컬럼 | 설명 |
| --- | --- |
| `review_id` | 자사몰 리뷰 seed 기준 고유 ID |
| `product_id` | 리뷰가 연결되는 상품 ID. `products.csv` 또는 `products/*.csv`의 `product_id`를 참조 |
| `source` | 리뷰 출처. 예: `oliveyoung` |
| `source_review_id` | 원본 출처의 리뷰 식별자. 중복 제거와 재수집 대조용 |
| `rating` | 별점. 1~5 스케일 |
| `review_text` | 리뷰 본문 |
| `review_date` | 리뷰 작성일. 원본에서 확인 가능한 경우 입력 |
| `option_text` | 리뷰 작성자가 구매한 옵션/구성 원문 |
| `helpful_count` | 도움이 됐어요 수 |
| `review_type` | 리뷰 구분. 예: `month_use`, `general` |
| `is_month_use_review` | 한달사용 리뷰 여부. `true` 또는 `false` |
| `is_repurchase` | 재구매 리뷰 여부. `true` 또는 `false` |
| `has_photo` | 사진 리뷰 여부. 사진 URL은 저장하지 않고 존재 여부만 저장 |
| `review_badge_labels` | 원본 리뷰에 붙은 배지 문구. 예: `한달이상사용;재구매` |
| `reviewer_skin_type_label_ko` | 작성자 피부 타입 라벨. 예: `건성`, `지성`, `복합성`, `민감성` |
| `reviewer_skin_tone_label_ko` | 작성자 피부 톤 라벨. 예: `봄웜톤`, `여름쿨톤` |
| `reviewer_skin_trouble_labels_ko` | 작성자 피부 고민 라벨. 여러 값은 `;`로 구분 |
| `reviewer_profile_labels_ko` | 피부 타입, 톤, 고민을 합친 사용자 노출용 프로필 라벨. 여러 값은 `;`로 구분 |
| `collected_at` | 리뷰 수집 시각 |

운영 원칙:

- 리뷰 원문은 상품 상세 노출용 seed 데이터입니다.
- 리뷰 작성자의 닉네임, 프로필 이미지, 리뷰 첨부 이미지는 저장하지 않습니다.
- `review_id`는 전체 split 파일에서 중복되면 안 됩니다.
- 같은 `source + product_id + source_review_id`가 다시 수집되면 기존 리뷰 갱신 또는 중복 제거 대상으로 처리합니다. 원본 `source_review_id`는 상품 범위에서만 유일할 수 있습니다.
- 이 파일은 리뷰 목록 노출을 위한 데이터이며, 추천 점수 반영 여부를 직접 확정하지 않습니다.

DB 정규화 원칙:

- 원본 리뷰는 `product_reviews`, 정규화된 작성자 피부 라벨은 `product_review_profile_labels`에 저장합니다.
- `review_type=one_month_review`와 `is_month_use_review=true`는 DB에서 `MONTH_USE`로 정규화합니다. 일반 리뷰는 `GENERAL`을 사용합니다.
- `has_photo`는 원본에 사진이 있었다는 표식일 뿐입니다. 실제 미디어 행이나 공개 URL이 없으므로 리뷰 이미지로 노출하지 않습니다.
- 상품 집계는 `product_review_metrics`, 피부 타입·민감도·고민·톤별 집계는 `product_review_segment_metrics`가 담당합니다.
- 집계 테이블은 원본 CSV 값을 그대로 적재하지 않고, 게시 상태의 원본 리뷰에서 재계산할 수 있는 파생 read model로 관리합니다.
- 원본 변경 감지는 `source_content_hash`, 프로필 라벨 재매핑은 `profile_mapping_version`으로 구분합니다.
- 자사몰 구매 리뷰는 `source=mubarelle`, `review_type=GENERAL`, `verified_purchase=true`로 저장하고 본인 배송완료 주문 상품의 `order_item_id`를 참조합니다.
- 자사몰 구매 리뷰 본문은 공백 제거 후 1~2,000자이며 별점 1~5가 필수입니다. 외부 seed의 누락 가능성을 유지하기 위해 이 입력 제약은 API에서 강제합니다.
- 자사몰 리뷰는 작성 시점의 저장 피부 타입·민감도·피부 고민을 `product_review_profile_labels`에 snapshot하며 이후 프로필 변경으로 과거 라벨을 바꾸지 않습니다.
- 사용자 삭제는 `status=DELETED` tombstone으로 남기되 별점·본문·옵션·재구매·구매 인증·source metadata와 프로필 라벨을 제거합니다. 삭제 행은 공개 조회와 집계에서 제외합니다.
- 같은 `order_item_id + review_type`에는 활성 리뷰 하나만 허용하며, 삭제 후 재작성은 기존 tombstone을 재활성화합니다.

리뷰 집계 점수 원칙:

- 원본 1건의 기본 가중치는 `source 1.0 × 한달사용 배율 × 구매확인 배율 × helpful 최대 1.10 × recency`입니다.
- `source=oliveyoung` seed는 현재 전량이 `MONTH_USE`이고 원본 구매확인 값도 없으므로 한달사용·구매확인 배율을 모두 `1.0`으로 둡니다. 이 두 필드로 같은 소스 안의 리뷰를 차등하지 않습니다.
- 자사몰 `source=mubarelle`의 `verified_purchase=true`는 실제 배송완료 주문 검증 신호이므로 `1.10`을 유지합니다. OliveYoung 이외 소스의 한달사용·구매확인 값은 기존 배율 `1.15`·`1.10`을 유지하되, 신규 소스 도입 시 신호의 실재 여부를 별도 확인합니다.
- helpful은 `1 + 0.10 × min(log(1 + helpful_count) / log(21), 1)`을 사용합니다.
- recency는 `0.5 + 0.5 × 2^(-age_days / 730)`이며 작성일이 없으면 `0.75`입니다.
- 카테고리 평균과 prior strength `20`으로 상품의 Bayesian 별점·재구매율·사진리뷰율을 계산합니다.
- 유효 표본 수는 Kish 공식 `(sum(w)^2 / sum(w^2))`, confidence는 `n_eff / (n_eff + 20)`입니다.
- 프로필 segment는 상품 전체 Bayesian 값을 prior로 사용합니다. 매핑 신뢰도는 segment weight에 곱합니다.
- 상품 품질 신호는 별점 `0.75`, 재구매율 `0.20`, Bayesian 사진리뷰율 `0.05`입니다. 값이 없는 신호는 분모에서 제외해 나머지 가중치를 재정규화합니다.
- 일반/한달 후기 일관성은 진단 컬럼에 계속 저장하지만 품질점수 합성에는 사용하지 않습니다.
- `has_photo`는 이미지 노출용 데이터가 아니라 상품 단위 사진리뷰율 집계에만 사용합니다. 프로필 affinity에는 사용하지 않습니다.
- 집계 버전은 `review_quality_v2`입니다. migration 적용 뒤 전체 재집계를 완료한 행만 v2가 됩니다.

### `data/product_review_summary.csv`

상품별 리뷰 요약 통계입니다. 상품 카드, 상품 상세 리뷰 요약, 관리자 QA에서 사용할 수 있는 집계 데이터입니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 ID |
| `brand` | 브랜드명 |
| `product_name` | 상품명 |
| `category` | 상품 카테고리 |
| `is_recommendable` | 기본 추천 후보 포함 여부 |
| `review_count` | 전체 리뷰 수 |
| `avg_rating` | 평균 별점. 0~5 스케일 |
| `month_review_count` | 한달사용 리뷰 수 |
| `month_review_rate` | 전체 리뷰 중 한달사용 리뷰 비율. 0.0~1.0 |
| `repurchase_count` | 재구매 리뷰 수 |
| `repurchase_rate` | 전체 리뷰 중 재구매 리뷰 비율. 0.0~1.0 |
| `photo_review_count` | 사진 리뷰 수 |
| `photo_review_rate` | 전체 리뷰 중 사진 리뷰 비율. 0.0~1.0 |
| `profile_review_count` | 피부 프로필 라벨이 있는 리뷰 수 |
| `profile_review_rate` | 전체 리뷰 중 피부 프로필 라벨이 있는 리뷰 비율. 0.0~1.0 |
| `avg_helpful_count` | 리뷰 1개당 평균 도움이 됐어요 수 |
| `top_skin_types` | 많이 등장한 피부 타입 요약. 예: `건성:120;복합성:80` |
| `top_skin_tones` | 많이 등장한 피부 톤 요약 |
| `top_skin_troubles` | 많이 등장한 피부 고민 요약 |
| `review_confidence` | 리뷰 통계 신뢰도. `high`, `medium`, `low` |

### `data/product_review_profile_stats.csv`

상품별로 피부 타입, 피부 톤, 피부 고민 라벨에 따른 리뷰 반응을 집계한 데이터입니다. 한 행은 `product_id + profile_group + profile_label_ko` 조합을 의미합니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 ID |
| `brand` | 브랜드명 |
| `product_name` | 상품명 |
| `category` | 상품 카테고리 |
| `profile_group` | 프로필 그룹. 예: `skin_type`, `skin_tone`, `skin_trouble` |
| `profile_label_ko` | 프로필 라벨. 예: `건성`, `트러블`, `블랙헤드` |
| `review_count` | 해당 프로필 라벨이 붙은 리뷰 수 |
| `avg_rating` | 해당 프로필 라벨 리뷰의 평균 별점 |
| `repurchase_count` | 해당 프로필 라벨 리뷰 중 재구매 리뷰 수 |
| `repurchase_rate` | 해당 프로필 라벨 리뷰 중 재구매 리뷰 비율 |
| `photo_review_count` | 해당 프로필 라벨 리뷰 중 사진 리뷰 수 |
| `photo_review_rate` | 해당 프로필 라벨 리뷰 중 사진 리뷰 비율 |
| `avg_helpful_count` | 해당 프로필 라벨 리뷰의 평균 도움이 됐어요 수 |
| `profile_confidence` | 프로필별 통계 신뢰도. `high`, `medium`, `low` |

### `data/product_review_signals.csv` (선택)

리뷰 데이터를 추천에 활용하기 위해 과거에 만든 보조 신호 CSV입니다. 현재 runtime은 이 파일을 읽지 않고 `product_reviews`에서 계산한 `product_review_metrics`, `product_review_segment_metrics`를 단일 집계 원천으로 사용합니다.

| 컬럼 | 설명 |
| --- | --- |
| `product_id` | 상품 ID |
| `brand` | 브랜드명 |
| `product_name` | 상품명 |
| `category` | 상품 카테고리 |
| `review_count` | 전체 리뷰 수 |
| `avg_rating` | 평균 별점 |
| `repurchase_rate` | 재구매 리뷰 비율 |
| `photo_review_rate` | 사진 리뷰 비율 |
| `profile_review_rate` | 피부 프로필 라벨이 있는 리뷰 비율 |
| `review_confidence` | 리뷰 통계 신뢰도 |
| `review_signal_score` | 리뷰 기반 보조 신호 종합 점수. 0.0~1.0 |
| `rating_signal_score` | 평균 별점 기반 보조 점수. 0.0~1.0 |
| `repurchase_signal_score` | 재구매 비율 기반 보조 점수. 0.0~1.0 |
| `confidence_signal_score` | 리뷰 수와 프로필 라벨 충분성 기반 보조 점수. 0.0~1.0 |
| `review_signal_reason` | 보조 신호 산출 이유 요약 |

운영 원칙:

- 이 파일은 과거 QA·대조용 산출물이며 runtime scoring 입력이 아닙니다.
- 실제 추천은 `review_quality 7%`, `review_profile_affinity 5%` 기본축을 사용합니다.
- 세부 공식과 동적 배수는 `docs/backend-scoring-v0.md`를 기준으로 확인합니다.
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
- 상품 이미지 노출은 상품 CSV의 `thumbnail_url`, `image_urls`보다 `product_image_assets.csv`를 우선 사용합니다.
- 상품 CSV의 `thumbnail_url`, `image_urls`는 원본 수집값 확인용 보조 컬럼입니다.
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

## 현재 점수 정책

- 성분효능점수는 효능 단위로 계산합니다.
- 같은 효능이 여러 고민에서 중복 도출되어도 효능 자체는 한 번만 반영합니다.
- 하나의 효능에 여러 유효 성분이 있으면 상위 3개 성분을 반영합니다.
- 상위 3개 성분은 `1.0 / 0.5 / 0.25` 감쇠계수를 적용합니다.
- 성분효능 top3는 `effect_score`, 성분근거 top3는
  `evidence_score × source_authority_score` 기준으로 각각 독립 선발합니다.
- 상품 근거와 리뷰 품질·유사 프로필 affinity를 추천 점수에 반영합니다.
- 위험성분은 항상 표시하며 민감도 `높음` 사용자에게만 penalty를 적용합니다.
- `v6_independent_evidence_top3`는 성분효능, 독립 성분근거 top3, 피부프로필, 함량,
  기능성, 검색, 가격, 인기, 스킨테스트, 행동, 리뷰 품질, 리뷰 affinity를 사용합니다.
- 함량 점수는 `product_ingredients.csv`와 `ingredient_effect_ranges.csv`를 사용합니다.
- 피부타입/민감도 개인화는 `product_skin_profiles.csv`가 채워지는 즉시 `skin_profile_score`에 반영할 수 있습니다.

## 검수 체크리스트

- [ ] 파일명이 이 문서와 일치한다.
- [ ] 필수 컬럼이 누락되지 않았다.
- [ ] ID 값이 다른 파일의 참조와 일치한다.
- [ ] 실제 secret 또는 개인 정보가 없다.
- [ ] 빈 값 허용 필드는 프론트/백엔드에서 처리 가능한 값으로 남겼다.
- [ ] 예시 파일은 실제 운영 데이터와 섞이지 않는다.
