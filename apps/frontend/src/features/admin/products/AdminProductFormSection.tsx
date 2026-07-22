import { useEffect, useState, type FormEvent } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import { SearchableSelect } from "../../../components/ui/SearchableSelect";
import { getProductImageUrl } from "../../../lib/imageUrls";
import { useAdminProductForm } from "./useAdminProductForm";

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

const SALES_STATUS_LABELS: Record<string, string> = {
  ON_SALE: "판매중",
  SOLD_OUT: "품절",
  HIDDEN: "숨김",
  UNKNOWN: "미상"
};

type AdminProductFormSectionProps = {
  active: boolean;
  productCode: string | null;
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (productCode: string) => void;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
  onViewInventory: () => void;
};

export function AdminProductFormSection({
  active,
  productCode,
  onDirtyChange,
  onSaved,
  onOperationLog,
  onViewInventory
}: AdminProductFormSectionProps) {
  const {
    brands,
    categories,
    optionsLoading,
    optionsError,
    detail,
    values,
    originalValues,
    loading,
    submitting,
    error,
    savedMessage,
    dirty,
    patchValues,
    reset,
    submit
  } = useAdminProductForm({ enabled: active, productCode });

  const isEdit = productCode !== null;
  const [confirmingNavigation, setConfirmingNavigation] = useState(false);
  const [thumbnailPreviewError, setThumbnailPreviewError] = useState(false);
  const thumbnailStorageKey = values.thumbnailStorageKey.trim();
  const thumbnailPreviewUrl = thumbnailStorageKey ? getProductImageUrl(thumbnailStorageKey) : "";

  // 신규 등록 중 "운영 기본값" 위젯에 보여줄 미리보기. 매 입력마다가 아니라, 필드에서
  // 포커스가 빠질 때(다른 곳 클릭 시)만 반영한다 — 타이핑 중 계속 흔들리지 않게.
  const [previewValues, setPreviewValues] = useState(values);
  const commitPreview = () => setPreviewValues(values);

  // 다른 상품으로 전환하면(수정 대상이 바뀌면) 이전 상품의 미리보기 실패 상태가 남지 않게 한다.
  useEffect(() => {
    void Promise.resolve().then(() => setThumbnailPreviewError(false));
  }, [productCode]);

  // 상품을 새로 불러오거나(수정 대상 전환) 저장에 성공하면 기준값이 바뀌므로, 운영 기본값
  // 미리보기도 그 기준으로 다시 맞춘다.
  useEffect(() => {
    void Promise.resolve().then(() => setPreviewValues(originalValues));
  }, [originalValues]);

  // 부모(AdminDashboardPage)가 사이드바 이동 시 저장 안 한 내용이 있는지 알 수 있게 알려준다.
  useEffect(() => {
    void Promise.resolve().then(() => onDirtyChange(dirty));
  }, [dirty, onDirtyChange]);

  const handleViewInventoryClick = () => {
    if (dirty) {
      setConfirmingNavigation(true);
      return;
    }
    onViewInventory();
  };

  const handleReset = () => {
    reset();
    setPreviewValues(originalValues);
  };

  const previewBrandName = brands.find((brand) => brand.code === previewValues.brandCode)?.name ?? "-";
  const previewCategoryName =
    categories.find((category) => category.code === previewValues.categoryCode)?.name ?? "-";
  const previewPrice = Number(previewValues.price);
  const previewPriceLabel =
    previewValues.price && Number.isFinite(previewPrice) ? `${previewPrice.toLocaleString("ko-KR")}원` : "-";

  // 새 상품 등록 시 필수 항목(상품명·브랜드·카테고리·판매가)이 하나라도 비어 있으면
  // 등록 버튼을 비활성 상태로 시작한다 — useAdminProductForm.submit() 의 검증 규칙과 동일하다.
  const canCreate =
    Boolean(values.name.trim()) &&
    Boolean(values.brandCode) &&
    Boolean(values.categoryCode) &&
    Number.isInteger(Number(values.price)) &&
    Number(values.price) > 0;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const result = await submit();
    if (!result) return;
    onSaved(result.productCode);
    onOperationLog(
      "상품",
      isEdit ? "상품 기본정보 수정" : "새 상품 등록",
      `${result.name} · ${result.productCode}`,
      "success"
    );
  };

  return (
    <section className="admin-product-layout" hidden={!active}>
      <form className="admin-panel admin-product-form" onSubmit={handleSubmit}>
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>상품 등록/수정</p>
            <h2>{isEdit ? "상품 기본정보 수정" : "새 상품 등록"}</h2>
          </div>
          <div className="admin-filter-row">
            <button
              className="admin-secondary-button admin-light-button"
              disabled={!dirty || submitting}
              onClick={handleReset}
              type="button"
            >
              입력값 되돌리기
            </button>
            <button
              className="admin-primary-button"
              disabled={
                loading ||
                optionsLoading ||
                submitting ||
                Boolean(optionsError) ||
                (isEdit && !dirty) ||
                (!isEdit && !canCreate)
              }
              type="submit"
            >
              {submitting ? "저장 중..." : isEdit ? "수정 저장" : "상품 등록"}
            </button>
          </div>
        </div>

        {(error || optionsError) && (
          <div className="admin-state-banner danger" role="alert">
            <strong>상품을 저장할 수 없습니다</strong>
            <span>{error ?? optionsError}</span>
          </div>
        )}
        {savedMessage && (
          <div className="admin-state-banner success" role="status">
            <strong>저장 완료</strong>
            <span>{savedMessage}</span>
          </div>
        )}
        {!error && !optionsError && !savedMessage && isEdit && dirty && (
          <div className="admin-state-banner warning">
            <strong>저장 대기</strong>
            <span>수정한 내용은 저장 전까지 서버에 반영되지 않습니다.</span>
          </div>
        )}

        <div className="admin-form-grid">
          {isEdit && (
            <label>
              상품코드
              <input disabled readOnly value={productCode ?? ""} />
            </label>
          )}
          <label>
            <span className="admin-form-label-text">
              상품명 <span className="admin-required-mark">*</span>
            </span>
            <input
              disabled={loading || submitting}
              onBlur={commitPreview}
              onChange={(event) => patchValues({ name: event.target.value })}
              placeholder="상품명을 입력하세요"
              value={values.name}
            />
          </label>
          <label>
            <span className="admin-form-label-text">
              브랜드 <span className="admin-required-mark">*</span>
            </span>
            <SearchableSelect
              ariaLabel="브랜드"
              disabled={optionsLoading || submitting}
              onBlur={commitPreview}
              onChange={(brandCode) => patchValues({ brandCode })}
              options={brands}
              placeholder="브랜드 검색"
              value={values.brandCode}
            />
          </label>
          <label>
            <span className="admin-form-label-text">
              카테고리 <span className="admin-required-mark">*</span>
            </span>
            <SearchableSelect
              ariaLabel="카테고리"
              disabled={optionsLoading || submitting}
              onBlur={commitPreview}
              onChange={(categoryCode) => patchValues({ categoryCode })}
              options={categories}
              placeholder="카테고리 검색"
              value={values.categoryCode}
            />
          </label>
          <label>
            <span className="admin-form-label-text">
              판매가 <span className="admin-required-mark">*</span>
            </span>
            <input
              disabled={loading || submitting}
              min="1"
              onBlur={commitPreview}
              onChange={(event) => patchValues({ price: event.target.value })}
              placeholder="예: 19900"
              step="1"
              type="number"
              value={values.price}
            />
          </label>
          <label>
            노출 상태
            {isEdit ? (
              <select
                disabled={loading || submitting}
                onChange={(event) => patchValues({ isActive: event.target.value === "true" })}
                value={String(values.isActive)}
              >
                <option value="false">비공개</option>
                <option value="true">공개</option>
              </select>
            ) : (
              <input disabled readOnly value="등록 후 비공개" />
            )}
          </label>
          <label className="admin-form-wide">
            상품 설명
            <textarea
              disabled={loading || submitting}
              onChange={(event) => patchValues({ description: event.target.value })}
              placeholder="상품 설명을 입력하세요"
              rows={5}
              value={values.description}
            />
          </label>
          <label className="admin-form-wide">
            대표 이미지 storage_key
            <div className="admin-thumbnail-field">
              <input
                disabled={loading || submitting}
                onChange={(event) => {
                  patchValues({ thumbnailStorageKey: event.target.value });
                  setThumbnailPreviewError(false);
                }}
                placeholder="products/.../thumbnail_0"
                value={values.thumbnailStorageKey}
              />
              <div className="admin-thumbnail-preview">
                {thumbnailPreviewUrl && !thumbnailPreviewError ? (
                  <img
                    alt="대표 이미지 미리보기"
                    onError={() => setThumbnailPreviewError(true)}
                    src={thumbnailPreviewUrl}
                  />
                ) : (
                  <span>{thumbnailStorageKey ? "이미지를 불러올 수 없습니다" : "미리보기 없음"}</span>
                )}
              </div>
            </div>
            <small>완성 URL이 아닌, 스토리지에 이미 업로드된 상대 경로만 입력합니다.</small>
          </label>
        </div>
      </form>

      <aside className="admin-panel admin-product-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>운영 기본값</p>
            <h2>{detail ? detail.name : previewValues.name.trim() || "신규 상품"}</h2>
          </div>
          {detail ? (
            <span className="admin-badge neutral">{detail.isActive ? "공개" : "비공개"}</span>
          ) : (
            <span className="admin-badge neutral">비공개</span>
          )}
        </div>
        {detail ? (
          <>
            <dl className="admin-metric-list">
              <div><dt>상품코드</dt><dd>{detail.productCode}</dd></div>
              <div><dt>브랜드</dt><dd>{detail.brand}</dd></div>
              <div><dt>카테고리</dt><dd>{detail.categoryName}</dd></div>
              <div>
                <dt>판매가</dt>
                <dd>{detail.price === null ? "-" : `${detail.price.toLocaleString("ko-KR")}원`}</dd>
              </div>
              <div>
                <dt>판매 상태/재고</dt>
                <dd>
                  {SALES_STATUS_LABELS[detail.availability.salesStatus]} · 재고{" "}
                  {(detail.stockQuantity ?? 0).toLocaleString("ko-KR")}개
                </dd>
              </div>
              <div><dt>노출 상태</dt><dd>{detail.isActive ? "공개" : "비공개"}</dd></div>
            </dl>
            <button
              className="admin-secondary-button admin-light-button"
              onClick={handleViewInventoryClick}
              type="button"
            >
              재고/가격 확인으로 이동
            </button>
          </>
        ) : (
          <dl className="admin-metric-list">
            <div><dt>브랜드</dt><dd>{previewBrandName}</dd></div>
            <div><dt>카테고리</dt><dd>{previewCategoryName}</dd></div>
            <div><dt>판매가</dt><dd>{previewPriceLabel}</dd></div>
            <div><dt>노출 상태</dt><dd>비공개</dd></div>
          </dl>
        )}
      </aside>
      <ConfirmModal
        compact
        message="저장하지 않은 수정 내용이 있습니다. 지금 이동하면 사라집니다. 계속할까요?"
        onCancel={() => setConfirmingNavigation(false)}
        onConfirm={() => {
          setConfirmingNavigation(false);
          onViewInventory();
        }}
        open={confirmingNavigation}
      />
    </section>
  );
}
