# 5천 건 확장 Dry-run 리포트

현재 2,206개 정제 데이터를 기반으로 `product_id`를 새로 부여한 5,000건 스케일 테스트 데이터를 만들고, 기존 `audit_repo_data.cjs` 검증을 그대로 수행했습니다.

이 테스트는 실상품 5천 개를 새로 수집한 것이 아니라, 10만 상품으로 가기 전에 현재 CSV 계약과 QA 로직이 더 큰 데이터에서도 깨지지 않는지 확인하는 구조 검증입니다.

## 생성 결과

| 항목 | 개수 |
|---|---:|
| 상품 | 5,000 |
| 가격/Offer seed | 5,000 |
| 재고 seed | 5,000 |
| 이미지 자산 row | 124,266 |
| 상품-성분 row | 202,642 |
| 성분 master | 4,697 |
| 검색/벡터 문서 | 5,000 |

생성 위치:

`C:\Users\tpdls\바탕 화면\나만무 시작 week1\oliveyoung_automation_1p\output\p2_data_planning\scale_test_5000\repo_data`

## Audit 결과

- 결론: `PASS: 커밋 가능한 데이터 상태입니다.`
- audit 소요 시간: `6.79초`

| 체크 | 상태 | 요약 |
|---|---|---|
| 필수 CSV 존재 | PASS | products=5000, prices=5000, inventory=5000, images=124266, product_ingredients=202642, ingredients=4697, vector_docs=5000 |
| 가격/재고/이미지/성분/벡터 매핑 | PASS | 상품별 가격, 재고, 이미지, 성분, 검색 문서 연결 여부 |
| FK 정합성 | PASS | product_id, ingredient_id 참조 무결성 |
| 자사몰 가격/재고 값 | PASS | 가격 양수, 자사몰 URL, 판매상태, 재고 수량 형식 |
| 이미지 자산 값 | PASS | 대표/상세 이미지 타입, 순서, 저장키, public_url 형식 |
| 성분/벡터 노이즈 | PASS | ILN, 표시, HYDRATING/FACE/TONIC 등 제거 대상 잔존 여부 + product_id/ingredient_id 중복 여부 |
| 추천 후보 정책 | PASS | 기본 추천 후보 3,323개 / 추천 제외 1,677개 |
| 최저가 표시 | PASS | 상품별 is_lowest=true가 정확히 1개인지 |
| 외부 가격 비교 비활성 | PASS | P2 자사몰 기준: 네이버/외부몰 가격 비교 미사용 |
| 가격 이상치 후보 | PASS | 가격 검수 후보 0개 |

## 해석

- 현재 데이터 계약은 5천 건 규모까지는 구조적으로 통과했습니다.
- `product_id + ingredient_id` 중복 pair는 0건입니다.
- 다음 실제 확장 단계는 synthetic dry-run이 아니라 원본 feed를 추가 수집해 5천~1만 실상품 기준으로 같은 audit을 통과시키는 것입니다.
- 그 전에 R3/R6와 `Offer`, `Inventory`, `Image storage`, `ImportJob/failed row` 계약을 잠그는 것이 우선입니다.
