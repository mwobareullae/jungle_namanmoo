import { useEffect, useState } from "react";

import { AdminProductRow, AdminSalesStatus, AdminStockStatus } from "../api/adminProductApi";
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

// 상세 패널의 판매/재고 상태 배지 색상. 표의 combinedStatus 톤과 어긋나지 않게 맞춘다.
const SALES_STATUS_TONE: Record<AdminSalesStatus, BadgeTone> = {
  ON_SALE: "success",
  SOLD_OUT: "danger",
  HIDDEN: "warning",
  UNKNOWN: "review"
};

const STOCK_STATUS_TONE: Record<string, BadgeTone> = {
  IN_STOCK: "success",
  LOW_STOCK: "warning",
  SOLD_OUT: "danger",
  HIDDEN: "neutral",
  UNKNOWN: "review"
};

// 비공개(Product.is_active=false)와 판매 숨김(Inventory.sales_status=HIDDEN)은 서로 다른 상태라
// 각각 별도로 유지하되, 목록에서는 한 배지로 조합해 보여준다. 재고 상태(품절 임박 등 세부값)는
// 목록에서 빼고 상세 패널에서만 보여준다.
const combinedStatus = (product: AdminProductRow): { label: string; tone: BadgeTone } => {
  if (!product.isActive) return { label: "비공개", tone: "neutral" };
  const status = product.availability.salesStatus;
  if (status === "ON_SALE") return { label: "공개 · 판매중", tone: "success" };
  if (status === "SOLD_OUT") return { label: "공개 · 품절", tone: "danger" };
  if (status === "HIDDEN") return { label: "공개 · 판매 숨김", tone: "warning" };
  return { label: "공개 · 재고 미확인", tone: "review" };
};

const formatPrice = (price: number | null): string =>
  price === null ? "-" : `${price.toLocaleString("ko-KR")}원`;

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// 네이버식 블록 페이지네이션. 10개씩 묶어서 보여주고 "다음"으로 다음 10개 블록으로 이동한다.
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  const pages: number[] = [];
  for (let page = start; page <= end; page += 1) pages.push(page);
  return pages;
};

export function AdminProductSection({ active, onEditProduct, onOperationLog }: AdminProductSectionProps) {
  const {
    items,
    pagination,
    loading,
    error,
    page,
    pageSize,
    activeFilter,
    salesStatusFilter,
    stockStatusFilter,
    brandCodeFilter,
    categoryCodeFilter,
    brands,
    categories,
    applySearch,
    setActiveFilter,
    setSalesStatusFilter,
    setStockStatusFilter,
    setBrandCodeFilter,
    setCategoryCodeFilter,
    setPageSize,
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

  // 페이지를 넘기면(검색/필터로 인한 1페이지 초기화 포함) 스크롤을 맨 위로 되돌린다.
  useEffect(() => {
    if (!active) return;
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [active, page]);

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
    if (succeeded) return;
    onOperationLog("상품", "상품 목록 새로고침 실패", "잠시 후 다시 시도해 주세요.", "danger");
  };

  const totalPages = pagination?.totalPages ?? 1;
  const blockPages = getBlockPages(page, totalPages);
  const blockStart = blockPages[0] ?? 1;
  const blockEnd = blockPages[blockPages.length - 1] ?? 1;
  const hasPrevBlock = blockStart > 1;
  const hasNextBlock = blockEnd < totalPages;

  return (
    <section className="admin-product-layout" hidden={!active}>
      <section className="admin-panel admin-product-panel">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>상품 조회/상태 확인</p>
            <h2>상품 운영 목록{pagination ? ` (${pagination.totalItems.toLocaleString("ko-KR")}건)` : ""}</h2>
          </div>
          <button
            aria-label="새로고침"
            className="admin-secondary-button admin-light-button"
            disabled={loading}
            onClick={handleRefresh}
            type="button"
          >
            새로고침
          </button>
        </div>

        <div className="admin-product-filters">
          <form className="admin-filter-row" onSubmit={handleSearchSubmit}>
            <input
              aria-label="상품명·상품코드 검색"
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="상품명·상품코드 검색"
              type="search"
              value={searchInput}
            />
            <button className="admin-secondary-button admin-light-button" disabled={loading} type="submit">
              검색
            </button>
          </form>
          <div className="admin-filter-row">
            <select
              aria-label="카테고리 필터"
              onChange={(event) => setCategoryCodeFilter(event.target.value === "" ? null : event.target.value)}
              value={categoryCodeFilter ?? ""}
            >
              <option value="">카테고리 전체</option>
              {categories.map((category) => (
                <option key={category.code} value={category.code}>
                  {category.name}
                </option>
              ))}
            </select>
            <select
              aria-label="브랜드 필터"
              onChange={(event) => setBrandCodeFilter(event.target.value === "" ? null : event.target.value)}
              value={brandCodeFilter ?? ""}
            >
              <option value="">브랜드 전체</option>
              {brands.map((brand) => (
                <option key={brand.code} value={brand.code}>
                  {brand.name}
                </option>
              ))}
            </select>
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
            <select
              aria-label="재고 상태 필터"
              onChange={(event) =>
                setStockStatusFilter(event.target.value === "" ? null : (event.target.value as AdminStockStatus))
              }
              value={stockStatusFilter ?? ""}
            >
              <option value="">재고상태 전체</option>
              <option value="IN_STOCK">재고 정상</option>
              <option value="LOW_STOCK">품절 임박</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">판매 숨김</option>
              <option value="UNKNOWN">재고 미확인</option>
            </select>
            <button className="admin-secondary-button admin-light-button" onClick={handleReset} type="button">
              초기화
            </button>
          </div>
        </div>

        {error && (
          <div className="admin-state-banner danger">
            <strong>상품 목록을 불러오지 못했습니다</strong>
            <span>{error}</span>
          </div>
        )}

        <div className="admin-list-toolbar">
          <div className="admin-page-size">
            <label htmlFor="admin-product-page-size">페이지당</label>
            <select
              id="admin-product-page-size"
              onChange={(event) => setPageSize(Number(event.target.value))}
              value={pageSize}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}개
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="admin-table-wrap">
          <table className="admin-table admin-product-table">
            <thead>
              <tr>
                <th scope="col">상품</th>
                <th scope="col">공개/판매 상태</th>
                <th scope="col">가격</th>
                <th scope="col">가용 재고</th>
                <th scope="col">수정일</th>
              </tr>
            </thead>
            <tbody>
              {items.map((product: AdminProductRow) => {
                const status = combinedStatus(product);
                return (
                  <tr
                    className={product.productCode === selectedCode ? "selected" : undefined}
                    key={product.productCode}
                    onClick={() => void selectProduct(product.productCode)}
                  >
                    <td>
                      <strong className="admin-product-name" title={product.name}>
                        {product.name}
                      </strong>
                      <small className="admin-product-code" title={`${product.brand} · ${product.productCode}`}>
                        {product.brand} · {product.productCode}
                      </small>
                    </td>
                    <td>
                      <span className={`admin-badge ${status.tone}`}>{status.label}</span>
                    </td>
                    <td>{formatPrice(product.price)}</td>
                    <td>{product.availability.availableQuantity ?? "-"}개</td>
                    <td>{product.updatedAt.slice(0, 10)}</td>
                  </tr>
                );
              })}
              {loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    상품을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    {error ? "상품 목록을 불러오지 못했습니다." : "조건에 맞는 상품이 없습니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="admin-pagination-row">
          <div className="admin-pagination">
            <button
              className="admin-pagination-jump"
              disabled={page <= 1 || loading}
              onClick={() => goToPage(1)}
              type="button"
            >
              처음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={!hasPrevBlock || loading}
              onClick={() => goToPage(blockStart - 1)}
              type="button"
            >
              이전
            </button>
            {blockPages.map((entry) => (
              <button
                className={`admin-pagination-page${entry === page ? " active" : ""}`}
                disabled={loading}
                key={entry}
                onClick={() => goToPage(entry)}
                type="button"
              >
                {entry}
              </button>
            ))}
            <button
              className="admin-pagination-jump"
              disabled={!hasNextBlock || loading}
              onClick={() => goToPage(blockEnd + 1)}
              type="button"
            >
              다음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={page >= totalPages || loading}
              onClick={() => goToPage(totalPages)}
              type="button"
            >
              맨끝
            </button>
          </div>
        </div>
      </section>

      <aside className="admin-panel admin-product-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 상품</p>
            <h2>{detail ? detail.name : "상세 정보"}</h2>
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
          <div className="admin-detail-body">
            <p className="admin-metric-group-title">기본 정보</p>
            <dl className="admin-metric-list">
              <div>
                <dt>상품코드</dt>
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
            </dl>

            <p className="admin-metric-group-title">판매 정보</p>
            <dl className="admin-metric-list">
              <div>
                <dt>가격</dt>
                <dd>{formatPrice(detail.price)}</dd>
              </div>
              <div>
                <dt>판매 상태</dt>
                <dd>
                  <span className={`admin-badge ${SALES_STATUS_TONE[detail.availability.salesStatus]}`}>
                    {SALES_STATUS_LABELS[detail.availability.salesStatus]}
                  </span>
                </dd>
              </div>
              <div>
                <dt>재고 상태</dt>
                <dd>
                  <span className={`admin-badge ${STOCK_STATUS_TONE[detail.availability.stockStatus]}`}>
                    {STOCK_STATUS_LABELS[detail.availability.stockStatus]}
                  </span>
                </dd>
              </div>
              <div>
                <dt>가용 재고</dt>
                <dd>
                  {detail.availability.availableQuantity ?? "-"}개
                  <span className="admin-metric-sub"> (총 재고 {detail.stockQuantity ?? "-"}개)</span>
                </dd>
              </div>
            </dl>

            <p className="admin-metric-group-title">운영 정보</p>
            <dl className="admin-metric-list">
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
          </div>
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
