# 뭐바를래 근거 데이터 런타임 계약 (초안)

> 작성일: 2026-07-11
> 상태: 데이터 매핑 원칙과 PR A 상태 구조 승인 완료. accepted-only 점수 게이트와 API 변경은 후속 PR 전까지 적용하지 않는다.
> 정책 정본: `docs/scoring/evidence-policy.md`
> 코드 확인 기준: `origin/dev` (`ffe69e1`)

## 1. 목적

논문을 보존하고 검수하는 정책이 실제 추천 점수와 상품 화면에서 같은 의미로 동작하도록 최소 계약을 정한다.

핵심 원칙은 다음 다섯 가지다.

1. 수집한 논문과 판정 이력은 삭제하지 않고 보존한다.
2. 사람 검수를 통과한 `accepted` 근거만 점수 계산에 사용할 수 있다.
3. `candidate_unverified`와 `rejected` 근거는 점수와 고객 화면에서 제외한다.
4. 음성·무효·반대·상충 결과도 보존하되, 합의되지 않은 감점식을 임의로 적용하지 않는다.
5. 고객 화면에는 성분 × 효능축별 대표 근거를 최대 3편만 보여주며 논문 수를 우수성으로 표현하지 않는다.

## 2. 현재 코드에서 확인된 사실

### 2.1 맞는 부분

- 추천 점수는 논문 행을 모두 합산하지 않는다. 현재는 성분 × 효능축마다 `evidence_score × source_authority_score`가 가장 높은 한 행을 사용한다.
- 추천 결과의 `score_evidence` 최대 3개는 대표 논문 3편이 아니라 점수 기여가 큰 성분 × 효능 설명 3개다.
- `ingredient_effect_score`와 `ingredient_evidence_score`는 별도 항목으로 계산한다.

### 2.2 PR A 적용 후 남은 차이

- `ingredient_evidence`와 CSV에 검수 상태·결과 방향·점수 사용 등급·대표 여부·활성 여부·검수 이력을 저장한다.
- 72행 백필은 `accepted 4 / candidate_unverified 62 / rejected 6`이다. 우선 검수 19행에는 검수자와 시각을 기록했고, 나머지 53행은 미검수 후보 상태다.
- PMID가 있는 행은 45개, PMID/DOI가 모두 없는 행은 27개이며, 이 중 18개는 `source_type=unknown`인 일반 검토 자료다. 식별자가 없는 행은 안정적인 legacy key를 사용하되 자동 승인하지 않는다.
- seed는 CSV에서 사라진 기존 DB 행을 삭제하지 않고 `is_current=false`로 전환한다.
- 상태 구조는 저장되지만 PR A에서는 점수 쿼리가 아직 상태를 필터링하지 않는다. 따라서 accepted-only 게이트를 켜기 전까지 기존 점수 동작은 유지된다.
- 음성·무효·상충은 상태와 검수 메모로 보존한다. 상충 종합식과 자동 감점은 아직 없다.
- 홈 추천은 `source_authority_score`를 적용하지 않고 `evidence_score` 최댓값만 사용해 일반 추천 점수와 기준이 다르다.
- 상품 상세 API는 연결된 근거를 전부 반환하고 대표 최대 3편을 구분하지 않는다.
- 프론트는 근거 행 수와 출처 수를 신뢰도·비교 강도에 사용한다. 논문이 많은 상품이 더 좋아 보일 수 있다.
- 화면의 `관련 성분 N개`는 고유 성분 수가 아니라 근거 행 수라서 같은 성분의 논문이 여러 편이면 부풀 수 있다.

### 2.3 세민 데이터 확인 결과 (2026-07-11)

- 최신 `origin/dev`의 상품 성분 정본은 `data/product_ingredients/product_ingredients_000~004.csv` 5개 파일이다.
- 전체 행은 2,058,682개이며 `product_id`, `ingredient_id`, `ingredient_name`, `display_order`, 함량 관련 컬럼을 포함한다.
- 넓은 원료명은 넓은 canonical 성분으로 유지하고, 논문이 특정 단일 성분을 연구했다면 상품 원문에 그 성분명이 명확히 적힌 행만 별도 canonical 성분과 근거에 연결한다.
- `contains` 검색은 긴 원문·설명문·붙어 있는 성분명까지 포함하므로 영향 파악과 alias 후보 검수에만 사용한다. 자동 remap은 strict exact 기준으로 시작한다.
- strict exact는 `ingredient_name`을 앞뒤 공백 제거·Unicode 정규화·대소문자 통일한 뒤, 승인된 한글/영문 alias 전체와 완전 일치하는 경우다. 부분 문자열 검색은 포함하지 않는다.

| 특정 성분 | strict exact | 변형 포함 | 초기 처리 |
|---|---:|---:|---|
| 글라브리딘 / Glabridin | 10 | 10 | exact 행만 별도 성분 연결 |
| 아시아티코사이드 / Asiaticoside | 1,594 | 1,611 | exact 1,594행 우선, 17행은 alias 검수 |
| 징크설페이트 / Zinc Sulfate | 154 | 158 | exact 154행 우선, 4행은 원문 검수 |
| 글루코노락톤 / Gluconolactone | 819 | 852 | exact 819행 우선, 33행은 원문 검수 |
| 락토바이오닉애씨드 / Lactobionic Acid | 78 | 79 | exact 78행 우선, 1행은 원문 검수 |
| `retinyl ester` 문자 그대로 | 0 | 해당 없음 | 묶음 ID를 만들지 않고 실제 화합물명별 검토 |

`retinyl palmitate`, `retinyl acetate`, `retinyl propionate`, `retinyl linoleate`, `retinyl retinoate` 등은 서로 다른 표기와 근거 범위를 가지므로 자동으로 하나의 `retinyl ester` 근거에 합치지 않는다.

## 3. 최소 데이터 계약

기존 `ingredient_evidence`는 검수 완료 후 런타임에 연결할 근거 테이블로 유지한다.
자동 수집된 미검수 논문은 별도 `evidence_discovery_candidates`에 저장하고,
승인 트랜잭션에서만 `ingredient_evidence`로 승격한다.

| 필드 | 값/형식 | 의미 |
|---|---|---|
| `canonical_evidence_key` | 문자열 | PMID 우선, 없으면 정규화 DOI, 그마저 없으면 검수자가 부여한 키 |
| `review_status` | `candidate_unverified` / `accepted` / `rejected` | 사람 검수 상태 |
| `result_direction` | `positive` / `negative` / `null` / `unclear` | 해당 성분 × 효능 결과 방향 |
| `score_use_level` | `primary` / `supporting` / `reference_only` | 정책 문서의 주점수 / 보조점수 / 참고만에 대응하는 점수 사용 등급 |
| `is_representative` | boolean | 고객·검수 화면 대표 노출 여부 |
| `representative_rank` | `1` / `2` / `3` / null | 성분 × 효능축 내부 대표 순서 |
| `is_current` | boolean | 현재 데이터 계약에서 활성인 행인지 여부 |
| `review_note` | text/null | 제외·보류·상충·전문 미확보 등 판정 근거 |
| `reviewed_by` | 문자열/null | 검수자 식별자 |
| `reviewed_at` | datetime/null | 마지막 검수 시각 |

필수 제약은 다음과 같다.

- 동일 `canonical_evidence_key + ingredient_id + effect_id` 조합은 한 행만 활성화한다.
- 대표 근거는 `accepted + is_current`인 행만 지정할 수 있다.
- 대표 순위는 성분 × 효능축마다 1~3을 중복 없이 사용한다.
- `rejected` 행도 삭제하지 않는다. `is_current=false` 또는 제외 사유로 런타임 사용만 막는다.
- 한 논문을 여러 성분·효능에 연결할 수 있지만, 각 연결은 별도 검수 판정을 가진다.
- 감초추출물·병풀추출물·PHA·retinol처럼 범위가 넓은 원료와 glabridin·asiaticoside·gluconolactone·개별 retinyl 화합물 같은 특정 성분을 자동으로 같은 근거 범위로 취급하지 않는다.
- 초기 canonical remap은 `ingredient_name` strict exact 행만 대상으로 한다. contains 변형은 alias 승인 전까지 기존 상태 또는 pending으로 유지한다.

### 3.1 자동 수집 후보 보관함

- 후보 자연키는 `(ingredient_id, effect_id, paper_key)`다.
- 동일 후보가 다음 주 검색에 다시 나오면 새 행을 만들지 않고 최근 발견 시각만 갱신한다.
- 후보 테이블은 점수 계산·고객 API·대표 근거 조회 대상이 아니다.
- 기각 후보도 삭제하지 않고 판정 이력을 보존한다.
- 승인 시 검수자가 결과 방향, 근거 등급, 점수 사용 등급, 근거 점수, 대표 여부를 입력한다.
- 승인과 `ingredient_evidence` 생성은 한 DB 트랜잭션으로 처리한다.
- 음성·무효·불명확 후보는 종합 감점식 확정 전까지 `reference_only + 0점`으로만 승인할 수 있다.
- 기존 CSV 근거는 baseline seed가 관리하고, 자동 수집 이후 후보·판정·승인 근거는 운영 DB가 관리한다.
- seed 정리 로직은 후보에서 승격된 근거를 CSV 미존재 이유로 비활성화하지 않는다.

## 4. 점수 동작 계약

### 4.1 점수 사용 게이트

현재 양의 근거 점수 후보는 다음 조건을 모두 만족해야 한다.

```text
review_status == accepted
is_current == true
result_direction == positive
score_use_level in {primary, supporting}
```

- `candidate_unverified`, `rejected`, `reference_only`는 양의 점수에 사용하지 않는다.
- `negative`, `null`, `unclear`는 보존하고 상충 표시와 사람 검수에 사용한다.
- 음성·무효·상충 근거의 수치 감점은 `evidence-policy.md`의 종합식이 팀에서 확정될 때까지 적용하지 않는다.
- 종합식 확정 전 임시 계산은 **가장 높은 accepted 양의 유효점수 한 건**을 사용하는 현재 방식을 유지한다. 논문 수는 합산하지 않는다.

### 4.2 서비스 간 동일성

- 일반 추천, 홈 섹션, 상품 상세는 같은 `score_eligible` 판정과 같은 유효점수 계산 함수를 사용한다.
- 홈 섹션도 `evidence_score × source_authority_score` 기준을 적용한다.
- 추천 결과의 상위 성분 기여 3개와 대표 논문 최대 3편은 서로 다른 개념과 필드로 유지한다.

## 5. seed와 전환 순서

기존 72행을 일괄 `accepted` 또는 일괄 `candidate_unverified`로 바꾸지 않는다. 점수 급변과 미검수 근거 승인을 모두 피하기 위해 두 단계로 전환한다.

### 5.1 1단계: 상태 구조만 추가

- migration과 CSV 계약에 상태 필드를 추가한다.
- 현재 점수 동작은 유지한 채 72행의 상태를 워크북 검수 결과와 동기화한다.
- seed는 물리 삭제 대신 입력에서 사라진 행을 `is_current=false`로 만든다.
- PMID/DOI 중복, 일반 서술, 전문 미확보, 성분 형태 불일치 리포트를 만든다.
- canonical 성분 remap 입력은 strict exact 행과 contains 변형 후보를 분리한 manifest로 만든다.
- strict exact 행만 먼저 remap하고 변형 후보는 원문·alias 검수 전 자동 승격하지 않는다.

### 5.2 2단계: accepted-only 게이트 적용

- 검수 상태 채우기와 회귀 테스트가 끝난 뒤 점수 쿼리에 accepted-only 조건을 적용한다.
- 변경 전후 상품별 점수와 순위 차이를 리포트한다.
- 검색 문서가 근거 상태나 canonical 성분 변경의 영향을 받으면 rebuild하고 임베딩을 갱신한다.
- 점수 급변이 확인되면 데이터를 검수하지 않은 채 게이트를 완화하지 않고 원인을 수정한다.

## 6. API와 화면 계약

### 6.1 상품 상세 API

상품 상세의 근거 응답은 논문별 반복 행이 아니라 성분 × 효능축 단위로 구성한다.

```text
ingredient_id
ingredient_name
effect_id
effect_name
evidence_level
has_conflict
representative_sources[]  # 최대 3편
```

- `representative_sources`에는 `accepted + is_current + is_representative`만 반환한다.
- 후보·기각 근거와 내부 검수 메모는 고객 API에 반환하지 않는다.
- 전체 보존 풀은 관리자 검수 API에서만 조회한다.

### 6.2 프론트

- `content_confidence`를 근거 행 개수로 계산하지 않는다.
- 상품 비교의 근거 강도에 `evidence.length`나 `sources.length`를 더하지 않는다.
- `관련 성분 N개`는 고유 성분 ID를 세거나 개수 표기를 제거한다.
- 논문 개수 자체를 우수성 배지나 추천 이유로 사용하지 않는다.
- 대표 근거가 1편이면 1편만 표시하고 3편을 억지로 채우지 않는다.
- 음성·상충 결과를 고객에게 보여줄지는 PM/UX 문구 확인 후 결정한다.

## 7. 필수 테스트

1. `candidate_unverified` 행만 추가해도 추천 점수와 순위가 변하지 않는다.
2. 같은 성분 × 효능에 유사 논문을 여러 행 추가해도 논문 수만으로 점수가 증가하지 않는다.
3. `accepted` 양의 근거 중 유효점수가 가장 높은 행만 임시 집계에 사용된다.
4. `negative`·`null`·`unclear`는 보존되지만 합의 전 자동 감점되지 않는다.
5. CSV에서 빠진 행은 DB에 남되 `is_current=false`가 되어 점수·고객 화면에서 제외된다.
6. 대표 순위는 성분 × 효능축별 최대 3개이며 후보·기각 행은 대표가 될 수 없다.
7. 홈과 일반 추천이 같은 근거 행에 대해 같은 유효점수를 계산한다.
8. 상품 상세는 대표 근거만 반환하고, 화면의 성분 수가 논문 행 수로 부풀지 않는다.
9. canonical 성분 remap 후 이전 연결과 새 연결이 동시에 점수에 사용되지 않는다.
10. 추천 결과의 성분 기여 상위 3개가 대표 논문 3편으로 오해되지 않도록 API 계약을 검증한다.

## 8. 역할별 구현 범위

- 규태 AI 추천/검색/에이전트: 72행의 근거 판정 초안·대표 후보·제외 사유 정리, accepted-only 점수 게이트, 유효점수 공통 함수, 상충 처리 정책, 점수·순위 회귀 리포트와 테스트.
- 세민 데이터: 성분·논문 식별자와 CSV 형식 검증, strict exact/변형 후보 manifest 확인, canonical 성분 분리 결과와 CSV 계약 동기화. 논문의 과학적 승인·기각 판정은 담당하지 않는다. exact-only 연결 원칙은 확인 완료.
- 원우 백엔드: migration, seed 동기화/비활성화, 고객·관리자 API 계약, rollback 방식.
- 지현 프론트엔드: 논문 수 기반 신뢰도 제거, 대표 근거 최대 3편 표시, 고유 성분 수 계산.
- 현옥 PM/UX: 대표 근거와 상충 결과의 고객 문구, 관리자 검수 흐름 확인.
- 지운 인프라/로그: canonical remap 이후 검색 문서 rebuild·임베딩 갱신 및 작업 로그 확인.

## 9. 구현 순서

1. PR #431의 근거 보존 정책은 `dev` 반영 완료다. 이 계약의 상태 구조·seed 전환·점수 게이트를 팀이 확인한다.
2. 데이터·백엔드가 상태 컬럼과 seed 전환 방식을 확정한다.
3. **PR A:** migration + 데이터 계약 + seed + 상태 백필(점수 동작 유지).
4. AI 추천 담당이 72행 검수 상태와 대표 후보를 먼저 작성하고, 사람 승인과 데이터 식별자 검증을 거쳐 회귀 기준을 저장한다.
5. **PR B:** accepted-only 점수 게이트 + 홈 계산 통일 + 백엔드 테스트.
6. **PR C:** 상품 상세 API 대표 근거 계약 + 프론트 개수 편향 제거.
7. canonical 성분 분리가 끝나면 cleanup migration, 검색 rebuild, 임베딩 갱신을 별도 실행한다.

## 10. 결정 기록

### 확인 완료: canonical 성분 근거 연결 원칙

- 넓은 원료명은 기존 broad 성분으로 유지한다.
- 특정 단일 성분 논문은 strict exact 상품 행에만 연결한다.
- contains 변형은 alias 검수 전 자동 remap하지 않는다.
- `retinyl ester` 묶음으로 자동 합치지 않고 실제 retinyl 화합물별로 검토한다.
- 남은 결정은 기존 broad 연결을 어떻게 비활성화하고 rollback할지에 대한 백엔드 구현 방식이다.

### 결정 1: 검수 상태의 정본 위치 — 확정

- 확정안: CSV와 DB를 런타임 정본으로 두고, 워크북은 검수 입력·감사 자료로 사용한다.
- 대안: 워크북만 정본으로 두고 seed 전에 변환한다.
- 왜 중요한지: 상태가 두 곳에서 다르면 후보 논문이 점수에 들어갈 수 있다.
- 선택 후 영향: 세민 데이터 계약과 원우 seed 구현이 정해진다.

### 결정 2: 기존 72행의 전환 — 확정

- 확정안: 상태 구조를 먼저 추가하고 행별 검수 후 accepted-only 게이트를 별도 PR로 켠다.
- 대안: 기존 행을 일괄 승인해 현재 점수를 즉시 유지한다.
- 왜 중요한지: 일괄 승인은 미검수 근거를 승인하고, 일괄 후보화는 추천 점수를 급락시킨다.
- 선택 후 영향: migration 기본값, 백필 파일, 배포 순서가 정해진다.

### 결정 3: 음성·무효·상충의 수치 처리 — 확정

- 확정안: 현재는 보존·표시·검수만 하고 자동 감점하지 않는다.
- 대안: 임시 감점 계수를 도입한다.
- 왜 중요한지: 감점 계수는 추천 scoring 기준 변경이므로 팀 승인 없이 넣을 수 없다.
- 선택 후 영향: 이번 구현 범위와 후속 scoring 실험 범위가 분리된다.

### 결정 4: canonical 성분 remap의 cleanup·rollback 방식 — 후속 구현 전 확인

- 추천안: cleanup migration으로 이전 broad 연결을 비활성화한 뒤 새 exact 연결을 만들고 검색 문서를 재생성한다.
- 대안: 기존 연결을 유지하고 새 연결만 추가한다.
- 왜 중요한지: 기존과 신규 연결이 함께 남으면 같은 상품이 이중 점수를 받을 수 있다.
- 선택 후 영향: 원우 migration·rollback과 세민 remap 파일 형식이 정해진다.
