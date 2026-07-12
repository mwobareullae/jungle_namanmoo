# Review Import Operations

상품 리뷰 원문은 일반 상품 seed와 분리된 전용 importer로 적재합니다. 기본 데이터 경로는 `DATA_DIR=/data`이며 `storefront_product_reviews/product_reviews_*.csv`를 파일명 순서로 읽습니다.

## 사전 확인

리뷰가 참조하는 상품을 먼저 seed하고 최신 migration을 적용합니다.

```bash
docker compose exec -T backend alembic upgrade head
```

## 검증 실행

DB를 변경하지 않고 파일과 1,000개 행을 검증합니다.

```bash
docker compose exec -T backend \
  python -m app.cli.import_product_reviews --dry-run --limit 1000
```

## 제한 적재

```bash
docker compose exec -T backend \
  python -m app.cli.import_product_reviews --limit 1000
```

## 전체 적재

```bash
docker compose exec -T backend \
  python -m app.cli.import_product_reviews --full --batch-size 5000
```

특정 파일만 적재하려면 `--file storefront_product_reviews/product_reviews_000.csv`를 사용합니다. `--file`은 여러 번 지정할 수 있습니다.

CLI 결과의 `inserted`, `updated`, `unchanged` 합계는 `rows_read`와 같아야 합니다. 같은 파일을 다시 실행하면 내용과 프로필 매핑 버전이 같은 행은 `unchanged`가 됩니다. Import는 review rollup을 자동으로 실행하지 않습니다.

원본 리뷰 본문에 PostgreSQL text가 허용하지 않는 NUL(`0x00`)이 있으면 해당 바이트만 제거합니다. 리뷰 ID, 상품 ID, 출처 ID 같은 필수 식별자에 NUL이 있으면 적재를 실패시킵니다.
