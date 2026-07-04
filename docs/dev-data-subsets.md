# 개발용 seed subset 운영

## 목적

상품 데이터가 2만 건을 넘고 상품-성분 매핑이 커지면, 모든 기능 개발을 full 데이터로만 진행하기 어렵다.

개발 순서는 아래처럼 둔다.

1. `dev-small`: 추천 가능 상품 1,000개로 API/화면/구매 흐름을 먼저 안정화한다.
2. `dev-recommendable`: `is_recommendable=true` 전체 상품으로 추천 후보 품질을 확인한다.
3. `full`: 전체 상품/성분 데이터로 성능 병목을 측정하고 최적화한다.

## 생성 방법

기본 1,000개 개발용 subset:

```bash
python data/scripts/build_seed_subset.py --output-dir data/dev-small --force
```

`is_recommendable=true` 전체 subset:

```bash
python data/scripts/build_seed_subset.py --output-dir data/dev-recommendable --no-limit --force
```

비추천 상품까지 포함한 임의 크기 subset:

```bash
python data/scripts/build_seed_subset.py --output-dir data/generated-subsets/all-2000 --include-non-recommendable --limit 2000 --force
```

생성물은 로컬 개발 산출물이므로 Git에 올리지 않는다.

## 포함 기준

`products.csv`에서 선택된 `product_id`를 기준으로 아래 파일을 함께 필터링한다.

- `product_prices.csv`
- `product_inventory.csv`
- `product_skin_profiles.csv`
- `product_image_assets.csv`
- `product_ingredients.csv`
- `product_market_signals.csv`
- `vector_docs.csv`

그리고 선택된 상품이 사용하는 `ingredient_id`를 기준으로 아래 파일도 함께 줄인다.

- `ingredients.csv`
- `ingredient_aliases.csv`
- `ingredient_effect.csv`
- `ingredient_effect_ranges.csv`
- `ingredient_evidence.csv`
- `risk_flags.csv`

`tags.json`, `concern_to_effect.json`은 그대로 복사한다.

## seed 실행

Docker 기준:

```bash
docker compose exec backend python -m app.cli.seed_data --data-dir /data/dev-small
```

로컬 Python 기준:

```bash
cd apps/backend
python -m app.cli.seed_data --data-dir ../../data/dev-small
```

## small/full DB 분리 기준

스키마는 같고 데이터만 다르게 둔다.

추천안:

- `mwobareullae_small`: `data/dev-small`
- `mwobareullae_full`: `data`

같은 Postgres 서버 안에서 DB 이름만 다르게 두면 포트를 늘리지 않아도 된다.
포트를 나누고 싶을 때만 Postgres 컨테이너를 하나 더 띄운다.

예시:

```bash
docker compose exec postgres createdb -U mwobareullae mwobareullae_small
docker compose exec postgres createdb -U mwobareullae mwobareullae_full
```

small DB에 붙일 때:

```text
DATABASE_URL=postgresql+psycopg://mwobareullae:change-me@postgres:5432/mwobareullae_small
DATA_DIR=/data/dev-small
```

full DB에 붙일 때:

```text
DATABASE_URL=postgresql+psycopg://mwobareullae:change-me@postgres:5432/mwobareullae_full
DATA_DIR=/data
```

## 주의

- `is_recommendable`은 현재 CSV subset 생성 기준이다.
- 현 시점 백엔드 DB 모델에는 `is_recommendable` 컬럼이 없다.
- 추천 후보에서 `is_recommendable=true`만 쓰도록 DB 레벨까지 강제할지는 별도 결정이 필요하다.
- 10만 데이터 성능 최적화는 small DB에서 기능이 안정된 뒤 full DB 수치로 판단한다.
