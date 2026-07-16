# 추천 스코어링 Compact Read Model (Opt4b)

Opt4b는 후보 상품의 안정적인 스코어링 입력을
`product_recommendation_scoring_read_models`에 평탄화해 저장한다. 요청 시 후보
상품 ID 전체를 한 번에 조회하며, 누락되거나 현재 버전과 맞지 않는 상품만 Opt3의
기존 벌크 조인으로 한 번에 보완한다.

Opt4a의 `product_recommendation_scoring_snapshots` 테이블과 migration은 이미 적용된
이력으로 유지한다. 다만 추천 요청 런타임과 benchmark 준비 경로에서는 Opt4a의 큰
JSON payload를 읽거나 새로 집계하지 않는다.

## 불변 조건

- 추천 점수 공식, 가중치, 후보 추출 방식과 후보 수를 바꾸지 않는다.
- API request/response, score breakdown, reason, 최종 순위를 바꾸지 않는다.
- 사용자 프로필, 스킨 테스트, 행동 개인화는 read model에 저장하지 않는다.
- 효능별 상세 feature, 위험 flag, 리뷰 segment는 기존 필터링된 벌크 조회를 사용한다.
- 최종 점수, 동적 가중치, 순위와 설명 문구는 요청 시 계산한다.

## 저장 범위

read model은 다음 상품 핵심 입력만 저장한다.

- 상위 성분 코드와 효능 코드
- 기능성 상태, claim, confidence, basis
- 피부 태그와 피부 타입 적합도
- 7일 인기 신호
- 현재 버전 리뷰 품질 요약
- 원본 feature 버전, 최신성 여부, read model 버전과 계산 시각

## 조회 경로

`RECOMMENDATION_SCORING_READ_PATH`는 다음 두 값만 허용한다.

- `legacy_bulk`: Opt3 벌크 조인을 사용한다. 기본값이며 즉시 rollback 경로다.
- `compact_v2`: compact read model을 먼저 조회하고 상품 단위로 벌크 fallback한다.

compact 행이 없거나 read model/product feature/review 버전이 맞지 않거나 필수 필드가
불완전하면 해당 상품만 fallback 대상이 된다. 여러 상품이 fallback되어도 Opt3 loader는
한 번만 호출하며 상품별 N+1 조회를 만들지 않는다.

## 집계 명령

최초 적용 시 migration, 기존 상품 feature, compact read model 순서로 실행한다.

```bash
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --full --batch-size 500
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_read_models --full --batch-size 500
```

일부 상품만 다시 집계할 수 있다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --product-id 101 --product-id 205 --batch-size 100
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_read_models --product-id 101 --product-id 205 --batch-size 100
```

DB에 반영하지 않고 결과만 확인하려면 `--dry-run`을 사용한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_scoring_read_models --full --batch-size 500 --dry-run
```

자동 scheduler는 이 단계에 포함하지 않는다. 상품 feature가 변경된 뒤에는 운영 배치나
수동 명령으로 read model을 갱신한다.

## Benchmark 적용

서버 로컬 `config.benchmark.env`에서 실험 경로를 명시한다.

```bash
BENCHMARK_RECOMMENDATION_SCORING_READ_PATH="compact_v2"
```

그 뒤 기존 명령으로 dataset을 준비하고 검증한다. `prepare`는 compact read model을
집계하며, `verify`는 상품 수, read model 버전, 상품 feature 최신성과 리뷰 버전을
검증한다.

```bash
BENCHMARK_CONFIG_FILE=/home/ubuntu/mwobareullae-benchmark/config.benchmark.env \
./scripts/perf/benchmarkctl prepare 80000

BENCHMARK_CONFIG_FILE=/home/ubuntu/mwobareullae-benchmark/config.benchmark.env \
./scripts/perf/benchmarkctl verify 80000
```

Opt3로 되돌릴 때는 값을 `legacy_bulk`로 바꾸고 backend만 다시 활성화한다. DB schema와
집계 데이터는 그대로 두므로 rollback에 migration downgrade가 필요하지 않다.

## 관측 지표

- `scoring_read_path`: 실제 사용한 조회 경로
- `scoring_compact_read_model_load_ms`: compact 조회와 변환 전체 시간
- `scoring_compact_read_model_query_ms`: compact SQL 실행 및 fetch 시간
- `scoring_compact_read_model_build_ms`: 행 검증 및 scoring bundle 변환 시간
- `scoring_compact_read_model_hit_count`: compact 입력을 사용한 후보 수
- `scoring_compact_read_model_miss_count`: compact 행이 없었던 후보 수
- `scoring_compact_read_model_stale_count`: 버전 또는 필드 검증에 실패한 후보 수
- `scoring_compact_read_model_fallback_ms`: 누락·구버전 후보의 Opt3 벌크 조회 시간

성능 개선 여부는 실제 서버에서 동일 dataset, 사용자 유형, VUS, query set과 반복 횟수로
측정한 뒤 별도 결과 기록에 남긴다. 구현만으로 목표 수치를 달성했다고 간주하지 않는다.
