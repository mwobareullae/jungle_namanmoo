# 관리자 성분 매핑 CSV 일괄 적용 API 계약

- 확정일: 2026-07-23
- 범위: 운영 DB 미판정 그룹 export, dry-run, 판정 이력 저장, 실제 상품-성분 연결 이동
- 실행 주체: `ADMIN` 세션 사용자

## 처리 흐름

1. `GET /api/admin/ingredient-mappings/csv-export`로 **현재 운영 DB**의 미판정 그룹을 내려받는다.
2. 관리자가 target 컬럼과 근거를 작성한다.
3. `POST /api/admin/ingredient-mappings/csv-preview`로 1,000행 이하 배치를 dry-run한다.
4. 오류가 0건일 때만 preview digest와 확인 건수를 `POST /api/admin/ingredient-mappings/csv-apply`에 보낸다.
5. 프론트는 큰 파일을 1,000행 단위로 순차 처리하고 마지막 배치에서만 pending materialized view를 갱신한다.
6. 완료 후 Elasticsearch 상품 색인은 별도 운영 재색인을 실행한다.

기본 운영 흐름에서는 CSV를 Git에 저장하거나 로컬 seed CSV로 변환하지 않는다. export와 적용은 모두 요청 시점의 운영 DB를 기준으로 한다.
다만 대량 초기 정리처럼 재현성과 검수가 필요한 일회성 작업은 운영 export를 입력으로 생성한 완성 CSV와 생성·정규화 코드를 함께 커밋할 수 있다. 이 스냅샷은 seed가 아니며 관리자 화면에서 dry-run을 통과한 뒤에만 적용한다.
계속 미판정으로 남길 약 20건은 적용 파일에서 행을 제외하며 운영 DB에서는 그대로 유지한다.

### 2026-07-23 일회성 운영 스냅샷

- 입력: 2026-07-23 운영 DB 미판정 그룹 export 70,442건
- 생성기: `data/scripts/generate_production_ingredient_mapping_csv.py`
- 완성 파일: `data/reconciliation/ingredient_mapping_ready_20260723.csv`
- 완성 행: 70,422건 (`MAP_EXISTING` 6,861건, `CREATE_AND_MAP` 63,561건)
- 제외: 자동 판정 위험 점수가 높은 20건. 운영 DB에서는 계속 미판정으로 유지
- 적용: 관리자 화면에서 파일 선택 → 1,000행 단위 dry-run → 오류 0건 확인 → 적용
- 주의: export 이후 운영 연결 수가 달라지면 `CONNECTION_COUNT_CHANGED`로 차단되므로 파일을 임의 수정해 우회하지 않고 운영 export부터 다시 생성한다.

생성 예시:

```powershell
python data/scripts/generate_production_ingredient_mapping_csv.py `
  --pending-csv <운영-export.csv> `
  --output data/reconciliation/ingredient_mapping_ready_20260723.csv `
  --excluded-count 20 `
  --report <검수-report.json>
```

## CSV 컬럼

| 컬럼 | 필수 | 설명 |
| --- | --- | --- |
| `action` | O | `MAP_EXISTING` 또는 `CREATE_AND_MAP` |
| `pending_code` | O | export가 제공한 pending 성분 코드 |
| `raw_name` | 읽기용 | 대표 원문. 적용 요청에서는 사용하지 않음 |
| `normalized_source_name` | O | export 값을 수정하지 않고 사용 |
| `expected_connection_count` | O | export 시점 연결 수. 현재 값과 다르면 배치 차단 |
| `target_ingredient_code` | O | 기존 또는 신규 canonical 코드 |
| `target_name_ko` | 신규 시 O | `CREATE_AND_MAP` 신규 canonical 한글명 |
| `target_name_en` | 선택 | 신규 canonical 영문명 |
| `decision_reason` | 선택 | 비어 있으면 관리자 CSV 일괄 매핑 기본 사유 사용 |
| `source_reference` | 신규 시 O | 신규 canonical 생성 근거 또는 출처 식별자 |

`CREATE_AND_MAP`의 코드는 `ing_`로 시작하고 `ing_pending_`는 사용할 수 없다. 같은 신규 코드가 파일에서 서로 다른 이름으로 정의되거나 기존 코드의 이름과 충돌하면 적용하지 않는다.

## dry-run

`POST /api/admin/ingredient-mappings/csv-preview`

- 요청당 1~1,000행
- 운영 DB에서 source/target 존재, 활성 canonical 여부, 현재 연결 수, 기존 승인 충돌, 파일 내 중복을 재검증한다.
- 결과 상태는 `VALID`, `INVALID`, `ALREADY_APPLIED`다.
- `preview_digest`는 행 전체의 SHA-256 digest이며 apply 요청이 같은 행인지 확인한다.

## 실제 적용

`POST /api/admin/ingredient-mappings/csv-apply`

추가 요청 필드:

- `preview_digest`: 직전 dry-run digest
- `confirmed_count`: 요청 행 수와 정확히 같아야 함
- `refresh_pending_groups`: 마지막 배치에서만 `true`, 중간 배치는 `false`

서버는 apply 직전에 dry-run 검증을 다시 수행한다. 한 행이라도 잘못되면 해당 배치는 전부 rollback한다. 유효 행은 다음을 같은 DB 트랜잭션에서 처리한다.

- `ingredient_mapping_reviews` 승인 및 append-only 이벤트 생성
- 필요 시 근거가 있는 신규 canonical 생성
- 해당 `(pending_code, normalized_source_name)`의 `product_ingredients.ingredient_id`를 target으로 이동
- 한 상품에 target 연결이 이미 있으면 pending 쪽 중복 행 삭제

배치 간에는 독립 트랜잭션을 사용한다. 중간 실패 후 같은 파일을 다시 dry-run하면 완료된 행은 `ALREADY_APPLIED`로 표시되어 중복 저장되지 않는다.

## 후속 작업

- `refresh_pending_groups=true`이면 commit 후 `ingredient_mapping_pending_groups`를 갱신한다.
- 중간 배치 실패 뒤에는 `POST /api/admin/ingredient-mappings/csv-refresh`로 완료된 배치 기준의 pending 목록을 복구한다.
- 응답의 `search_reindex_required=true`이면 고객 상품 조회·검색 반영을 위해 배포 환경의 전체 Elasticsearch catalog 재색인을 실행한다.
- 재색인은 장시간 작업이므로 이 HTTP 요청 안에서 자동 실행하지 않는다.

## 주요 오류

| 코드 | 의미 |
| --- | --- |
| `CONNECTION_COUNT_CHANGED` | export 이후 해당 원문 그룹 연결 수 변경 |
| `DUPLICATE_MAPPING_GROUP` | 같은 source 그룹이 파일 안에 중복 |
| `APPROVED_TARGET_CONFLICT` | 이미 다른 canonical로 승인됨 |
| `SOURCE_REFERENCE_REQUIRED` | 신규 canonical 생성 근거 누락 |
| `CSV_MAPPING_PREVIEW_STALE` | dry-run과 apply 행 digest 불일치 |
| `CSV_MAPPING_BATCH_INVALID` | 재검증 결과 오류 행 존재 |
