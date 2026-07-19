# 관리자 성분 매핑 최종 분류 API 계약

## 목적

관리자는 pending 성분 원문 그룹을 정식 성분에 연결하거나, 연결하지 않는 최종 사유를 남긴다.
이 API는 **판정 기록만** 저장하며 기존 `product_ingredients`를 변경하지 않는다.

## 최종 상태

| 최종 분류 | review 상태 | target canonical |
| --- | --- | --- |
| `MAPPED` | `APPROVED` | 필수 |
| `NON_INGREDIENT` | `REJECTED` | 없음 |
| `COMPOUND_MATERIAL` | `REJECTED` | 없음 |
| `SOURCE_ERROR` | `REJECTED` | 없음 |
| `UNRESOLVABLE` | `REJECTED` | 없음 |

`PENDING`, `HELD`, `NEEDS_REVIEW`는 아직 최종 분류되지 않은 임시 상태다.

## 목록

`GET /api/admin/ingredient-mappings`

- `status`: `PENDING | HELD | NEEDS_REVIEW | APPROVED | REJECTED`
- `final_disposition`: 최종 분류 5개 중 하나
- `sort`: `CODE_ASC`(기본) | `CONNECTION_DESC`(연결 상품 수 내림차순)
- `candidate_type`: `CANONICAL_EXACT_MATCH` | `ALIAS_EXACT_MATCH` | `EXACT_MATCH_CONFLICT` | `NO_EXACT_MATCH`
- `q`, `limit`, `cursor`
- `CONNECTION_DESC`는 pending 원문 그룹이 연결된 상품 수만 기준으로 우선 검수 순서를 정한다. 기존 alias/canonical 정확 일치 후보 표시는 그대로 사용하며, 이 정렬은 자동 승인·최종 분류·기존 상품 성분 변경을 수행하지 않는다.
- `candidate_type`은 등록된 정식명·별칭의 **정확 일치 여부**를 읽기 전용 처리 후보로 나눈다. `EXACT_MATCH_CONFLICT`, `NO_EXACT_MATCH`는 자동 결론이 아니라 관리자 근거 검토 대상이다. 원문 오류·성분 아님·복합 원료를 자동으로 추정하지 않는다.
- 각 항목의 `candidate`에는 후보 유형과 판단 근거가 포함된다. `suggestion`은 정확 일치로 단일 canonical 후보가 있을 때만 제공한다.
- `cursor`는 `sort`, `candidate_type`까지 포함한 조회 범위와 함께 검증한다. 다른 정렬 또는 후보 필터로 재사용하면 `400 INVALID_CURSOR`다.
- 상태와 최종 분류 필터를 모두 생략하면 임시 상태(`PENDING`, `HELD`, `NEEDS_REVIEW`)만 반환한다.
- `cursor`는 `status`, `final_disposition`, `q`와 함께 묶인다. 다른 필터로 재사용하면 `400 INVALID_CURSOR`다.

응답의 `summary`에는 `needs_review_count`, `unclassified_count`가 추가된다. 각 `decision`과 변경 이력에는 `final_disposition`을 포함한다.

## 판정

### 정식 성분 연결

`POST /api/admin/ingredient-mappings/{pending_code}/approve`

```json
{
  "normalized_source_name": "sodiumhyaluronate",
  "target_ingredient_code": "ing_hyaluronic_acid",
  "decision_reason": "KCIA 정식명과 확인"
}
```

성공 시 `status=APPROVED`, `final_disposition=MAPPED`가 된다.

### 연결하지 않는 최종 분류

`POST /api/admin/ingredient-mappings/{pending_code}/reject`

```json
{
  "normalized_source_name": "sample raw name",
  "decision_reason": "원문이 성분 목록이 아니라 마케팅 문구입니다.",
  "final_disposition": "NON_INGREDIENT",
  "evidence_source_url": "https://example.com/source",
  "source_reference": "kcia_ingredients_2026-07.csv"
}
```

- `final_disposition`은 필수다.
- `NON_INGREDIENT`는 근거 필드가 선택이다.
- `COMPOUND_MATERIAL`, `SOURCE_ERROR`, `UNRESOLVABLE`은 `evidence_source_url` 또는 `source_reference` 중 하나가 필수다. 없으면 `400 FINAL_DISPOSITION_EVIDENCE_REQUIRED`다.
- 이전의 단순 반려 요청은 더 이상 유효하지 않다.

### 보류·재검토

- `POST .../hold`: `HELD`, 최종 분류 없음
- `POST .../reopen`: 기존 `APPROVED` 또는 `REJECTED`를 `NEEDS_REVIEW`로 되돌리고 최종 분류를 지운다.

## 범위 밖

승인 결과를 기존 상품 성분 행에 실제 적용하는 대량 작업(M2-B)은 이 API 범위가 아니다.
