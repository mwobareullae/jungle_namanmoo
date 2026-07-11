# accepted-only 근거 게이트 영향 측정

> 작성일: 2026-07-11
>
> 상태: 읽기 전용 분석. scoring 코드와 DB는 변경하지 않았다.

## 재현 방법

```bash
python data/scripts/analyze_evidence_gate_impact.py
```

Source manifest SHA256: `e74859cf139df58efe0380601ef8bbb9bbf31f73ae7ea831962a1544b2defaa8`

## 전체 요약

- 추천 가능 상품: 10,164개
- 현재 근거점수가 하나라도 있는 상품: 9,426개
- accepted-only 후 근거점수가 남는 상품: 3,080개
- accepted 근거쌍: 4개
- 상품×효능 조합: 41,186개

## 효능축별 영향

| 효능축 | 상품×축 | 현재 근거 있음 | 게이트 후 근거 있음 | 평균 근거점수 현재→후 | 평균 총점 감소 추정 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 각질 | 7,766 | 7,766 | 0 | 0.339→0.000 | 7.80점 |
| 미백·톤 | 3,746 | 3,746 | 0 | 0.828→0.000 | 19.05점 |
| 보습·장벽 | 9,234 | 9,234 | 2,417 | 0.915→0.083 | 19.12점 |
| 여드름·피지 | 4,046 | 4,046 | 402 | 0.513→0.016 | 11.42점 |
| 주름·탄력 | 7,302 | 7,302 | 0 | 0.683→0.000 | 15.71점 |
| 진정 | 9,092 | 9,092 | 754 | 0.582→0.042 | 12.44점 |

## accepted 4쌍의 상품 범위

| 성분×효능 | 해당 성분 포함 추천상품 | top 3에 들어 게이트 후 점수에 기여 |
| --- | ---: | ---: |
| centella_asiatica × 진정 | 754 | 754 |
| centella_asiatica × 보습·장벽 | 754 | 193 |
| niacinamide × 보습·장벽 | 2,694 | 2,242 |
| retinol × 여드름·피지 | 415 | 402 |

## 판정

- 단일 효능 질의 기준 총점 감소 추정 중앙값은 14.20점, 평균은 14.14점이다.
- 이 값은 기본 가중치에서 근거점수 항목만 바꾼 추정치이며 검색·가격·피부 적합 등 다른 점수는 유지한 값이다.
- 미백·주름·각질 축에는 accepted 근거가 아직 없어 게이트를 즉시 켜면 해당 축의 근거점수가 전부 0이 된다.
- 따라서 PR #434에서는 상태를 저장하되 accepted-only 점수 게이트는 활성화하지 않는다.

## Source manifest

| 파일 | SHA256 |
| --- | --- |
| `data/products/products_000.csv` | `304e60cd3ddef4a2533bbac36a214ceafa4b8e352f5f8d332a51d15cae7cdd73` |
| `data/products/products_001.csv` | `bd76a0d01b6f52c93cc813bd8328df398edaa313506ff6c1d725638047ca44ad` |
| `data/products/products_002.csv` | `ba2f974d3a521b020fbbdc8289ed4cdf8e2c6caf56e4c66a919df09f343a5baf` |
| `data/product_ingredients/product_ingredients_000.csv` | `4e42511cbcfbae49bd795c44f560c7fa0864ffbecc43a67f159093150124d850` |
| `data/product_ingredients/product_ingredients_001.csv` | `6d2ba436989e392c940f9be54cd6d382d6eaf8cb6e1f36a1e3ea397300087e5d` |
| `data/product_ingredients/product_ingredients_002.csv` | `4271f615da337c5f39ee2a6e26e92e304eefb63c9024d10406672355c621d4a7` |
| `data/product_ingredients/product_ingredients_003.csv` | `a3ff9e6d91305f4505231f1a01b17bb5276dd8c76b2064753f7d87a33b0f57ae` |
| `data/product_ingredients/product_ingredients_004.csv` | `e34c663a799af78b6e5b91a047988d910597d9f93dc0cb4a733e1aebf560f393` |
| `data/ingredient_effect.csv` | `ddb884a0ec14893814bf9c6236f2d7871b0210eb8afa0f254645fc226f37eb50` |
| `data/ingredient_evidence.csv` | `5d5a1441ca2236d2e8602e11779fb6344446084d477eac53588526d7505f72c7` |
