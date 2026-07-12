# 10만 상품 Feed Schema 초안

목표는 원본 feed를 바로 운영 테이블에 넣지 않고, staging 검증 → bulk upsert → QA 리포트 → rollback 가능 상태로 정규화하는 것입니다.

## 1. 원본 feed 최소 컬럼

| 컬럼 | 필수 | 설명 | 정규화 대상 |
|---|---|---|---|
| `row_id` | Y | feed 내부 고유 row id. 없으면 `source_name + source_product_id`로 생성 | staging 추적 |
| `source_name` | Y | 원본 출처. 예: `oliveyoung`, `manual_feed` | DataSource |
| `source_product_id` | Y | 원본 사이트/공급사 상품 ID | Product source ref |
| `source_url` | Y | 원본 상품 상세 URL | QA 추적용 |
| `brand` | Y | 브랜드명 | Product/Brand |
| `product_name` | Y | 상품명 | Product |
| `category` | Y | `toner`, `serum`, `cream`, `lotion` 등 지원 카테고리 | ProductCategory |
| `price` | Y | 자사몰 기준 판매가 seed. 원 단위 정수 | Offer |
| `currency` | Y | 기본 `KRW` | Offer |
| `capacity_value` | N | 용량 숫자 | Product/QA |
| `capacity_unit` | N | `ml`, `g` 등 | Product/QA |
| `sales_status` | N | `ON_SALE`, `SOLD_OUT`, `HIDDEN` 등 | Inventory/Offer |
| `stock_quantity` | N | 자사몰 가정 재고. 없으면 기본 seed 규칙 적용 | Inventory |
| `thumbnail_image_url` | Y | 대표 이미지 원본 URL | ProductImage queue |
| `detail_image_urls` | N | 상세 이미지 URL 목록. `;` 구분 | ProductImage queue |
| `ingredients_raw` | N | 전성분 원문 | ProductIngredient |
| `functional_review_text` | N | 기능성 심사/보고 관련 원문 | Product |
| `collected_at` | Y | 수집 시각 ISO 문자열 | QA/source registry |
| `source_checksum` | N | 원본 row 또는 핵심 필드 hash | 중복/변경 감지 |

## 2. 정규화 산출물 매핑

| 정규화 파일 | 입력 원천 | 생성 규칙 |
|---|---|---|
| `products.csv` | 브랜드/상품명/카테고리/기능성/추천 제외 정책 | canonical `product_id` 생성, 기본 추천 가능 여부 계산 |
| `product_prices.csv` | 가격/상품 URL | P2에서는 단일 셀러 `mwobareullae`의 기본 Offer seed로 해석 |
| `product_inventory.csv` | 판매 상태/재고 | 없으면 임의 seed 규칙으로 생성하되, 품절/숨김 상태는 보존 |
| `product_image_assets.csv` | 대표/상세 이미지 URL | 서버 다운로드/업로드 작업 큐. `source_image_url`, `storage_key`, `public_url` 제공 |
| `product_ingredients.csv` | 전성분 원문 | 성분 분리, 순서, 함량 표기/정규화 값 저장. 모르면 `unknown` |
| `ingredients.csv` | 성분명 | 기존 R4 성분 master를 `ingredient_id` 기준으로 보존 병합 |
| `vector_docs.csv` | 상품명/브랜드/카테고리/성분/효능 요약 | 검색/임베딩 인덱싱 입력 텍스트 생성 |

## 3. 실패 row 표준

| 컬럼 | 설명 |
|---|---|
| `job_id` | import 작업 ID |
| `row_no` | 원본 row 번호 |
| `source_name` | 출처 |
| `source_product_id` | 원본 상품 ID |
| `field` | 실패 필드 |
| `code` | `MISSING_REQUIRED`, `INVALID_PRICE`, `IMAGE_BROKEN`, `INGREDIENT_PARSE_FAILED`, `DUPLICATE_PRODUCT`, `UNSUPPORTED_CATEGORY` 등 |
| `message` | 사람이 읽을 수 있는 실패 이유 |
| `raw_ref` | 원본 row 또는 원본 URL 참조 |

## 4. 10만 import 완료 기준

- 필수 컬럼 누락 0건
- `product_id` FK 누락 0건
- 가격 양수, 통화 `KRW` 검증
- 상품별 대표 이미지 1개 이상
- 이미지/성분/가격/중복 이슈는 `DataQualityIssue` 또는 실패 row로 남김
- 실패 row CSV 다운로드 가능
- 같은 feed를 다시 넣어도 중복 생성되지 않는 idempotent upsert
- rollback 또는 이전 버전 재적용 가능

## 5. 세민 기준 다음 행동

1. 위 컬럼을 R3/R6와 잠그기
2. 현재 2,206개 CSV를 기준 fixture로 유지
3. 5천 → 1만 → 10만 순서로 staging/import 성능을 올리기
4. QA 리포트에서 critical issue가 0건일 때만 추천/검색 인덱싱으로 넘기기
