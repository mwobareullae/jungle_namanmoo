import { useState } from "react";

import { AdminProductRow, AdminSalesStatus } from "../api/adminProductApi";
import { AdminProductActiveFilter, useAdminProducts } from "./useAdminProducts";

// 관리자 상품 조회 화면 (P1-M3-A, 조회 전용). 등록/수정(폼)은 Chunk 5.
// 부모(AdminDashboardPage)와는 onOperationLog(공용 운영 로그)만 공유한다.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type AdminProductSectionProps = {
  active: boolean;
  onEditProduct: (productCode: string) => void;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
};

const SALES_STATUS_LABELS: Record<AdminSalesStatus, string> = {
  ON_SALE: "판매중",
  SOLD_OUT: "품절",
  HIDDEN: "숨김",
  UNKNOWN: "미상"
};

const STOCK_STATUS_LABELS: Record<string, string> = {
  IN_STOCK: "재고 정상",
  LOW_STOCK: "품절임박",
  SOLD_OUT: "품절",
  HIDDEN: "숨김",
  UNKNOWN: "미상"
};

const salesTone = (status: AdminSalesStatus): BadgeTone => {
  if (status === "ON_SALE") return "success";
  if (status === "SOLD_OUT") return "danger";
  if (status === "HIDDEN") return "neutral";
  return "review";
};

const stockTone = (status: string): BadgeTone => {
  if (status === "IN_STOCK") return "success";
  if (status === "LOW_STOCK") return "warning";
  if (status === "SOLD_OUT") return "danger";
  return "neutral";
};

const formatPrice = (price: number | null): string =>
  price === null ? "-" : `${price.toLocaleString("ko-KR")}원`;

export function AdminProductSection({ active, onEditProduct, onOperationLog }: AdminProductSectionProps) {
  const {
    items,
    pagination,
    loading,
    error,
    page,
    activeFilter,
    salesStatusFilter,
    applySearch,
    setActiveFilter,
    setSalesStatusFilter,
    resetFilters,
    refresh,
    goToPage,
    selectedCode,
    detail,
    detailLoading,
    detailError,
    selectProduct
  } = useAdminProducts({ enabled: active });

  const [searchInput, setSearchInput] = useState("");

  const handleSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    applySearch(searchInput);
  };

  const handleReset = () => {
    setSearchInput("");
    resetFilters();
  };

  const handleRefresh = async () => {
    const succeeded = await refresh();
    onOperationLog(
      "상품",
      succeeded ? "상품 목록 새로고침" : "상품 목록 새로고침 실패",
      succeeded ? "관리자 상품 목록을 다시 불러왔습니다." : "잠시 후 다시 시도해 주세요.",
      succeeded ? "success" : "danger"
    );
  };

  const totalPages = pagination?.totalPages ?? 1;

  return (
    <section className="admin-product-layout" hidden={!active}>
      <section className="admin-panel admin-product-panel">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>상품 조회/상태 확인</p>
            <h2>상품 운영 목록{pagination ? ` (${pagination.totalItems.toLocaleString("ko-KR")}건)` : ""}</h2>
          </div>
          <form className="admin-filter-row" onSubmit={handleSearchSubmit}>
            <input
              aria-label="상품명 검색"
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="상품명 검색"
              type="search"
              value={searchInput}
            />
            <select
              aria-label="노출 필터"
              onChange={(event) => setActiveFilter(event.target.value as AdminProductActiveFilter)}
              value={activeFilter}
            >
              <option value="all">노출 전체</option>
              <option value="active">공개</option>
              <option value="inactive">비공개</option>
            </select>
            <select
              aria-label="판매 상태 필터"
              onChange={(event) =>
                setSalesStatusFilter(event.target.value === "" ? null : (event.target.value as AdminSalesStatus))
              }
              value={salesStatusFilter ?? ""}
            >
              <option value="">판매상태 전체</option>
              <option value="ON_SALE">판매중</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">숨김</option>
              <option value="UNKNOWN">재고미상</option>
            </select>
            <button className="admin-secondary-button" disabled={loading} type="submit">
              검색
            </button>
            <button className="admin-secondary-button" onClick={handleReset} type="button">
              초기화
            </button>
            <button className="admin-primary-button" disabled={loading} onClick={handleRefresh} type="button">
              새로고침
            </button>
          </form>
        </div>

        {error && (
          <div className="admin-state-banner danger">
            <strong>상품 목록을 불러오지 못했습니다</strong>
            <span>{error}</span>
          </div>
        )}

        <div className="admin-table-wrap">
          <table className="admin-table admin-product-table">
            <thead>
              <tr>
                <th scope="col">상품</th>
                <th scope="col">카테고리</th>
                <th scope="col">가격</th>
                <th scope="col">판매/재고</th>
                <th scope="col">노출</th>
                <th scope="col">이미지</th>
                <th scope="col">수정일</th>
              </tr>
            </thead>
            <tbody>
              {items.map((product: AdminProductRow) => (
                <tr
                  className={product.productCode === selectedCode ? "selected" : undefined}
                  key={product.productCode}
                  onClick={() => void selectProduct(product.productCode)}
                >
                  <td>
                    <strong className="admin-product-name">{product.name}</strong>
                    <small className="admin-product-code">
                      {product.brand} · {product.productCode}
                    </small>
                  </td>
                  <td>{product.categoryName}</td>
                  <td>{formatPrice(product.price)}</td>
                  <td>
                    <div className="admin-product-status-badges">
                      <span className={`admin-badge ${salesTone(product.availability.salesStatus)}`}>
                        {SALES_STATUS_LABELS[product.availability.salesStatus]}
                      </span>
                      <span className={`admin-badge ${stockTone(product.availability.stockStatus)}`}>
                        {STOCK_STATUS_LABELS[product.availability.stockStatus]}
                      </span>
                    </div>
                    <small className="admin-product-code">
                      가용 {product.availability.availableQuantity ?? "-"} / 재고 {product.stockQuantity ?? "-"}
                    </small>
                  </td>
                  <td>
                    <span className={`admin-badge ${product.isActive ? "success" : "neutral"}`}>
                      {product.isActive ? "공개" : "비공개"}
                    </span>
                  </td>
                  <td>{product.imageCount}</td>
                  <td>{product.updatedAt}</td>
                </tr>
              ))}
              {loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={7}>
                    상품을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={7}>
                    {error ? "상품 목록을 불러오지 못했습니다." : "조건에 맞는 상품이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="admin-filter-row">
          <button
            className="admin-secondary-button"
            disabled={page <= 1 || loading}
            onClick={() => goToPage(page - 1)}
            type="button"
          >
            이전
          </button>
          <span>
            {page} / {totalPages} 페이지
          </span>
          <button
            className="admin-secondary-button"
            disabled={page >= totalPages || loading}
            onClick={() => goToPage(page + 1)}
            type="button"
          >
            다음
          </button>
        </div>
      </section>

      <aside className="admin-panel admin-product-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 상품</p>
            <h2>{detail ? detail.name : "선택된 상품 없음"}</h2>
          </div>
          {detail && (
            <span className={`admin-badge ${detail.isActive ? "success" : "neutral"}`}>
              {detail.isActive ? "공개" : "비공개"}
            </span>
          )}
        </div>
        {detailError && (
          <div className="admin-state-banner danger">
            <strong>상품 상세를 불러오지 못했습니다</strong>
            <span>{detailError}</span>
          </div>
        )}
        {detailLoading && !detail ? (
          <div className="admin-state-banner neutral">
            <strong>상세 정보를 불러오는 중입니다</strong>
            <span>잠시만 기다려 주세요.</span>
          </div>
        ) : detail ? (
          <>
            <dl className="admin-metric-list">
              <div>
                <dt>product_code</dt>
                <dd>{detail.productCode}</dd>
              </div>
              <div>
                <dt>브랜드</dt>
                <dd>{detail.brand}</dd>
              </div>
              <div>
                <dt>카테고리</dt>
                <dd>{detail.categoryName}</dd>
              </div>
              <div>
                <dt>셀러</dt>
                <dd>{detail.sellerName}</dd>
              </div>
              <div>
                <dt>가격</dt>
                <dd>{formatPrice(detail.price)}</dd>
              </div>
              <div>
                <dt>판매 상태</dt>
                <dd>{SALES_STATUS_LABELS[detail.availability.salesStatus]}</dd>
              </div>
              <div>
                <dt>재고 상태</dt>
                <dd>
                  {STOCK_STATUS_LABELS[detail.availability.stockStatus]} (가용{" "}
                  {detail.availability.availableQuantity ?? "-"} / 재고 {detail.stockQuantity ?? "-"})
                </dd>
              </div>
              <div>
                <dt>추천 가능</dt>
                <dd>{detail.isRecommendable ? "가능" : "제외"}</dd>
              </div>
              <div>
                <dt>이미지</dt>
                <dd>{detail.imageCount}개</dd>
              </div>
              <div>
                <dt>수정일</dt>
                <dd>{detail.updatedAt}</dd>
              </div>
            </dl>
            <button
              className="admin-primary-button"
              onClick={() => onEditProduct(detail.productCode)}
              type="button"
            >
              이 상품 수정
            </button>
          </>
        ) : (
          <div className="admin-state-banner neutral">
            <strong>선택된 상품 없음</strong>
            <span>표에서 상품을 선택하면 상세 정보가 표시됩니다.</span>
          </div>
        )}
      </aside>
    </section>
  );
}
