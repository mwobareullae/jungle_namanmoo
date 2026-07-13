# Review Rollup Operations

리뷰 원문 적재 후 상품별 품질 지표와 피부 프로필별 affinity를 별도 CLI로 계산합니다. Import는 rollup을 자동 실행하지 않으며 scheduler, worker, cron도 이 저장소에서 구성하지 않습니다.

## 전체 집계

```bash
docker compose exec -T backend \
  python -m app.cli.rollup_product_reviews --full
```

## 상품 1개 재집계

CLI의 `--product-id`에는 API에서 사용하는 외부 상품 ID를 넣습니다.

```bash
docker compose exec -T backend \
  python -m app.cli.rollup_product_reviews \
  --product-id prod_oy_a000000144177
```

## 검증 실행

고정 시각을 사용하면 점수 재현성을 비교하기 쉽습니다. `--dry-run`은 계산과 DB 제약 검증까지 수행한 뒤 rollback합니다.

```bash
docker compose exec -T backend \
  python -m app.cli.rollup_product_reviews --full --dry-run \
  --computed-at 2026-07-12T00:00:00+00:00
```

상품 품질은 카테고리 prior strength 20으로 보정합니다. `review_quality_v2`는 별점 75%, 재구매율 20%, Bayesian 사진리뷰율 5%를 합성하고 effective sample confidence로 중립 0.5 쪽에 보정합니다. 사진 URL은 저장·노출하지 않으며 원본의 사진 존재 표식만 상품 품질 집계에 사용합니다. 프로필 segment는 상품 전체 점수를 prior로 사용하며, effective sample size가 5보다 작은 segment도 저장합니다. 추천 단계에서는 이 작은 segment를 중립 0.5로 처리합니다.

OliveYoung seed는 전량 `MONTH_USE`이고 구매확인 원본값이 없어 두 배율을 적용하지 않습니다. 자사몰 `mubarelle` 구매 리뷰의 `verified_purchase=true`는 실제 주문 검증 신호이므로 1.10 배율을 유지합니다.

## v2 전환 순서

1. v2 코드를 배포합니다. DB migration은 없습니다.
2. 전체 rollup을 실행해 기존 v1 행을 v2로 다시 계산합니다.
3. 추천 결과나 캐시를 별도로 저장하는 운영 환경이면 v1 결과를 무효화합니다.

코드만 배포하고 전체 rollup을 실행하지 않으면 기존 행의 값과 `score_version`은 v1로 남습니다. 코드 배포와 재집계 완료 시점을 함께 기록합니다.

일반 검색 ES 문서의 평점·리뷰 수도 갱신해야 하면 리뷰 rollup을 커밋한 뒤 행동 인기 점수를 먼저 갱신하고 full reindex를 실행합니다. 행동 인기 집계는 기존 seed에 남아 있을 수 있는 리뷰 기반 인기 점수를 행동 데이터 전용 점수로 교체합니다. catalog reindex는 문서만 다시 만들며 embedding은 재생성하지 않습니다.

```bash
docker compose exec -T backend \
  python -m app.cli.rollup_product_popularity --window-days 7

docker compose exec -T backend \
  python -m app.cli.index_catalog_products_to_elasticsearch --full
```
