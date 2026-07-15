# 추천 사전 계산 특징 배치

> 동일 조건 재측정 수치와 scoring 하위 단계 변화는 [Opt2 측정 결과](results/recommendation/details/opt2-precomputed-features/README.md)에서 확인한다.

추천 점수 공식과 API 응답은 유지하면서 반복 계산되는 상품 특징과 사용자 행동 선호를 DB에 미리 저장한다. 최종 `total_score`나 순위는 저장하지 않으며 검색어, 요청 효능 가중치, 수동 피부 프로필, 스킨 테스트, 회피 성분, 가격 조건은 요청 시점에 계산한다.

## 저장 테이블

- `product_recommendation_features`: 상품별 상위 성분·효능 코드 8개
- `product_effect_recommendation_features`: 상품·효능별 성분 효능, 근거, 농도 특징
- `user_preference_profiles`: 사용자·행동 출처별 선호 점수와 정규화 값

추천 요청은 버전과 상품 갱신 시각이 유효한 행을 먼저 사용한다. 행이 없거나 버전이 다르면 해당 상품 또는 사용자만 기존 온라인 계산으로 돌아간다.

## 최초 적용

서버의 저장소 루트에서 아래 순서로 실행한다.

```bash
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --full --batch-size 500
docker compose exec -T backend python -m app.cli.rollup_user_preference_profiles --full --batch-size 100
```

상품 특징을 먼저 집계하고 사용자 프로필을 집계한다. 각 명령은 chunked UPSERT 방식이며 같은 입력으로 다시 실행해도 행이 중복되지 않는다.

## 선택 재집계

상품 DB ID를 지정한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --product-id 101 --product-id 205 --batch-size 100
```

사용자 DB ID를 지정한다.

```bash
docker compose exec -T backend python -m app.cli.rollup_user_preference_profiles --user-id 11 --user-id 12 --batch-size 50
```

커밋하지 않고 실행 결과만 확인하려면 `--dry-run`을 붙인다.

```bash
docker compose exec -T backend python -m app.cli.rollup_product_recommendation_features --full --batch-size 500 --dry-run
docker compose exec -T backend python -m app.cli.rollup_user_preference_profiles --full --batch-size 100 --dry-run
```

## DB 검증

운영 DB 클라이언트에서 다음 SQL로 행 수와 버전을 확인한다.

```sql
SELECT feature_version, count(*)
FROM product_recommendation_features
GROUP BY feature_version;

SELECT feature_version, count(*)
FROM product_effect_recommendation_features
GROUP BY feature_version;

SELECT profile_version, source, count(*)
FROM user_preference_profiles
GROUP BY profile_version, source
ORDER BY profile_version, source;

SELECT count(*) AS stale_product_features
FROM product_recommendation_features f
JOIN products p ON p.id = f.product_id
WHERE f.source_updated_at < p.updated_at;
```

CLI JSON 결과의 `product_count`, `product_feature_count`, `effect_feature_count`, `profile_count`, `stale_*_count`도 함께 확인한다.

## 재집계 시점

- 상품 seed/import 후 상품 특징 전체 집계
- 상품 성분, 효능, 근거, 농도 데이터 변경 후 해당 상품 또는 전체 집계
- 사용자 행동 데이터 반영이 필요할 때 사용자 프로필 집계
- 특징 계산 버전을 올린 배포 직후 전체 집계

현재 범위에는 cron, worker, queue, Redis 스케줄러를 포함하지 않는다. 인프라 자동화를 붙이기 전까지 위 CLI를 수동 실행하며, 스케줄 주기와 실행 플랫폼은 별도 운영 결정으로 확정한다.

## 인프라 인계

1. 배포 후 migration을 먼저 적용한다.
2. 상품 특징 전체 집계가 성공한 뒤 사용자 프로필 전체 집계를 실행한다.
3. DB 버전별 행 수와 stale 상품 수를 확인한다.
4. 추천 로그에서 `product_feature_*`, `effect_feature_*`, `user_profile_*`, `legacy_fallback_*` 지표를 확인한다.
5. 집계 실패 중에도 추천 API는 누락 범위만 기존 계산으로 fallback하므로 API를 중단하거나 응답 계약을 바꿀 필요가 없다.

