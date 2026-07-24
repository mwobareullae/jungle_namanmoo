import { useEffect, useRef, useState } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import {
  AdminOrderAction,
  AdminOrderStatus,
  AdminOrderRow,
  AdminPaymentStatus,
  ORDER_STATUS_LABELS,
  PAYMENT_STATUS_LABELS
} from "../api/adminOrderApi";
import { ShipmentStep, useAdminOrders } from "./useAdminOrders";

// 관리자 주문·결제 상태 화면.
// 배송 액션 성공·실패는 배너·토스트 없이 하단 "결제·재고 예외" 표와 액션 버튼 옆 인라인
// 문구로만 안내한다 — 부모(AdminDashboardPage)의 공용 운영 로그(onOperationLog)는 쓰지 않는다.
// 주문 데이터는 useAdminOrders 가 자체적으로 서버에서 조회한다.
// M4 재고/M5 대시보드가 쓰는 mock(orders, adminOrderMock.ts)과는 완전히 분리되어 서로 영향을 주지 않는다.
// 로그인/권한 확인은 AdminDashboardPage 가 페이지 진입 시점에 이미 게이트로 막으므로
// 이 컴포넌트는 항상 인증된 상태에서만 렌더링된다(자체 접근 확인 없음).
//
// 배송 액션(준비/시작/완료, M1.5-A)은 실 API로 연결되어 서버에 반영된다 — 버튼 표시 여부는
// 서버가 계산한 availableActions 를 그대로 따르고 프론트가 직접 계산하지 않는다.
// 결제 만료(M1.5-B)는 관리자 수동 버튼이 아니라 payment-expiry-scheduler 컨테이너가 주기적으로
// PENDING_PAYMENT 중 payment_expires_at 이 지난 주문을 자동 처리한다(2026-07-14, docker-compose.yml
// 참고) — 만료는 시간 기준이라 관리자가 개별로 트리거할 이유가 없어 로컬 미리보기 버튼은 제거했다.
// 취소 승인·거절은 사이드바의 "취소·클레임 관리" 화면에서 실 API로 처리한다(M1.5-B 2단계) —
// 이 화면의 로컬 미리보기 버튼은 역할이 중복돼 제거했다.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

type OrderExceptionRow = {
  id: number; // time(분 단위)+orderCode 조합만으로는 같은 주문에 1분 내 여러 액션 시 key 충돌
  time: string;
  orderCode: string;
  issue: string;
  action: string;
};

// 확인 대기 중인 배송 액션의 대상을 액션 종류와 함께 통째로 고정해둔다 — 확인 대기 중에
// 필터·선택이 바뀌어도, 확인을 누르면 처음 누른 그 주문에만 실행되게 하기 위함이다.
type PendingShipmentAction = {
  action: AdminOrderAction;
  orderId: string;
  orderCode: string;
  statusLabelBefore: string;
};

type AdminOrderStatusSectionProps = {
  active: boolean;
};

const ORDER_STATUS_TONE: Record<AdminOrderStatus, BadgeTone> = {
  PENDING_PAYMENT: "warning",
  PAID: "success",
  PAYMENT_FAILED: "danger",
  EXPIRED: "danger",
  PREPARING_SHIPMENT: "success",
  SHIPPED: "success",
  DELIVERED: "success",
  CANCEL_REQUESTED: "review",
  CANCELED: "danger",
  RETURN_REQUESTED: "review",
  RETURNED: "neutral",
  REFUND_REQUESTED: "review",
  REFUNDED: "neutral",
  EXCHANGE_REQUESTED: "review",
  EXCHANGED: "neutral"
};

const PAYMENT_STATUS_TONE: Record<AdminPaymentStatus, BadgeTone> = {
  READY: "warning",
  CONFIRMING: "warning",
  UNKNOWN: "review",
  APPROVED: "success",
  FAILED: "danger",
  CANCELED: "danger",
  EXPIRED: "danger",
  REFUND_REQUESTED: "review",
  REFUNDED: "neutral",
  PARTIALLY_REFUNDED: "neutral"
};

// 배송 액션(준비/시작/완료) — 서버가 계산한 available_actions 값을 그대로 키로 쓴다(M1.5-A).
// confirmMessage 가 있으면 버튼을 바로 실행하지 않고 ConfirmModal 로 먼저 확인받는다
// (팀원 스펙: 배송중·배송완료 전환 전 확인 필요, 배송 준비 시작은 확인 불필요).
const SHIPMENT_ACTION_CONFIG: Record<
  AdminOrderAction,
  { step: ShipmentStep; label: string; logTitle: string; confirmMessage: string | null }
> = {
  START_PREPARATION: {
    step: "prepare",
    label: "배송 준비 시작",
    logTitle: "배송 준비 처리",
    confirmMessage: null
  },
  START_SHIPMENT: {
    step: "dispatch",
    label: "배송 시작",
    logTitle: "배송 시작 처리",
    confirmMessage: "배송을 시작하면 준비 상태로 되돌릴 수 없습니다. 배송을 시작할까요?"
  },
  COMPLETE_DELIVERY: {
    step: "deliver",
    label: "배송완료 처리",
    logTitle: "배송완료 처리",
    confirmMessage: "배송완료로 처리하면 되돌릴 수 없습니다. 배송완료로 처리할까요?"
  }
};

function formatCurrency(value: number) {
  return `${value.toLocaleString("ko-KR")}원`;
}

function formatCurrentTime() {
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date());
}

const PAYMENT_STATUS_GROUPS: Array<{ label: string; statuses: AdminPaymentStatus[] }> = [
  {
    label: "결제 진행",
    statuses: ["READY", "CONFIRMING", "UNKNOWN"]
  },
  {
    label: "결제 결과",
    statuses: ["APPROVED", "FAILED", "CANCELED", "EXPIRED"]
  },
  {
    label: "환불",
    statuses: ["REFUND_REQUESTED", "REFUNDED", "PARTIALLY_REFUNDED"]
  }
];

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// 재고/가격 확인과 같은 네이버식 블록 페이지네이션(10개씩 묶어서 이동).
const PAGE_BLOCK_SIZE = 10;

const getBlockPages = (current: number, total: number): number[] => {
  const blockIndex = Math.floor((current - 1) / PAGE_BLOCK_SIZE);
  const start = blockIndex * PAGE_BLOCK_SIZE + 1;
  const end = Math.min(start + PAGE_BLOCK_SIZE - 1, total);
  const pages: number[] = [];
  for (let page = start; page <= end; page += 1) pages.push(page);
  return pages;
};

export function AdminOrderStatusSection({ active }: AdminOrderStatusSectionProps) {
  const {
    items,
    summary,
    pagination,
    loading,
    error,
    page,
    pageSize,
    orderStatusFilter,
    paymentStatusFilter,
    setOrderStatusFilter,
    setPaymentStatusFilter,
    setPageSize,
    resetFilters,
    refresh,
    goToPage,
    actionOrderId,
    actionError,
    syncWarning,
    runShipmentAction,
    clearShipmentActionFeedback
  } = useAdminOrders({ enabled: active }); // 주문 화면이 열려 있을 때만 최초 조회·자동 동기화를 실행한다.

  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [orderExceptions, setOrderExceptions] = useState<OrderExceptionRow[]>([]);
  const nextExceptionIdRef = useRef(0);
  const [confirmingAction, setConfirmingAction] = useState<PendingShipmentAction | null>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    tableScrollRef.current?.scrollTo({ top: 0 });
  }, [page]);

  // 직접 선택하기 전까지는 아무 주문도 자동으로 보여주지 않는다. 이미 선택한 주문이 있는데
  // (예: 30초 자동 새로고침으로 목록이 갱신되며) 그 주문이 현재 items 에서 사라졌다면,
  // items[0] 등 다른 주문으로 조용히 바꿔치기하지 않는다 — 그렇게 하면 관리자가 여전히
  // 원래 주문을 보고 있다고 착각한 채 배송 액션 버튼을 눌러 엉뚱한 주문에 실행될 수 있다.
  const selectedOrder = selectedOrderId === null ? null : items.find((order) => order.id === selectedOrderId) ?? null;
  const selectedOrderMissing = selectedOrderId !== null && selectedOrder === null && items.length > 0;
  const shipmentActionInProgress = actionOrderId !== null;
  const listRequestInProgress = loading;
  const totalPages = pagination?.totalPages ?? 1;
  const blockPages = getBlockPages(page, totalPages);
  const blockStart = blockPages[0] ?? 1;
  const blockEnd = blockPages[blockPages.length - 1] ?? 1;
  const hasPrevBlock = blockStart > 1;
  const hasNextBlock = blockEnd < totalPages;

  const handleOrderRefresh = async () => {
    if (shipmentActionInProgress) return;
    const outcome = await refresh();
    if (outcome === "stale") return; // 이후 요청이 대신 처리 중 — 실패가 아니므로 조용히 넘어간다.
    if (outcome === "error") {
      setOrderExceptions((current) => [
        {
          id: ++nextExceptionIdRef.current,
          time: formatCurrentTime(),
          orderCode: selectedOrder?.orderCode ?? "-",
          issue: "새로고침 실패",
          action: "잠시 후 다시 시도해 주세요."
        },
        ...current
      ]);
      return;
    }
    if (selectedOrder) {
      setOrderExceptions((current) => [
        {
          id: ++nextExceptionIdRef.current,
          time: formatCurrentTime(),
          orderCode: selectedOrder.orderCode,
          issue: "상태 동기화 완료",
          action: `${selectedOrder.status} / ${selectedOrder.paymentStatus}`
        },
        ...current
      ]);
    }
    setConfirmingAction(null);
    clearShipmentActionFeedback();
  };

  // 주문 선택·필터 변경 시, 이전 주문에 대한 확인 대기·에러·동기화 경고가 새 화면에
  // 그대로 남아있지 않도록 배송 액션 관련 상태를 전부 초기화한다.
  const resetShipmentActionUiState = () => {
    setConfirmingAction(null);
    clearShipmentActionFeedback();
  };

  const handleSelectOrder = (orderId: string) => {
    setSelectedOrderId(orderId);
    resetShipmentActionUiState();
  };

  const handleOrderFilterReset = () => {
    if (shipmentActionInProgress) return;
    resetFilters();
    resetShipmentActionUiState();
  };

  const handleOrderStatusFilterChange = (value: AdminOrderStatus | null) => {
    if (shipmentActionInProgress) return;
    setOrderStatusFilter(value);
    resetShipmentActionUiState();
  };

  const handlePaymentStatusFilterChange = (value: AdminPaymentStatus | null) => {
    if (shipmentActionInProgress) return;
    setPaymentStatusFilter(value);
    resetShipmentActionUiState();
  };

  // 배송 준비 시작 버튼 클릭: 확인 불필요라 바로 실행.
  // 배송 시작·배송완료 처리 버튼 클릭: confirmMessage 가 있으니 ConfirmModal 부터 띄운다.
  // 클릭 시점의 order 를 그대로 캡처해두므로, 확인 대기 중 선택·필터가 바뀌어도
  // 실제 실행은 항상 처음 누른 그 주문에 적용된다.
  const handleShipmentButtonClick = (action: AdminOrderAction, order: AdminOrderRow) => {
    if (shipmentActionInProgress || listRequestInProgress) return;
    if (SHIPMENT_ACTION_CONFIG[action].confirmMessage) {
      setConfirmingAction({ action, orderId: order.id, orderCode: order.orderCode, statusLabelBefore: order.status });
      return;
    }
    void executeShipmentAction(action, order.id, order.orderCode, order.status);
  };

  const executeShipmentAction = async (
    action: AdminOrderAction,
    orderId: string,
    orderCode: string,
    previousStatusLabel: string
  ) => {
    const config = SHIPMENT_ACTION_CONFIG[action];
    const succeeded = await runShipmentAction(orderId, orderCode, config.step);
    setConfirmingAction(null);
    if (!succeeded) {
      setOrderExceptions((current) => [
        {
          id: ++nextExceptionIdRef.current,
          time: formatCurrentTime(),
          orderCode,
          issue: `${config.logTitle} 실패`,
          action: "잠시 후 다시 시도해 주세요."
        },
        ...current
      ]);
      return;
    }

    setOrderExceptions((current) => [
      {
        id: ++nextExceptionIdRef.current,
        time: formatCurrentTime(),
        orderCode,
        issue: config.logTitle,
        action: `${previousStatusLabel} → 처리 완료`
      },
      ...current
    ]);
  };

  const summaryCards = summary
    ? [
        { label: "결제 대기", value: summary.pendingPaymentCount.toLocaleString("ko-KR"), tone: "warning" as const },
        { label: "배송 준비", value: summary.preparingShipmentCount.toLocaleString("ko-KR"), tone: "success" as const },
        { label: "배송 중", value: summary.shippedCount.toLocaleString("ko-KR"), tone: "success" as const },
        { label: "취소 요청", value: summary.cancelRequestedCount.toLocaleString("ko-KR"), tone: "danger" as const },
        { label: "재고 예약", value: summary.reservedQuantityTotal.toLocaleString("ko-KR"), tone: "neutral" as const }
      ]
    : [];

  return (
    <section className="admin-order-layout" hidden={!active}>
      <section className="admin-panel admin-order-hero">
            <div className="admin-panel-header admin-product-header">
              <div>
                <p>주문·결제 상태 확인</p>
                <h2>주문·결제·재고 현황</h2>
              </div>
              <div className="admin-filter-row">
                <button
                  className="admin-secondary-button admin-light-button"
                  disabled={listRequestInProgress || shipmentActionInProgress}
                  onClick={handleOrderRefresh}
                  type="button"
                >
                  새로고침
                </button>
              </div>
            </div>
            {summary ? (
              <div className="admin-excel-summary-grid admin-order-summary-grid">
                {summaryCards.map((item) => (
                  <article className={`admin-excel-summary ${item.tone}`} key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </article>
                ))}
              </div>
            ) : (
              <div className="admin-state-banner neutral">
                <strong>{loading ? "요약 정보를 불러오는 중입니다" : "요약 정보 없음"}</strong>
                <span>{error ?? "잠시 후 다시 시도해 주세요."}</span>
              </div>
            )}
          </section>

          <section className="admin-panel admin-order-table-panel">
            <div className="admin-panel-header compact">
              <div>
                <p>최근 주문</p>
                <h2>상태 확인 목록</h2>
              </div>
              <div className="admin-filter-row">
                <select
                  aria-label="주문 상태 필터"
                  disabled={shipmentActionInProgress}
                  onChange={(event) =>
                    handleOrderStatusFilterChange(
                      event.target.value === "" ? null : (event.target.value as AdminOrderStatus)
                    )
                  }
                  value={orderStatusFilter ?? ""}
                >
                  <option value="">주문 전체</option>
                  <optgroup label="결제">
                    <option value="PENDING_PAYMENT">{ORDER_STATUS_LABELS.PENDING_PAYMENT}</option>
                    <option value="PAID">{ORDER_STATUS_LABELS.PAID}</option>
                    <option value="PAYMENT_FAILED">{ORDER_STATUS_LABELS.PAYMENT_FAILED}</option>
                    <option value="EXPIRED">{ORDER_STATUS_LABELS.EXPIRED}</option>
                  </optgroup>
                  <optgroup label="배송">
                    <option value="PREPARING_SHIPMENT">{ORDER_STATUS_LABELS.PREPARING_SHIPMENT}</option>
                    <option value="SHIPPED">{ORDER_STATUS_LABELS.SHIPPED}</option>
                    <option value="DELIVERED">{ORDER_STATUS_LABELS.DELIVERED}</option>
                  </optgroup>
                  <optgroup label="취소">
                    <option value="CANCEL_REQUESTED">{ORDER_STATUS_LABELS.CANCEL_REQUESTED}</option>
                    <option value="CANCELED">{ORDER_STATUS_LABELS.CANCELED}</option>
                  </optgroup>
                  {/* 반품·환불·교환 상태(RETURN_REQUESTED 등)는 Order.status 로 전환되지 않고 OrderClaim
                      으로만 관리돼(案A 확정) 필터에 넣어도 항상 0건이라 제외했다 — 취소·클레임 관리 화면 참조 */}
                </select>
                <select
                  aria-label="결제 상태 필터"
                  disabled={shipmentActionInProgress}
                  onChange={(event) =>
                    handlePaymentStatusFilterChange(
                      event.target.value === "" ? null : (event.target.value as AdminPaymentStatus)
                    )
                  }
                  value={paymentStatusFilter ?? ""}
                >
                  <option value="">결제 전체</option>
                  {PAYMENT_STATUS_GROUPS.map((group) => (
                    <optgroup key={group.label} label={group.label}>
                      {group.statuses.map((status) => (
                        <option key={status} value={status}>
                          {PAYMENT_STATUS_LABELS[status]}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <button
                  className="admin-secondary-button admin-light-button"
                  disabled={shipmentActionInProgress}
                  onClick={handleOrderFilterReset}
                  type="button"
                >
                  초기화
                </button>
              </div>
            </div>
            {error && (
              <div className="admin-state-banner danger">
                <strong>주문 목록을 불러오지 못했습니다</strong>
                <span>{error}</span>
              </div>
            )}
            <div className="admin-list-toolbar">
              <div className="admin-page-size">
                <label htmlFor="admin-order-page-size">페이지당</label>
                <select
                  id="admin-order-page-size"
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
            <div className="admin-table-wrap admin-order-table-scroll" ref={tableScrollRef}>
              <table className="admin-table admin-order-table">
                <thead>
                  <tr>
                    <th scope="col">주문</th>
                    <th scope="col">상품</th>
                    <th scope="col">금액</th>
                    <th scope="col">주문 상태</th>
                    <th scope="col">결제</th>
                    <th scope="col">예약</th>
                    <th scope="col">추천 추적</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((order) => (
                    <tr
                      className={selectedOrder && order.id === selectedOrder.id ? "selected" : undefined}
                      key={order.id}
                      onClick={() => handleSelectOrder(order.id)}
                    >
                      <td>
                        <strong className="admin-product-name" title={order.orderCode}>
                          {order.orderCode}
                        </strong>
                        <small className="admin-product-code" title={`${order.customer} · 주문 ${order.orderedAt}`}>
                          {order.customer} · 주문 {order.orderedAt}
                        </small>
                      </td>
                      <td>
                        <strong className="admin-product-name" title={order.productSummary}>
                          {order.productSummary}
                        </strong>
                        <small className="admin-product-code">{order.itemCount}개 상품</small>
                      </td>
                      <td className="admin-order-amount">{formatCurrency(order.totalAmount)}</td>
                      <td>
                        <span className={`admin-badge ${ORDER_STATUS_TONE[order.orderStatusRaw]}`}>{order.status}</span>
                      </td>
                      <td>
                        <span
                          className={`admin-badge ${
                            order.paymentStatusRaw ? PAYMENT_STATUS_TONE[order.paymentStatusRaw] : "danger"
                          }`}
                        >
                          {order.paymentStatus}
                        </span>
                      </td>
                      <td>{order.stockReserved}개</td>
                      <td className="admin-file-name" title={order.recommendationId}>
                        {order.recommendationId}
                      </td>
                    </tr>
                  ))}
                  {loading && items.length === 0 && (
                    <tr>
                      <td className="admin-empty-row" colSpan={7}>
                        주문을 불러오는 중입니다...
                      </td>
                    </tr>
                  )}
                  {!loading && items.length === 0 && (
                    <tr>
                      <td className="admin-empty-row" colSpan={7}>
                        {error
                          ? "주문 목록을 불러오지 못했습니다. 다시 시도해 주세요."
                          : "조건에 맞는 주문이 없습니다. 필터를 초기화해 주세요."}
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
                  disabled={page <= 1 || listRequestInProgress}
                  onClick={() => goToPage(1)}
                  type="button"
                >
                  처음
                </button>
                <button
                  className="admin-pagination-jump"
                  disabled={!hasPrevBlock || listRequestInProgress}
                  onClick={() => goToPage(blockStart - 1)}
                  type="button"
                >
                  이전
                </button>
                {blockPages.map((entry) => (
                  <button
                    className={`admin-pagination-page${entry === page ? " active" : ""}`}
                    disabled={listRequestInProgress}
                    key={entry}
                    onClick={() => goToPage(entry)}
                    type="button"
                  >
                    {entry}
                  </button>
                ))}
                <button
                  className="admin-pagination-jump"
                  disabled={!hasNextBlock || listRequestInProgress}
                  onClick={() => goToPage(blockEnd + 1)}
                  type="button"
                >
                  다음
                </button>
                <button
                  className="admin-pagination-jump"
                  disabled={page >= totalPages || listRequestInProgress}
                  onClick={() => goToPage(totalPages)}
                  type="button"
                >
                  맨끝
                </button>
              </div>
            </div>
          </section>

          <aside className="admin-panel admin-order-detail">
            <div className="admin-panel-header compact">
              <div>
                <p>선택 주문</p>
                <h2>{selectedOrder ? selectedOrder.orderCode : "상세 정보"}</h2>
              </div>
              {selectedOrder && (
                <span className={`admin-badge ${ORDER_STATUS_TONE[selectedOrder.orderStatusRaw]}`}>
                  {selectedOrder.status}
                </span>
              )}
            </div>
            <div className="admin-order-detail-scroll">
              {selectedOrderMissing && (
                <div className="admin-state-banner neutral">
                  <strong>선택한 주문을 찾을 수 없음</strong>
                  <span>목록이 갱신되며 선택했던 주문이 현재 페이지에 보이지 않습니다. 표에서 다시 선택해 주세요.</span>
                </div>
              )}
              {!selectedOrder ? (
                <div className="admin-detail-body">
                  <p className="admin-metric-group-title">기본 정보</p>
                  <dl className="admin-metric-list">
                    <div>
                      <dt>고객</dt>
                      <dd>-</dd>
                    </div>
                    <div>
                      <dt>상품</dt>
                      <dd>-</dd>
                    </div>
                  </dl>

                  <p className="admin-metric-group-title">결제 정보</p>
                  <dl className="admin-metric-list">
                    <div>
                      <dt>결제 상태</dt>
                      <dd>-</dd>
                    </div>
                    <div>
                      <dt>결제일</dt>
                      <dd>-</dd>
                    </div>
                  </dl>

                  <p className="admin-metric-group-title">배송 정보</p>
                  <dl className="admin-metric-list">
                    <div>
                      <dt>배송 시작일</dt>
                      <dd>-</dd>
                    </div>
                    <div>
                      <dt>배송완료일</dt>
                      <dd>-</dd>
                    </div>
                  </dl>

                  <p className="admin-metric-group-title">추천 정보</p>
                  <dl className="admin-metric-list">
                    <div>
                      <dt>추천 ID</dt>
                      <dd>-</dd>
                    </div>
                  </dl>
                </div>
              ) : (
                <>
                  <div className="admin-detail-body">
                    <p className="admin-metric-group-title">기본 정보</p>
                    <dl className="admin-metric-list">
                      <div>
                        <dt>고객</dt>
                        <dd>{selectedOrder.customer}</dd>
                      </div>
                      <div>
                        <dt>상품</dt>
                        <dd>{selectedOrder.productSummary}</dd>
                      </div>
                    </dl>

                    <p className="admin-metric-group-title">결제 정보</p>
                    <dl className="admin-metric-list">
                      <div>
                        <dt>결제 상태</dt>
                        <dd>{selectedOrder.paymentStatus}</dd>
                      </div>
                      <div>
                        <dt>결제일</dt>
                        <dd>{selectedOrder.paidAt ?? "결제 미완료"}</dd>
                      </div>
                    </dl>

                    <p className="admin-metric-group-title">배송 정보</p>
                    <dl className="admin-metric-list">
                      <div>
                        <dt>배송 시작일</dt>
                        <dd>{selectedOrder.shippedAt ?? "배송 시작 전"}</dd>
                      </div>
                      <div>
                        <dt>배송완료일</dt>
                        <dd>{selectedOrder.deliveredAt ?? "배송완료 전"}</dd>
                      </div>
                    </dl>

                    <p className="admin-metric-group-title">추천 정보</p>
                    <dl className="admin-metric-list">
                      <div>
                        <dt>추천 ID</dt>
                        <dd>{selectedOrder.recommendationId}</dd>
                      </div>
                    </dl>
                  </div>

                  {/* 배송 액션: 서버가 계산한 availableActions 기준으로만 버튼 표시 — 프론트는 직접 계산하지 않는다.
                      실패·동기화 경고는 배너·토스트 대신 버튼 옆 짧은 문구로만 안내한다(하단 예외 표에도 기록됨). */}
                  {actionError && <p className="admin-inline-message danger">{actionError}</p>}
                  {syncWarning && <p className="admin-inline-message warning">{syncWarning}</p>}
                  <div className="admin-order-action-grid" aria-label="주문 운영 액션">
                    {selectedOrder.availableActions.map((action) => (
                      <button
                        className="admin-primary-button admin-order-shipment-button"
                        disabled={shipmentActionInProgress || listRequestInProgress}
                        key={action}
                        onClick={() => handleShipmentButtonClick(action, selectedOrder)}
                        type="button"
                      >
                        {actionOrderId === selectedOrder.id ? "처리 중..." : SHIPMENT_ACTION_CONFIG[action].label}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <ConfirmModal
              cancelLabel="취소"
              confirmLabel={shipmentActionInProgress ? "처리 중..." : listRequestInProgress ? "목록 조회 중..." : "확인"}
              message={confirmingAction ? SHIPMENT_ACTION_CONFIG[confirmingAction.action].confirmMessage ?? "" : ""}
              onCancel={() => {
                if (shipmentActionInProgress) return; // 처리 중에는 닫지 않음
                setConfirmingAction(null);
              }}
              onConfirm={() => {
                if (!confirmingAction || shipmentActionInProgress || listRequestInProgress) return;
                void executeShipmentAction(
                  confirmingAction.action,
                  confirmingAction.orderId,
                  confirmingAction.orderCode,
                  confirmingAction.statusLabelBefore
                );
              }}
              open={confirmingAction !== null}
              title={confirmingAction ? SHIPMENT_ACTION_CONFIG[confirmingAction.action].label : undefined}
            />
          </aside>

          <section className="admin-panel admin-order-exception-panel">
            <div className="admin-panel-header compact">
              <div>
                <p>확인 필요</p>
                <h2>결제·재고 예외</h2>
              </div>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table compact admin-order-exception-table">
                <thead>
                  <tr>
                    <th scope="col">시간</th>
                    <th scope="col">주문</th>
                    <th scope="col">이슈</th>
                    <th scope="col">조치</th>
                  </tr>
                </thead>
                <tbody>
                  {orderExceptions.map((row) => (
                    <tr key={row.id}>
                      <td>{row.time}</td>
                      <td className="admin-file-name">{row.orderCode}</td>
                      <td>{row.issue}</td>
                      <td>{row.action}</td>
                    </tr>
                  ))}
                  {orderExceptions.length === 0 && (
                    <tr>
                      <td className="admin-empty-row" colSpan={4}>
                        아직 기록된 예외가 없습니다.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
    </section>
  );
}
