# 2,206개 상품 데이터 QA 리포트

현재 repo의 `data/*.csv` 기준 QA 요약입니다.

## 1. 전체 수량

| 항목 | 개수 |
|---|---:|
| 상품 | 2,206 |
| 가격/Offer seed | 2,206 |
| 재고 seed | 2,206 |
| 이미지 자산 row | 54,933 |
| 상품-성분 row | 91,375 |
| 성분 master | 4,697 |
| 검색/벡터 문서 | 2,206 |
| 피부타입 프로필 | 2,206 |

## 2. 연결 커버리지

| 파일/객체 | 연결 상품 수 | 누락 상품 수 | 판단 |
|---|---:|---:|---|
| `product_prices` | 2,206 | 0 | PASS |
| `product_inventory` | 2,206 | 0 | PASS |
| `product_image_assets` | 2,206 | 0 | PASS |
| `product_ingredients` | 2,205 | 1 | 확인 필요 |
| `product_skin_profiles` | 2,206 | 0 | PASS |
| `vector_docs` | 2,206 | 0 | PASS |

## 3. 카테고리 분포

| 값 | 개수 |
|---|---:|
| `serum` | 879 |
| `cream` | 724 |
| `toner` | 349 |
| `lotion` | 254 |

## 4. 추천 가능 여부

| 값 | 개수 |
|---|---:|
| `true` | 1,455 |
| `false` | 751 |

## 5. 추천 제외 사유

| 값 | 개수 |
|---|---:|
| `duplicate_variant_hidden` | 307 |
| `mixed_set_composition` | 184 |
| `male_targeted` | 142 |
| `all_in_one` | 125 |
| `eye_neck_specific` | 76 |
| `data_quality_review` | 65 |
| `spot_treatment` | 13 |
| `missing_ingredients` | 2 |

## 6. 이미지 상태

| 항목 | 값 |
|---|---:|
| 전체 이미지 row | 54,933 |
| `source_image_url` 존재 | 54,933 |
| `public_url` 존재 | 54,933 |
| 상세 이미지 없는 상품 | 4 |
| 대표 이미지 없는 상품 | 0 |

| 값 | 개수 |
|---|---:|
| `detail` | 52,727 |
| `thumbnail` | 2,206 |

## 7. 성분/함량 상태

| 항목 | 값 |
|---|---:|
| 상품-성분 중복 pair | 0 |
| 중복 pair가 있는 상품 | 0 |
| 그중 추천 가능 상품 | 0 |

### content_confidence

| 값 | 개수 |
|---|---:|
| `unknown` | 68,573 |
| `medium` | 21,337 |
| `high` | 1,042 |
| `low` | 423 |

### concentration_confidence

| 값 | 개수 |
|---|---:|
| `unknown` | 88,659 |
| `medium` | 1,258 |
| `high` | 1,042 |
| `low` | 416 |

## 8. 기능성 표시 상태

| 값 | 개수 |
|---|---:|
| `FUNCTIONAL_CONFIRMED` | 1,257 |
| `NOT_FUNCTIONAL` | 948 |
| `UNKNOWN` | 1 |

## 9. QA 결론

- 가격, 재고, 이미지, 성분, 벡터 문서 연결은 현재 기준으로 전 상품 커버됩니다.
- `mixed_set_composition` 정책으로 세트/기획 구성 상품은 카탈로그에는 남고 기본 추천에서는 제외됩니다.
- 상품-성분 중복 pair는 0건입니다. 동일 상품 안에서 같은 성분이 반복 추출되면 `product_id + ingredient_id` 기준으로 1행만 남깁니다.
- 다음 단계는 5천~1만 건으로 스케일을 키워도 같은 QA 규칙이 통과하는지 확인하는 것입니다.
