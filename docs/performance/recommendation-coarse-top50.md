# 추천 Coarse Top50 재랭킹

`coarse_top50_v1`은 기존 후보 추출 결과 약 500개를 경량 피처로 먼저 선별하고,
상위 50개만 현재 정확 점수식으로 재계산한다. 최종 점수식, 가중치, API 계약과 후보
추출 방식은 변경하지 않는다.

## 실행 흐름

```text
기존 후보 약 500개
-> 요청에 필요한 coarse 숫자 컬럼만 1회 조회
-> coarse score 계산 및 상위 50개 선정
-> 50개만 기존 legacy_bulk 상세 조회
-> 기능성을 포함한 현재 정확 점수와 설명을 1회 계산
-> 정확 점수로 재정렬한 최대 50개 저장
```

근사 단계는 성분 효능, 성분 근거, 피부 프로필, 기존 검색 매칭, 가격, 계산 가능한
스킨 테스트 축과 행동 성향을 사용한다. 행동 성향은 effect/category/brand/price만
사용하며 ingredient affinity는 제외한다. 근사 단계에서 제외한 축은 0점으로 넣지 않고
사용한 축의 가중치 합으로 정규화한다.

기능성, 농도, 민감 위험 감점, 리뷰 상세, 인기, 상세 성분과 추천 문구는 근사 테이블에
저장하지 않는다. 이 정보는 상위 50개의 정확 단계에서만 조회하고 현재 식 그대로
반영한다. 내부 coarse score는 API 점수나 score breakdown으로 노출하지 않는다.

## Read Model

`product_recommendation_coarse_features`는 상품별 다음 값만 평탄화한다.

- 6개 효능별 성분 효능·근거 점수: `0..10000` SMALLINT
- 피부 타입별 fit과 sensitive fit
- 숫자형 skin profile confidence
- source 최신 여부, feature version, source/computed 시각

`product_id`가 PK/FK이며 별도 보조 인덱스, JSONB, 배열과 긴 문자열은 두지 않는다.
브랜드, 카테고리와 가격은 기존 `ProductCandidate` 값을 사용한다.

## Fallback

- 누락·stale 후보가 전체의 5% 이하면 해당 ID만 기존 피처 원본에서 벌크 보완한다.
- 5%를 초과하거나 부분 보완이 불완전하면 전체 후보를 `legacy_bulk`로 계산한다.
- 기존 `legacy_bulk`, `compact_v2`와 관련 테이블은 rollback을 위해 유지한다.

## 적용 명령

최초 적용과 전체 갱신은 migration, 기존 추천 피처, coarse 피처 순서로 실행한다.

```bash
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --full --batch-size 500
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_coarse_features --full --batch-size 500
```

일부 상품 또는 dry-run도 지원한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_coarse_features --product-id 101 --product-id 205 --batch-size 100
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_coarse_features --full --batch-size 500 --dry-run
```

활성화와 즉시 rollback 값은 다음과 같다.

```bash
RECOMMENDATION_SCORING_READ_PATH=coarse_top50_v1
RECOMMENDATION_SCORING_READ_PATH=legacy_bulk
```

benchmark에서는 서버 로컬 설정에 다음 값을 넣고 기존 `prepare`, `verify`, `activate`
순서를 사용한다. `prepare`와 `verify`는 이 경로일 때 coarse 피처를 자동 집계·검증한다.

```bash
BENCHMARK_RECOMMENDATION_SCORING_READ_PATH="coarse_top50_v1"
```

## 품질 비교

고정 10개 질의로 동일 후보군의 전체 `legacy_bulk` 결과와 `coarse_top50_v1` 결과를
비교한다. 이 명령은 외부 LLM을 호출하지 않고 추천 결과를 DB에 저장하지 않는다.

```bash
docker compose exec -T backend python -m app.cli.evaluate_recommendation_coarse_top50_quality --candidate-pool-limit 500 --format markdown
```

출력에는 기존 top1 포함 여부, 기존 exact top10 recall@50, 선택된 상품의 정확 점수·
score breakdown parity와 fallback 여부가 포함된다. `--fail-on-quality-loss`를 사용하면
오류, fallback, exact parity 손실 또는 top1 손실 시 종료 코드 1을 반환한다. recall
수치는 임의 기준으로 숨기지 않고 케이스별·평균·최솟값을 그대로 기록한다.

## 계측

- `coarse_feature_query_ms`, `coarse_feature_build_ms`, `coarse_feature_row_count`
- `coarse_feature_hit_count`, `coarse_feature_miss_count`, `coarse_feature_stale_count`
- `coarse_score_loop_ms`, `coarse_shortlist_size`
- `exact_prefetch_ms`, `exact_score_loop_ms`, `exact_functional_axis_ms`
- `scoring_read_path`, `scoring_fallback`, `scoring_fallback_reason`

성능 개선과 8만 상품 품질 수치는 실제 서버에서 동일 조건으로 직접 측정한 뒤 기록한다.
구현 또는 로컬 테스트만으로 목표 수치를 달성했다고 간주하지 않는다.
