import { useMemo, useState } from "react";

import type { AdminInventoryFilters, AdminInventoryPriceItem } from "../api/adminInventoryPriceApi";
import { useAdminInventoryPrice } from "./useAdminInventoryPrice";

type BadgeTone = "success" | "warning" | "danger" | "neutral";

type InventoryFilterForm = {
  query: string;
  salesStatus: "" | "ON_SALE" | "SOLD_OUT" | "HIDDEN";
  stockStatus: "" | "IN_STOCK" | "LOW_STOCK" | "SOLD_OUT" | "HIDDEN";
};

const initialFilters: InventoryFilterForm = {
  query: "",
  salesStatus: "",
  stockStatus: ""
};

const formatCurrency = (value: number | null) =>
  value == null ? "가격 정보 없음" : `${value.toLocaleString("ko-KR")}원`;

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

export function AdminInventoryPriceSection() {
  const [filterForm, setFilterForm] = useState<InventoryFilterForm>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<InventoryFilterForm>(initialFilters);
  const filters = useMemo<AdminInventoryFilters>(
    () => ({
      query: appliedFilters.query || undefined,
      salesStatus: appliedFilters.salesStatus || undefined,
      stockStatus: appliedFilters.stockStatus || undefined
    }),
    [appliedFilters]
  );
  const inventory = useAdminInventoryPrice(filters);
  const [draftProductCode, setDraftProductCode] = useState<string | null>(null);
  const [stockDraft, setStockDraft] = useState("");
  const [priceDraft, setPriceDraft] = useState("");
  const [reasonDraft, setReasonDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saleConfirmOpen, setSaleConfirmOpen] = useState(false);

  const currentItems = inventory.items;
  const summary = useMemo(
    () => ({
      lowStock: currentItems.filter((item) => item.availability.stockStatus === "LOW_STOCK").length,
      hidden: currentItems.filter((item) => item.availability.salesStatus === "HIDDEN").length,
      unknown: currentItems.filter((item) => item.availability.stockStatus === "UNKNOWN").length
    }),
    [currentItems]
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

  const applyFilters = () => {
    setAppliedFilters({ ...filterForm, query: filterForm.query.trim() });
  };

  const resetFilters = () => {
    setFilterForm(initialFilters);
    setAppliedFilters(initialFilters);
  };

  const selectProduct = (productCode: string) => {
    setDraftProductCode(null);
    setFormError(null);
    setNotice(null);
    setSaleConfirmOpen(false);
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
    if (outcome.result) setSaleConfirmOpen(false);
  };

  return (
    <section className="admin-inventory-layout">
      <section className="admin-panel admin-inventory-hero">
        <div className="admin-panel-header admin-product-header">
          <div>
            <p>재고·가격 상태 확인</p>
            <h2>재고와 가격을 각각 저장하고 판매 시작을 확인합니다</h2>
          </div>
          <button
            className="admin-secondary-button"
            disabled={inventory.loading}
            onClick={() => void inventory.reload()}
            type="button"
          >
            새로고침
          </button>
        </div>
        <div className="admin-excel-summary-grid">
          <article className="admin-excel-summary neutral">
            <span>현재 목록</span>
            <strong>{currentItems.length.toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary warning">
            <span>품절임박</span>
            <strong>{summary.lowStock.toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary review">
            <span>판매 시작 전</span>
            <strong>{summary.hidden.toLocaleString("ko-KR")}</strong>
          </article>
          <article className="admin-excel-summary neutral">
            <span>재고 정보 없음</span>
            <strong>{summary.unknown.toLocaleString("ko-KR")}</strong>
          </article>
        </div>
      </section>

      <section className="admin-panel admin-inventory-table-panel">
        <div className="admin-panel-header compact admin-inventory-filter-header">
          <div>
            <p>상품 목록</p>
            <h2>서버 상태 기준 조회</h2>
          </div>
          <div className="admin-inventory-filter-controls">
            <input
              aria-label="상품명 검색"
              onChange={(event) =>
                setFilterForm((current) => ({ ...current, query: event.target.value }))
              }
              placeholder="상품명 검색"
              value={filterForm.query}
            />
            <select
              aria-label="판매 상태 필터"
              onChange={(event) =>
                setFilterForm((current) => ({
                  ...current,
                  salesStatus: event.target.value as InventoryFilterForm["salesStatus"]
                }))
              }
              value={filterForm.salesStatus}
            >
              <option value="">전체 판매 상태</option>
              <option value="ON_SALE">판매중</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">판매 시작 전</option>
            </select>
            <select
              aria-label="재고 상태 필터"
              onChange={(event) =>
                setFilterForm((current) => ({
                  ...current,
                  stockStatus: event.target.value as InventoryFilterForm["stockStatus"]
                }))
              }
              value={filterForm.stockStatus}
            >
              <option value="">전체 재고 상태</option>
              <option value="IN_STOCK">재고 충분</option>
              <option value="LOW_STOCK">품절임박</option>
              <option value="SOLD_OUT">품절</option>
              <option value="HIDDEN">판매 시작 전</option>
            </select>
            <button className="admin-secondary-button" onClick={applyFilters} type="button">
              조회
            </button>
            <button className="admin-secondary-button" onClick={resetFilters} type="button">
              초기화
            </button>
          </div>
        </div>

        {inventory.error && (
          <p className="admin-inventory-error" role="alert">
            {inventory.error}
          </p>
        )}
        <div className="admin-table-wrap">
          <table className="admin-table admin-stock-table">
            <thead>
              <tr>
                <th scope="col">상품</th>
                <th scope="col">판매가</th>
                <th scope="col">재고 / 가용</th>
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
                      <strong className="admin-product-name">{item.name}</strong>
                      <small className="admin-product-code">
                        {item.brand} · {item.productCode}
                      </small>
                    </button>
                  </td>
                  <td>{formatCurrency(item.price)}</td>
                  <td>
                    {item.stockQuantity == null
                      ? "재고 정보 없음"
                      : `${item.stockQuantity.toLocaleString("ko-KR")} / ${(item.availability.availableQuantity ?? 0).toLocaleString("ko-KR")}`}
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
        {inventory.loading && (
          <p className="admin-inventory-loading">재고·가격 목록을 불러오는 중입니다.</p>
        )}
        {inventory.nextCursor && (
          <div className="admin-inventory-more">
            <button
              className="admin-secondary-button"
              disabled={inventory.loading}
              onClick={() => void inventory.loadMore()}
              type="button"
            >
              더 보기
            </button>
          </div>
        )}
      </section>

      <aside className="admin-panel admin-inventory-detail">
        {!selectedItem ? (
          <div className="admin-empty-state">목록에서 상품을 선택해 재고·가격을 관리하세요.</div>
        ) : (
          <>
            <div className="admin-panel-header compact">
              <div>
                <p>선택 상품</p>
                <h2>{selectedItem.brand}</h2>
              </div>
              <div className="admin-inventory-badges">
                {statusBadges(selectedItem).map((badge) => (
                  <span className={`admin-badge ${badge.tone}`} key={badge.label}>
                    {badge.label}
                  </span>
                ))}
              </div>
            </div>
            <dl className="admin-metric-list">
              <div>
                <dt>상품명</dt>
                <dd>{selectedItem.name}</dd>
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
                className="admin-secondary-button"
                disabled={actionPending}
                onClick={() => void savePrice()}
                type="button"
              >
                {inventory.pendingAction === "price" ? "가격 저장 중" : "가격 저장"}
              </button>
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
                <span>변경 사유 (1~500자)</span>
                <textarea
                  aria-label="재고 변경 사유"
                  disabled={actionPending || selectedItem.stockQuantity == null}
                  onChange={(event) => {
                    setDraftProductCode(selectedItem.productCode);
                    setReasonDraft(event.target.value);
                  }}
                  rows={3}
                  value={displayedReasonDraft}
                />
              </label>
              {selectedItem.stockQuantity == null ? (
                <p className="admin-inventory-help">
                  재고 행이 없는 상품은 재고를 수정할 수 없습니다.
                </p>
              ) : (
                <button
                  className="admin-secondary-button"
                  disabled={actionPending}
                  onClick={() => void saveStock()}
                  type="button"
                >
                  {inventory.pendingAction === "stock" ? "재고 저장 중" : "재고 저장"}
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
                  onClick={() => setSaleConfirmOpen(true)}
                  type="button"
                >
                  판매 시작
                </button>
              </section>
            )}

            <p className="admin-inventory-help">
              고객 노출을 중지하려면 상품 관리에서 숨김 처리하세요.
            </p>
            {(formError || inventory.actionError || notice) && (
              <p
                className={
                  formError || inventory.actionError
                    ? "admin-inventory-error"
                    : "admin-inventory-notice"
                }
                role="alert"
              >
                {formError ?? inventory.actionError ?? notice}
              </p>
            )}
          </>
        )}
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
                  <td>{movement.movementType}</td>
                  <td>
                    {movement.quantityDelta > 0 ? "+" : ""}
                    {movement.quantityDelta.toLocaleString("ko-KR")}
                  </td>
                  <td>{movement.stockAfter.toLocaleString("ko-KR")}</td>
                  <td>{movement.reason ?? "-"}</td>
                </tr>
              ))}
              {!inventory.loadingHistory && inventory.history.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={5}>
                    표시할 재고 이력이 없습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {saleConfirmOpen && selectedItem && (
        <div aria-modal="true" className="admin-inventory-confirm-backdrop" role="dialog">
          <section className="admin-inventory-confirm-dialog">
            <p>판매 시작 확인</p>
            <h2>{selectedItem.name} 판매를 시작할까요?</h2>
            <span>
              가격·가용 재고·브랜드·카테고리 상태를 서버에서 다시 확인한 뒤 고객에게 노출합니다.
            </span>
            <div>
              <button
                className="admin-secondary-button"
                disabled={actionPending}
                onClick={() => setSaleConfirmOpen(false)}
                type="button"
              >
                취소
              </button>
              <button
                className="admin-primary-button"
                disabled={actionPending}
                onClick={() => void confirmSaleStart()}
                type="button"
              >
                {inventory.pendingAction === "sale" ? "판매 시작 중" : "판매 시작"}
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
