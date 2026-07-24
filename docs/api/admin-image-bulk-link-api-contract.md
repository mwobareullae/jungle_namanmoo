# 관리자 이미지 대량 연결 API 계약

상태: 구현 완료 (2026-07-19)

## 범위

- 기존 상품의 `ProductImage` 슬롯에 이미 S3/CloudFront에 존재하는 상대 `storage_key`를 연결한다.
- 파일 업로드, CDN/S3 파일 실존 확인, 리사이즈본 확인은 이 API 범위 밖이다.
- 대상 상품은 `import_sku`가 있는 M3-B 대량등록 상품뿐이다.

## 요청

`POST /api/admin/products/images/bulk`

```json
{
  "rows": [
    {
      "import_sku": "IMPORT_001",
      "image_type": "thumbnail",
      "display_order": 0,
      "storage_key": "products/IMPORT_001/thumbnail.jpg"
    },
    {
      "import_sku": "IMPORT_001",
      "image_type": "detail",
      "display_order": 1,
      "storage_key": "products/IMPORT_001/detail_01.jpg"
    }
  ]
}
```

- 행 수는 1~1,000개다. 500/1,000/2,000행 메모리 DB 측정에서 검증·저장은 각각 3.8/7.6/14.3초였으며, 브라우저 응답 여유를 위해 1,000행을 상한으로 정했다.
- `import_sku`는 대문자 영문·숫자·`._-` 형식(1~64자)이다.
- `thumbnail`은 `display_order=0`만 허용하고, `detail`은 1 이상만 허용한다.
- `storage_key`는 필수 상대 경로다. 절대 URL과 `..`는 거절한다.

## 처리 규칙

- 각 행은 독립 savepoint로 처리한다. 한 행의 충돌은 다른 행을 롤백하지 않는다.
- 같은 슬롯의 다른 키는 교체하고, 같은 키는 `SKIPPED` no-op으로 반환한다.
- 요청에 없는 detail 슬롯은 보존한다.
- 다른 슬롯이 이미 쓰는 `storage_key` 또는 키 교환 시도는 자동 추측하지 않고 `FAILED`로 반환한다.
- 실제 변경 시에만 `Product.updated_at`을 갱신한다.
- 실제 변경된 상품이 `HIDDEN`이 아니면 전체 commit 후 ES 문서를 best-effort로 동기화한다. HIDDEN 및 no-op은 동기화하지 않는다.

## 응답

```json
{
  "summary": {"total": 2, "updated": 1, "skipped": 0, "failed": 1},
  "rows": [
    {
      "row_number": 1,
      "import_sku": "IMPORT_001",
      "status": "UPDATED",
      "product_code": "prod_mwbl_example"
    },
    {
      "row_number": 2,
      "import_sku": "IMPORT_404",
      "status": "FAILED",
      "field": "import_sku",
      "error_code": "IMPORT_SKU_NOT_FOUND",
      "message": "이미지 연결 대상 상품을 import_sku로 찾을 수 없습니다."
    }
  ]
}
```

행 상태는 `UPDATED`, `SKIPPED`, `FAILED`다. `FAILED` 행은 다른 성공 행의 commit을 취소하지 않는다.

## 주요 오류

- `INVALID_IMAGE_INPUT` (400): 형식, 슬롯 또는 storage_key가 올바르지 않음
- `IMPORT_SKU_NOT_FOUND` (행 실패): 대상 상품 없음
- `DUPLICATE_IMAGE_SLOT_IN_REQUEST` (행 실패): 요청 안 동일 슬롯 중복
- `PRODUCT_IMAGE_STORAGE_KEY_CONFLICT` (행 실패): 같은 상품의 다른 슬롯이 이미 쓰는 key, 키 교환 또는 동시 충돌
- `PRODUCT_NOT_FOUND` (행 실패): 검증 뒤 대상 상품이 삭제됨
