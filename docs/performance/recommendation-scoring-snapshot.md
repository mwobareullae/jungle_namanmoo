# 추천 스코어링 Snapshot Read Model

Opt4는 상품별 추천 스코어링 입력을 `product_recommendation_scoring_snapshots`에 미리 저장한다. 요청 시에는 후보 상품 ID로 snapshot을 한 번에 조회하고, 누락되거나 버전이 맞지 않거나 payload를 해석할 수 없는 상품만 기존 loader로 보완한다.

최종 점수, 순위, 검색 조건, 사용자 프로필은 snapshot에 저장하지 않는다. 추천 점수 공식과 API 계약도 변경하지 않는다.

## 최초 적용

서버의 저장소 루트에서 migration, 상품 특징, snapshot 순서로 실행한다.

```bash
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --full --batch-size 500
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_snapshots --full --batch-size 500
```

snapshot은 상품 특징 rollup 결과를 입력으로 사용하므로 두 rollup의 순서를 바꾸지 않는다. 같은 명령을 다시 실행해도 `product_id` 기준 UPSERT로 행이 중복되지 않는다.

## 선택 재집계

상품 데이터가 일부 변경되면 상품 특징을 먼저 갱신하고 같은 상품 ID의 snapshot을 갱신한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --product-id 101 --product-id 205 --batch-size 100
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_snapshots --product-id 101 --product-id 205 --batch-size 100
```

DB에 반영하지 않고 결과만 확인하려면 `--dry-run`을 사용한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_snapshots --full --batch-size 500 --dry-run
```

## Benchmark 준비와 검증

`benchmarkctl prepare <dataset>`은 migration과 seed 뒤에 상품 특징과 snapshot을 생성한다. `verify <dataset>`은 다음 조건을 검사하며 하나라도 맞지 않으면 실패한다.

- 상품 수와 snapshot 행 수가 동일함
- 모든 행의 `snapshot_version`이 현재 코드 버전과 동일함
- 기존 상품, 검색 문서, Elasticsearch 검증을 통과함

```bash
BENCHMARK_CONFIG_FILE=/home/ubuntu/mwobareullae-benchmark/config.benchmark.env \
./scripts/perf/benchmarkctl prepare 80000

BENCHMARK_CONFIG_FILE=/home/ubuntu/mwobareullae-benchmark/config.benchmark.env \
./scripts/perf/benchmarkctl verify 80000
```

실제 서버 부하 측정과 k6 실행은 이 변경 범위에 포함하지 않는다.

## 관측 지표

추천 완료 structured log에서 다음 필드를 확인한다. snapshot payload 자체는 로그에 남기지 않는다.

- `scoring_snapshot_load_ms`: snapshot 일괄 조회와 payload 변환 시간
- `scoring_snapshot_hit_count`: 현재 버전 snapshot을 사용한 후보 수
- `scoring_snapshot_miss_count`: 기존 loader로 보완한 후보 수
- `scoring_snapshot_fallback_ms`: 누락 후보의 기존 loader 실행 시간
- `scoring_snapshot_parse_error_count`: payload 해석 실패로 fallback한 후보 수

성능 수치는 실제 서버에서 동일 조건으로 측정한 뒤 별도 결과 기록에 작성한다.
