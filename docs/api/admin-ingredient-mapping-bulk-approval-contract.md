# 관리자 KCIA 성분 별칭 일괄 승인 API 계약

## 범위

이 API는 `KCIA 표준화명칭목록 2026-06-30` 출처의 high-confidence 별칭과 KCIA 근거 canonical이 정확히 일치하는 pending 성분만 승인한다. 기존 `product_ingredients`를 변경하지 않으며, 관리자 판정과 append-only 결정 이력만 저장한다.

## 미리보기

```text
GET /api/admin/ingredient-mappings/bulk-approve/preview
```

- 관리자 인증이 필요하다.
- 서버가 다음 조건을 모두 다시 계산해 최대 100개를 반환한다.
  - `ALIAS_EXACT_MATCH`
  - alias `confidence=high`
  - alias `source=KCIA 표준화명칭목록 2026-06-30`
  - 활성 canonical의 `source_url`에 KCIA 근거 존재
  - canonical 정확 일치 충돌 없음
- 프론트는 이 목록을 임의로 만들거나 KCIA 여부를 판정하지 않는다.

## 일괄 승인

```text
POST /api/admin/ingredient-mappings/bulk-approve
```

```json
{
  "confirmed_count": 2,
  "items": [
    {
      "pending_code": "ing_pending_example",
      "normalized_source_name": "example",
      "target_ingredient_code": "ing_example"
    }
  ]
}
```

- 1~100개만 허용한다.
- `confirmed_count`와 선택 항목 수가 다르면 `400 BULK_APPROVAL_CONFIRMATION_MISMATCH`다.
- 같은 `(pending_code, normalized_source_name)`를 중복 전송하면 `400 BULK_APPROVAL_DUPLICATE_ITEM`다.
- 저장 직전에 각 항목을 미리보기와 동일한 서버 조건으로 다시 검증한다.
- 하나라도 재검증·상태 전이·target 조건을 통과하지 못하면 `409 BULK_APPROVAL_ITEM_INELIGIBLE` 또는 기존 단건 오류를 반환하고, 전체 트랜잭션을 rollback한다. 부분 성공 응답은 만들지 않는다.
- 성공 시 각 항목의 기존 `APPROVED/MAPPED` 이력과 함께 공통 `batch_reference`를 event metadata에 남긴다.

```json
{
  "batch_reference": "BULK_KCIA_ALIAS_EXACT:uuid",
  "approved_count": 2,
  "items": []
}
```

## 제외 범위

- `INCI/CosIng`, 내부 관찰값, 날짜 없는 일반 출처처럼 KCIA 기준이 확정되지 않은 별칭은 미리보기에 포함하지 않는다.
- 기존 상품 성분 연결을 실제 canonical로 교체하는 M2-B 적용은 이 API의 범위가 아니다.
