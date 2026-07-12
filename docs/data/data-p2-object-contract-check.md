# P2 데이터 객체 계약 검증표

엑셀 명세의 `Product / Offer / Inventory / Image / Ingredient / VectorDoc` 기준으로 현재 repo 데이터를 점검한 결과입니다.

| 객체 | 엑셀/P2 요구 | 현재 파일 | 현재 상태 | 판단 | 남은 합의/리스크 |
|---|---|---|---|---|---|
| Product | canonical 상품 master. 브랜드, 상품명, 카테고리, 추천 가능 여부, 기능성 정보 | `data/products.csv` | 2,206개. `product_id`, `brand`, `name`, `category`, `is_recommendable`, 기능성 컬럼 존재 | 적합 | `is_recommendable`, `recommend_exclude_reason`은 백엔드 `Product` dataclass/load/seed/DB에 반영됨. 기본 추천 후보는 `is_recommendable=true`만 사용 |
| Offer | 실제 판매 단위. `seller_id + product_id + price + status` | `data/product_prices.csv` | 2,206개. 현재는 `product_id`, `mall_name`, `price`, `product_url`, `is_lowest`, `currency` | P2 단일 셀러 seed로는 사용 가능 | 명시적 `offer_id`, `seller_id`, `offer_status`는 없음. 현재 문서대로 백엔드가 `product_id` 기준 기본 offer를 생성/매핑해야 함 |
| Inventory | offer별 재고와 품절/판매 상태 | `data/product_inventory.csv` | 2,206개. `stock_quantity`, `sales_status`, `safety_stock` 존재 | P2 단일 offer 기준 적합 | 마켓/다중 셀러 확장 전에는 충분. 다만 DB에서는 offer 기준으로 연결되어야 함 |
| Image | 대표/상세 이미지 자산. 서버가 저장소로 이관할 작업 큐 | `data/product_image_assets.csv` | 54,933개. `thumbnail/detail`, `source_image_url`, `storage_key`, `public_url` 존재 | 적합 | 현재는 파일 직접 저장이 아니라 매니페스트. R6/백엔드가 서버에서 다운로드 후 storage 업로드 처리 필요 |
| Ingredient | 성분 master + 상품-성분 연결 + 함량/순서 | `data/ingredients.csv`, `data/product_ingredients.csv` | 성분 4,697개, 상품-성분 91,375행 | 적합 | 일부 세트/기획 상품은 성분이 섞일 수 있어 `mixed_set_composition`으로 기본 추천 제외 처리. 성분 master의 영어명/설명은 R4 관리값 보존 필요 |
| VectorDoc | 검색/임베딩 인덱싱용 문서 | `data/vector_docs.csv` | 2,206개. 상품별 검색 문서 1개 구조 | P2/P3 인덱싱 입력으로 적합 | 10만 이상에서는 `index_version`, reindex job, cursor 검색/ES 또는 pgvector 인덱싱 정책이 R4/R6와 연결되어야 함 |

## 결론

- 현재 CSV는 P2 자사몰 seed와 10만 feed dry-run의 기준 데이터로 사용할 수 있습니다.
- 세민 담당 범위에서 바로 고칠 수 있는 핵심은 `data-contract.md`와 CSV 산출물입니다.
- 백엔드는 `is_recommendable`, `recommend_exclude_reason`을 DB에 저장하고 기본 추천 후보 필터로 사용합니다. 기본 offer 매핑은 R3 원우와 별도 계약 확인이 필요합니다.
- R5가 API 응답 구조를 임의 변경하면 역할 침범이므로, 필요한 변경은 문서/검증표로 먼저 제안하는 방식이 맞습니다.
