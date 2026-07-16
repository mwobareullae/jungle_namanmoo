import type { FormEvent } from "react";

import { useAdminProductForm } from "./useAdminProductForm";

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type AdminProductFormSectionProps = {
  active: boolean;
  productCode: string | null;
  onSaved: (productCode: string) => void;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
};

export function AdminProductFormSection({
  active,
  productCode,
  onSaved,
  onOperationLog
}: AdminProductFormSectionProps) {
  const {
    brands,
    categories,
    optionsLoading,
    optionsError,
    detail,
    values,
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
            <button className="admin-secondary-button" disabled={!dirty || submitting} onClick={reset} type="button">
              입력값 되돌리기
            </button>
            <button
              className="admin-primary-button"
              disabled={loading || optionsLoading || submitting || Boolean(optionsError) || (isEdit && !dirty)}
              type="submit"
            >
              {submitting ? "저장 중..." : isEdit ? "수정 저장" : "상품 등록"}
            </button>
          </div>
        </div>

        {(loading || optionsLoading) && (
          <div className="admin-state-banner neutral">
            <strong>상품 폼을 준비하는 중입니다</strong>
            <span>상품 정보와 선택 목록을 불러오고 있습니다.</span>
          </div>
        )}
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
        {!error && !optionsError && !savedMessage && (
          <div className={`admin-state-banner ${dirty ? "warning" : "neutral"}`}>
            <strong>{dirty ? "저장 대기" : "변경 없음"}</strong>
            <span>{dirty ? "수정한 내용은 저장 전까지 서버에 반영되지 않습니다." : "상품 기본정보를 입력해 주세요."}</span>
          </div>
        )}

        <div className="admin-form-grid">
          {isEdit && (
            <label>
              product_code
              <input disabled readOnly value={productCode ?? ""} />
            </label>
          )}
          <label>
            상품명
            <input
              disabled={loading || submitting}
              onChange={(event) => patchValues({ name: event.target.value })}
              placeholder="상품명을 입력하세요"
              value={values.name}
            />
          </label>
          <label>
            브랜드
            <select
              disabled={optionsLoading || submitting}
              onChange={(event) => patchValues({ brandCode: event.target.value })}
              value={values.brandCode}
            >
              <option value="">브랜드 선택</option>
              {brands.map((brand) => (
                <option key={brand.code} value={brand.code}>{brand.name}</option>
              ))}
            </select>
          </label>
          <label>
            카테고리
            <select
              disabled={optionsLoading || submitting}
              onChange={(event) => patchValues({ categoryCode: event.target.value })}
              value={values.categoryCode}
            >
              <option value="">카테고리 선택</option>
              {categories.map((category) => (
                <option key={category.code} value={category.code}>{category.name}</option>
              ))}
            </select>
          </label>
          <label>
            판매가
            <input
              disabled={loading || submitting}
              min="1"
              onChange={(event) => patchValues({ price: event.target.value })}
              step="1"
              type="number"
              value={values.price}
            />
          </label>
          <label>
            출시일
            <input
              disabled={loading || submitting}
              onChange={(event) => patchValues({ releasedDate: event.target.value })}
              type="date"
              value={values.releasedDate}
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
            <input
              disabled={loading || submitting}
              onChange={(event) => patchValues({ thumbnailStorageKey: event.target.value })}
              placeholder="products/.../thumbnail_0"
              value={values.thumbnailStorageKey}
            />
            <small>완성 URL이 아닌, 스토리지에 이미 업로드된 상대 경로만 입력합니다.</small>
          </label>
        </div>
      </form>

      <aside className="admin-panel admin-product-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>운영 기본값</p>
            <h2>{detail?.name ?? "신규 상품"}</h2>
          </div>
          <span className="admin-badge neutral">{detail?.isActive ? "공개" : "비공개"}</span>
        </div>
        <dl className="admin-metric-list">
          <div><dt>셀러</dt><dd>{detail?.sellerName ?? "뭐바를래"}</dd></div>
          <div><dt>판매 상태</dt><dd>{detail?.availability.salesStatus ?? "HIDDEN"}</dd></div>
          <div><dt>재고</dt><dd>{detail?.stockQuantity ?? 0}</dd></div>
          <div><dt>추천</dt><dd>{detail?.isRecommendable ? "가능" : "제외"}</dd></div>
        </dl>
        <div className="admin-state-banner neutral">
          <strong>이번 단계에서 편집하지 않는 항목</strong>
          <span>재고·판매 상태는 M4, 성분은 M2/M3-B에서 관리합니다. 여기서는 대표 이미지 storage_key 1개만 연결합니다.</span>
        </div>
        <div className="admin-state-banner warning">
          <strong>공개 전 확인</strong>
          <span>재고 상태가 HIDDEN인 상품은 공개할 수 없습니다. 먼저 재고 운영에서 판매 상태를 준비해야 합니다.</span>
        </div>
      </aside>
    </section>
  );
}
