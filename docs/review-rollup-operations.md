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

상품 품질은 카테고리 prior strength 20으로 보정합니다. 프로필 segment는 상품 전체 점수를 prior로 사용하며, effective sample size가 5보다 작은 segment도 저장합니다. 추천 단계에서는 이 작은 segment를 중립 0.5로 처리합니다. 원본의 사진 존재 표식은 통계 count에만 남고 점수에는 사용하지 않습니다.
