import { useMemo, useState } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import { SearchableSelect } from "../../../components/ui/SearchableSelect";
import type { AdminInventoryPriceItem } from "../api/adminInventoryPriceApi";
import type {
  AdminInventoryActiveFilter,
  AdminInventorySalesStatusFilter,
  AdminInventoryStockStatusFilter
} from "./useAdminInventoryPrice";
import { useAdminInventoryPrice } from "./useAdminInventoryPrice";

type BadgeTone = "success" | "warning" | "danger" | "neutral";

const formatCurrency = (value: number | null) =>
  value == null ? "가격 정보 없음" : `${value.toLocaleString("ko-KR")}원`;

// 백엔드는 안정적인 저장 코드를 그대로 내려주고(계약상 프론트가 한글 라벨로 변환하기로 되어
// 있음), 여기서 그 매핑을 담당한다. 목록에 없는 새 코드가 추가되면 원본 코드를 그대로 보여준다.
const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  RESERVE: "주문 예약",
  SALE_CONFIRM: "결제 확정 차감",
  SALE_CANCEL: "결제 취소 복구",
  RELEASE_RESERVATION: "예약 해제",
  RETURN_RESTOCK: "반품 재입고",
  ADMIN_ADJUST: "관리자 조정",
  SEED: "초기 데이터",
  SEED_ADJUST: "초기 데이터 조정"
};
const movementTypeLabel = (movementType: string) => MOVEMENT_TYPE_LABELS[movementType] ?? movementType;

const formatDateTime = (value: string) =>
  new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value));

const statusBadges = (item: AdminInventoryPriceItem): Array<{ label: string; tone: BadgeTone }> => {
  const badges: Array<{ label: string; tone: BadgeTone }> = [];
  if (!item.isActive) badges.push({ label: "숨김", tone: "danger" });

  if (item.availability.salesStatus === "HIDDEN") {
    badges.push({ label: "판매 시작 전", tone: "warning" });
  } else if (item.availability.stockStatus === "SOLD_OUT") {
    badges.push({ label: "품절", tone: "danger" });
  } else if (item.availability.stockStatus === "LOW_STOCK") {
    badges.push({ label: "품절임박", tone: "warning" });
  } else if (item.availability.stockStatus === "UNKNOWN") {
    badges.push({ label: "재고 정보 없음", tone: "neutral" });
  } else if (
    item.availability.salesStatus === "ON_SALE" &&
    item.availability.stockStatus === "IN_STOCK"
  ) {
    badges.push({ label: "판매중", tone: "success" });
  }

  return badges.slice(0, 2);
};

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// 상품 조회/상태 확인과 같은 네이버식 블록 페이지네이션(10개씩 묶어서 이동).
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  const pages: number[] = [];
  for (let page = start; page <= end; page += 1) pages.push(page);
  return pages;
};

export function AdminInventoryPriceSection() {
  const inventory = useAdminInventoryPrice({ enabled: true });
  const [searchInput, setSearchInput] = useState("");
  const [draftProductCode, setDraftProductCode] = useState<string | null>(null);
  const [stockDraft, setStockDraft] = useState("");
  const [priceDraft, setPriceDraft] = useState("");
  const [reasonDraft, setReasonDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"sale" | "hide" | null>(null);

  const currentItems = inventory.items;

  // 검색 가능한 콤보박스도 "전체" 상태(필터 없음)를 선택지로 가질 수 있어야 하니, 맨 앞에
  // 합성 옵션을 끼워 넣는다. code가 빈 문자열이면 필터가 꺼진 상태와 동일하다.
  const categoryOptions = useMemo(
    () => [{ code: "", name: "카테고리 전체" }, ...inventory.categories],
    [inventory.categories]
  );
  const brandOptions = useMemo(
    () => [{ code: "", name: "브랜드 전체" }, ...inventory.brands],
    [inventory.brands]
  );

  const selectedItem = inventory.selectedItem;
  const actionPending = inventory.pendingAction !== null;
  const hasSelectedDraft = draftProductCode === selectedItem?.productCode;
  const displayedStockDraft = hasSelectedDraft
    ? stockDraft
    : selectedItem?.stockQuantity == null
      ? ""
      : String(selectedItem.stockQuantity);
  const displayedPriceDraft = hasSelectedDraft
    ? priceDraft
    : selectedItem?.price == null
      ? ""
      : String(selectedItem.price);
  const displayedReasonDraft = hasSelectedDraft ? reasonDraft : "";

  const handleSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    inventory.applySearch(searchInput);
  };

  const handleReset = () => {
    setSearchInput("");
    inventory.resetFilters();
  };

  const selectProduct = (productCode: string) => {
    setDraftProductCode(null);
    setFormError(null);
    setNotice(null);
    setConfirmAction(null);
    inventory.setSelectedProductCode(productCode);
  };

  const saveStock = async () => {
    if (!selectedItem) return;
    const stockQuantity = Number(displayedStockDraft);
    const reason = displayedReasonDraft.trim();
    if (!Number.isInteger(stockQuantity) || stockQuantity < 0 || stockQuantity > 1_000_000) {
      setFormError("재고는 0 이상 1,000,000 이하의 정수로 입력해 주세요.");
      return;
    }
    if (!reason || reason.length > 500) {
      setFormError("재고 변경 사유는 공백을 제외하고 1~500자로 입력해 주세요.");
      return;
    }

    setFormError(null);
    const outcome = await inventory.adjustStock(selectedItem.productCode, stockQuantity, reason);
    if (outcome.message) setNotice(outcome.message);
    if (outcome.result) {
      setDraftProductCode(selectedItem.productCode);
      setStockDraft(String(outcome.result.stockQuantity));
      setReasonDraft("");
    }
  };

  const savePrice = async () => {
    if (!selectedItem) return;
    const price = Number(displayedPriceDraft);
    if (!Number.isInteger(price) || price < 1 || price > 100_000_000) {
      setFormError("가격은 1원 이상 100,000,000원 이하의 정수로 입력해 주세요.");
      return;
    }

    setFormError(null);
    const outcome = await inventory.updatePrice(selectedItem.productCode, price);
    if (outcome.message) setNotice(outcome.message);
    if (outcome.result) {
      setDraftProductCode(selectedItem.productCode);
      setPriceDraft(String(outcome.result.price));
    }
  };

  const confirmSaleStart = async () => {
    if (!selectedItem) return;
    const outcome = await inventory.startSale(selectedItem.productCode);
    if (outcome.message) setNotice(outcome.message);
    if (outcome.result) setConfirmAction(null);
  };

  const confirmHide = async () => {
    if (!selectedItem) return;
    const outcome = await inventory.hideProduct(selectedItem.productCode);
    if (outcome.message) setNotice(outcome.message);
    if (outcome.result) setConfirmAction(null);
  };

  const totalPages = inventory.pagination?.totalPages ?? 1;
  const blockPages = getBlockPages(inventory.page, totalPages);
  const blockStart = blockPages[0] ?? 1;
  const blockEnd = blockPages[blockPages.length - 1] ?? 1;
  const hasPrevBlock = blockStart > 1;
  const hasNextBlock = blockEnd < totalPages;

  return (
    <section className="admin-inventory-layout">
      <section className="admin-panel admin-inventory-hero">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>재고·가격 상태 확인</p>
            <h2>가격·재고 저장과 판매 시작 확인</h2>
          </div>
          <button
            className="admin-secondary-button admin-light-button"
            disabled={inventory.loading}
            onClick={() => void inventory.refresh()}
            type="button"
          >
            새로고침
          </button>
        </div>
        <div className="admin-excel-summary-grid">
          <article className="admin-excel-summary neutral">
            <span>현재 목록</span>
            <strong>{(inventory.pagination?.totalItems ?? 0).toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary warning">
            <span>품절임박</span>
            <strong>{(inventory.summary?.lowStockCount ?? 0).toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary review">
            <span>판매 시작 전</span>
            <strong>{(inventory.summary?.hiddenCount ?? 0).toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary neutral">
            <span>재고 정보 없음</span>
            <strong>{(inventory.summary?.unknownCount ?? 0).toLocaleString("ko-KR")}</strong>
          </article>
        </div>
      </section>

      <section className="admin-panel admin-inventory-table-panel">
        <div className="admin-panel-header compact admin-inventory-filter-header">
          <div>
            <p>상품 목록</p>
            <h2>
              서버 상태 기준 조회
              {inventory.pagination ? ` (${inventory.pagination.totalItems.toLocaleString("ko-KR")}건)` : ""}
            </h2>
          </div>
        </div>

        <div className="admin-product-filters">
          <form className="admin-filter-row" onSubmit={handleSearchSubmit}>
            <input
              aria-label="상품명 검색"
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="상품명 검색"
              type="search"
              value={searchInput}
            />
            <button className="admin-secondary-button admin-light-button" disabled={inventory.loading} type="submit">
              검색
            </button>
          </form>
          <div className="admin-filter-row">
            <SearchableSelect
              ariaLabel="카테고리 필터"
              onChange={(code) => inventory.setCategoryCodeFilter(code === "" ? null : code)}
              options={categoryOptions}
              placeholder="카테고리 검색"
              value={inventory.categoryCodeFilter ?? ""}
            />
            <SearchableSelect
              ariaLabel="브랜드 필터"
              onChange={(code) => inventory.setBrandCodeFilter(code === "" ? null : code)}
              options={brandOptions}
              placeholder="브랜드 검색"
              value={inventory.brandCodeFilter ?? ""}
            />
            <select
              aria-label="노출 필터"
              onChange={(event) => inventory.setActiveFilter(event.target.value as AdminInventoryActiveFilter)}
              value={inventory.activeFilter}
            >
              <option value="all">노출 전체</option>
              <option value="active">공개</option>
              <option value="inactive">비공개</option>
            </select>
            <select
              aria-label="판매 상태 필터"
              onChange={(event) =>
                inventory.setSalesStatusFilter(event.target.value as AdminInventorySalesStatusFilter)
              }
              value={inventory.salesStatusFilter}
            >
              <option value="">전체 판매 상태</option>
              <option value="ON_SALE">판매중</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">판매 시작 전</option>
            </select>
            <select
              aria-label="재고 상태 필터"
              onChange={(event) =>
                inventory.setStockStatusFilter(event.target.value as AdminInventoryStockStatusFilter)
              }
              value={inventory.stockStatusFilter}
            >
              <option value="">전체 재고 상태</option>
              <option value="IN_STOCK">재고 충분</option>
              <option value="LOW_STOCK">품절임박</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">판매 시작 전</option>
            </select>
            <button className="admin-secondary-button admin-light-button" onClick={handleReset} type="button">
              초기화
            </button>
          </div>
        </div>

        {inventory.error && (
          <div className="admin-state-banner danger">
            <strong>재고·가격 목록을 불러오지 못했습니다</strong>
            <span>{inventory.error}</span>
          </div>
        )}

        <div className="admin-list-toolbar">
          <div className="admin-page-size">
            <label htmlFor="admin-inventory-page-size">페이지당</label>
            <select
              id="admin-inventory-page-size"
              onChange={(event) => inventory.setPageSize(Number(event.target.value))}
              value={inventory.pageSize}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}개
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="admin-table-wrap admin-inventory-table-scroll">
          <table className="admin-table admin-stock-table">
            <thead>
              <tr>
                <th scope="col">상품</th>
                <th scope="col">판매가</th>
                <th scope="col">가용/재고</th>
                <th scope="col">상태</th>
                <th scope="col">최근 변경</th>
              </tr>
            </thead>
            <tbody>
              {currentItems.map((item) => (
                <tr
                  className={
                    item.productCode === selectedItem?.productCode ? "selected" : undefined
                  }
                  key={item.productCode}
                >
                  <td>
                    <button
                      className="admin-inventory-product-button"
                      onClick={() => selectProduct(item.productCode)}
                      type="button"
                    >
                      <strong className="admin-product-name" title={item.name}>
                        {item.name}
                      </strong>
                      <small className="admin-product-code" title={`${item.brand} · ${item.productCode}`}>
                        {item.brand} · {item.productCode}
                      </small>
                    </button>
                  </td>
                  <td>{formatCurrency(item.price)}</td>
                  <td>
                    {item.stockQuantity == null
                      ? "재고 정보 없음"
                      : `${(item.availability.availableQuantity ?? 0).toLocaleString("ko-KR")} / ${item.stockQuantity.toLocaleString("ko-KR")}`}
                  </td>
                  <td>
                    <div className="admin-inventory-badges">
                      {statusBadges(item).map((badge) => (
                        <span className={`admin-badge ${badge.tone}`} key={badge.label}>
                          {badge.label}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>{formatDateTime(item.updatedAt)}</td>
                </tr>
              ))}
              {inventory.loading && currentItems.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    재고·가격 목록을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!inventory.loading && currentItems.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    조건에 맞는 상품이 없습니다.
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
              disabled={inventory.page <= 1 || inventory.loading}
              onClick={() => inventory.goToPage(1)}
              type="button"
            >
              처음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={!hasPrevBlock || inventory.loading}
              onClick={() => inventory.goToPage(blockStart - 1)}
              type="button"
            >
              이전
            </button>
            {blockPages.map((entry) => (
              <button
                className={`admin-pagination-page${entry === inventory.page ? " active" : ""}`}
                disabled={inventory.loading}
                key={entry}
                onClick={() => inventory.goToPage(entry)}
                type="button"
              >
                {entry}
              </button>
            ))}
            <button
              className="admin-pagination-jump"
              disabled={!hasNextBlock || inventory.loading}
              onClick={() => inventory.goToPage(blockEnd + 1)}
              type="button"
            >
              다음
            </button>
            <button
              className="admin-pagination-jump"
              disabled={inventory.page >= totalPages || inventory.loading}
              onClick={() => inventory.goToPage(totalPages)}
              type="button"
            >
              맨끝
            </button>
          </div>
        </div>
      </section>

      <aside className="admin-panel admin-inventory-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 상품</p>
            <h2>{selectedItem ? selectedItem.name : "상세 정보"}</h2>
          </div>
          {selectedItem && (
            <div className="admin-inventory-badges">
              {statusBadges(selectedItem).map((badge) => (
                <span className={`admin-badge ${badge.tone}`} key={badge.label}>
                  {badge.label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="admin-inventory-detail-scroll">
          {!selectedItem ? (
            <dl className="admin-metric-list">
              <div>
                <dt>브랜드</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>가용 재고</dt>
                <dd>-</dd>
              </div>
              <div>
                <dt>안전 재고</dt>
                <dd>-</dd>
              </div>
            </dl>
          ) : (
            <>
              <dl className="admin-metric-list">
                <div>
                  <dt>브랜드</dt>
                  <dd>{selectedItem.brand}</dd>
                </div>
                <div>
                  <dt>가용 재고</dt>
                  <dd>
                    {selectedItem.availability.availableQuantity?.toLocaleString("ko-KR") ??
                      "정보 없음"}
                  </dd>
                </div>
                <div>
                  <dt>안전 재고</dt>
                  <dd>{selectedItem.safetyStock?.toLocaleString("ko-KR") ?? "정보 없음"}</dd>
                </div>
              </dl>

              <section className="admin-inventory-action-card">
                <h3>가격 저장</h3>
                <div className="admin-inventory-inline-row">
                  <label>
                    <span>판매가 (원)</span>
                    <input
                      aria-label="판매가"
                      disabled={actionPending}
                      min="1"
                      onChange={(event) => {
                        setDraftProductCode(selectedItem.productCode);
                        setPriceDraft(event.target.value);
                      }}
                      type="number"
                      value={displayedPriceDraft}
                    />
                  </label>
                  <button
                    className="admin-primary-button"
                    disabled={actionPending}
                    onClick={() => void savePrice()}
                    type="button"
                  >
                    {inventory.pendingAction === "price" ? "저장 중" : "저장"}
                  </button>
                </div>
              </section>

              <section className="admin-inventory-action-card">
                <h3>재고 저장</h3>
                <label>
                  <span>현재 재고 수량</span>
                  <input
                    aria-label="현재 재고 수량"
                    disabled={actionPending || selectedItem.stockQuantity == null}
                    min="0"
                    onChange={(event) => {
                      setDraftProductCode(selectedItem.productCode);
                      setStockDraft(event.target.value);
                    }}
                    type="number"
                    value={displayedStockDraft}
                  />
                </label>
                <label>
                  <span>
                    변경 사유 (1~500자) <span className="admin-inventory-required">*</span>
                  </span>
                  <textarea
                    aria-label="재고 변경 사유"
                    disabled={actionPending || selectedItem.stockQuantity == null}
                    onChange={(event) => {
                      setDraftProductCode(selectedItem.productCode);
                      setReasonDraft(event.target.value);
                    }}
                    rows={2}
                    value={displayedReasonDraft}
                  />
                </label>
                {selectedItem.stockQuantity == null ? (
                  <p className="admin-inventory-help">
                    재고 행이 없는 상품은 재고를 수정할 수 없습니다.
                  </p>
                ) : (
                  <button
                    className="admin-primary-button"
                    disabled={actionPending}
                    onClick={() => void saveStock()}
                    type="button"
                  >
                    {inventory.pendingAction === "stock" ? "저장 중" : "저장"}
                  </button>
                )}
              </section>

              {selectedItem.availability.salesStatus === "HIDDEN" && (
                <section className="admin-inventory-action-card admin-inventory-sale-card">
                  <h3>판매 시작</h3>
                  <p>가격·가용 재고·브랜드·카테고리 상태를 확인한 뒤 고객에게 노출합니다.</p>
                  <button
                    className="admin-primary-button"
                    disabled={actionPending}
                    onClick={() => setConfirmAction("sale")}
                    type="button"
                  >
                    판매 시작
                  </button>
                </section>
              )}

              {selectedItem.isActive && (
                <section className="admin-inventory-action-card">
                  <h3>판매 중지</h3>
                  <p>고객에게 더 이상 노출하지 않고 비공개로 전환합니다.</p>
                  <button
                    className="admin-secondary-button admin-light-button"
                    disabled={actionPending}
                    onClick={() => setConfirmAction("hide")}
                    type="button"
                  >
                    숨김 처리
                  </button>
                </section>
              )}

              {(formError || inventory.actionError) && (
                <div className="admin-state-banner danger" role="alert">
                  <strong>저장할 수 없습니다</strong>
                  <span>{formError ?? inventory.actionError}</span>
                </div>
              )}
              {!formError && !inventory.actionError && notice && (
                <div className="admin-state-banner success" role="status">
                  <strong>처리 완료</strong>
                  <span>{notice}</span>
                </div>
              )}
            </>
          )}
        </div>
      </aside>

      <section className="admin-panel admin-inventory-history-panel">
        <div className="admin-panel-header compact">
          <div>
            <p>최근 변경</p>
            <h2>재고 이력 최근 20건</h2>
          </div>
        </div>
        {inventory.historyError && (
          <p className="admin-inventory-error" role="alert">
            {inventory.historyError}
          </p>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table compact admin-stock-history-table">
            <thead>
              <tr>
                <th scope="col">시각</th>
                <th scope="col">유형</th>
                <th scope="col">변경</th>
                <th scope="col">변경 후 재고</th>
                <th scope="col">사유</th>
              </tr>
            </thead>
            <tbody>
              {inventory.history.map((movement) => (
                <tr
                  key={`${movement.createdAt}-${movement.movementType}-${movement.referenceId ?? ""}`}
                >
                  <td>{formatDateTime(movement.createdAt)}</td>
                  <td>{movementTypeLabel(movement.movementType)}</td>
                  <td>
                    {movement.quantityDelta > 0 ? "+" : ""}
                    {movement.quantityDelta.toLocaleString("ko-KR")}
                  </td>
                  <td>{movement.stockAfter.toLocaleString("ko-KR")}</td>
                  <td>{movement.reason ?? "-"}</td>
                </tr>
              ))}
              {inventory.loadingHistory && inventory.history.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    재고 이력을 불러오는 중입니다...
                  </td>
                </tr>
              )}
              {!inventory.loadingHistory && inventory.history.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    {selectedItem ? "표시할 재고 이력이 없습니다." : "상품을 선택하면 재고 이력이 표시됩니다."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmModal
        confirmLabel={
          confirmAction === "sale"
            ? inventory.pendingAction === "sale"
              ? "판매 시작 중..."
              : "판매 시작"
            : inventory.pendingAction === "hide"
              ? "숨김 처리 중..."
              : "숨김 처리"
        }
        message={
          selectedItem
            ? confirmAction === "sale"
              ? `${selectedItem.name} 판매를 시작할까요? 가격·가용 재고·브랜드·카테고리 상태를 서버에서 다시 확인한 뒤 고객에게 노출합니다.`
              : `${selectedItem.name}을(를) 숨김 처리할까요? 즉시 고객 화면에서 노출이 중지됩니다.`
            : ""
        }
        onCancel={() => {
          if (actionPending) return;
          setConfirmAction(null);
        }}
        onConfirm={() => {
          if (actionPending) return;
          if (confirmAction === "sale") void confirmSaleStart();
          else if (confirmAction === "hide") void confirmHide();
        }}
        open={confirmAction !== null && selectedItem !== null}
        title={confirmAction === "sale" ? "판매 시작 확인" : "판매 중지 확인"}
      />
    </section>
  );
}
