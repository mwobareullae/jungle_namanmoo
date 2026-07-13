import { useRef, useState } from "react";

import ConfirmModal from "../../../components/ui/ConfirmModal";
import {
  AdminOrderAction,
  AdminOrderStatus,
  AdminOrderRow,
  AdminPaymentStatus,
  ORDER_STATUS_LABELS,
  PAYMENT_STATUS_LABELS
} from "../api/adminOrderApi";
import { AdminOrderPreviewPatch, ShipmentStep, useAdminOrders } from "./useAdminOrders";

// 관리자 주문·결제 상태 화면.
// 부모(AdminDashboardPage)와는 onOperationLog(공용 운영 로그)만 공유하고,
// 주문 데이터는 useAdminOrders 가 자체적으로 서버에서 조회한다.
// M4 재고/M5 대시보드가 쓰는 mock(orders, adminOrderMock.ts)과는 완전히 분리되어 서로 영향을 주지 않는다.
// 로그인/권한 확인은 AdminDashboardPage 가 페이지 진입 시점에 이미 게이트로 막으므로
// 이 컴포넌트는 항상 인증된 상태에서만 렌더링된다(자체 접근 확인 없음).
//
// 배송 액션(준비/시작/완료, M1.5-A)은 실 API로 연결되어 서버에 반영된다 — 버튼 표시 여부는
// 서버가 계산한 availableActions 를 그대로 따르고 프론트가 직접 계산하지 않는다.
// 결제 만료·취소 승인(M1.5-B)은 아직 팀원 API 계약 확정 전이라 로컬 미리보기로 남아있다.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type OrderPreviewAction = "expirePayment" | "approveCancel";
type OrderUiState = "idle" | "saved";

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
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
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

// 결제 만료·취소 승인 — 아직 팀원 API 계약 확정 전이라 로컬 미리보기로만 남아있는 액션(M1.5-B)
const ORDER_ACTION_CONFIG: Record<
  OrderPreviewAction,
  {
    requiredStatus: AdminOrderStatus;
    nextOrderStatus: AdminOrderStatus;
    nextPaymentStatus?: AdminPaymentStatus;
    clearsReservedQuantity?: boolean;
    issue: string;
    logTitle: string;
  }
> = {
  expirePayment: {
    requiredStatus: "PENDING_PAYMENT",
    nextOrderStatus: "EXPIRED",
    nextPaymentStatus: "FAILED",
    clearsReservedQuantity: true,
    issue: "결제 대기 만료 처리",
    logTitle: "결제 만료 처리"
  },
  approveCancel: {
    requiredStatus: "CANCEL_REQUESTED",
    nextOrderStatus: "CANCELED",
    nextPaymentStatus: "CANCELED",
    clearsReservedQuantity: true,
    issue: "취소 요청 승인",
    logTitle: "취소 승인"
  }
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

const PAYMENT_STATUS_OPTIONS = Object.keys(PAYMENT_STATUS_LABELS) as AdminPaymentStatus[];

export function AdminOrderStatusSection({ active, onOperationLog }: AdminOrderStatusSectionProps) {
  const {
    items,
    summary,
    hasMore,
    loading,
    loadingMore,
    error,
    orderStatusFilter,
    paymentStatusFilter,
    setOrderStatusFilter,
    setPaymentStatusFilter,
    resetFilters,
    refresh,
    loadMore,
    applyPreviewOverride,
    actionOrderId,
    actionError,
    syncWarning,
    runShipmentAction,
    clearShipmentActionFeedback
  } = useAdminOrders({ enabled: true }); // 이 컴포넌트가 마운트된 시점엔 이미 AdminDashboardPage 의 접근 게이트를 통과한 상태

  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [orderExceptions, setOrderExceptions] = useState<OrderExceptionRow[]>([]);
  const nextExceptionIdRef = useRef(0);
  const [orderRefreshState, setOrderRefreshState] = useState<OrderUiState>("idle");
  // 미리보기(결제만료/취소승인)와 배송 액션(실 서버 반영)은 결과가 다르므로 상태를 분리한다 —
  // 합쳐두면 미리보기를 눌러도 "서버에 실제로 반영됐습니다" 배너가 잘못 뜬다.
  const [previewActionState, setPreviewActionState] = useState<OrderUiState>("idle");
  const [shipmentActionState, setShipmentActionState] = useState<OrderUiState>("idle");
  const [confirmingAction, setConfirmingAction] = useState<PendingShipmentAction | null>(null);

  const selectedOrder = items.find((order) => order.id === selectedOrderId) ?? items[0] ?? null;
  const shipmentActionInProgress = actionOrderId !== null;
  const listRequestInProgress = loading || loadingMore;

  const handleOrderRefresh = async () => {
    if (shipmentActionInProgress) return;
    const succeeded = await refresh();
    if (!succeeded) {
      setOrderRefreshState("idle");
      onOperationLog("주문", "주문 상태 새로고침 실패", "잠시 후 다시 시도해 주세요.", "danger");
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
    setOrderRefreshState("saved");
    setPreviewActionState("idle");
    setShipmentActionState("idle");
    setConfirmingAction(null);
    clearShipmentActionFeedback();
    onOperationLog("주문", "주문 상태 새로고침", selectedOrder?.orderCode ?? "-", "success");
  };

  // 주문 선택·필터 변경 시, 이전 주문에 대한 확인 대기·에러·동기화 경고가 새 화면에
  // 그대로 남아있지 않도록 배송 액션 관련 상태를 전부 초기화한다.
  const resetShipmentActionUiState = () => {
    setShipmentActionState("idle");
    setConfirmingAction(null);
    clearShipmentActionFeedback();
  };

  const handleSelectOrder = (orderId: string) => {
    setSelectedOrderId(orderId);
    setOrderRefreshState("idle");
    setPreviewActionState("idle");
    resetShipmentActionUiState();
  };

  const handleOrderFilterReset = () => {
    if (shipmentActionInProgress) return;
    resetFilters();
    setOrderRefreshState("idle");
    setPreviewActionState("idle");
    resetShipmentActionUiState();
    onOperationLog("주문", "필터 초기화", "전체 주문 목록 표시", "neutral");
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

  const handlePreviewAction = (action: OrderPreviewAction) => {
    if (!selectedOrder) return;
    const config = ORDER_ACTION_CONFIG[action];
    const previousStatusLabel = selectedOrder.status;

    const patch: AdminOrderPreviewPatch = {
      status: ORDER_STATUS_LABELS[config.nextOrderStatus],
      orderStatusRaw: config.nextOrderStatus,
      updatedAt: `로컬 처리 ${formatCurrentTime()}`
    };
    if (config.nextPaymentStatus) {
      patch.paymentStatus = PAYMENT_STATUS_LABELS[config.nextPaymentStatus];
      patch.paymentStatusRaw = config.nextPaymentStatus;
      patch.paymentMissing = false;
    }
    if (config.clearsReservedQuantity) {
      patch.stockReserved = 0;
    }
    applyPreviewOverride(selectedOrder.id, patch);

    setOrderExceptions((current) => [
      {
        id: ++nextExceptionIdRef.current,
        time: formatCurrentTime(),
        orderCode: selectedOrder.orderCode,
        issue: config.issue,
        action: `${previousStatusLabel} → ${ORDER_STATUS_LABELS[config.nextOrderStatus]}`
      },
      ...current
    ]);
    setOrderRefreshState("idle");
    setPreviewActionState("saved");
    onOperationLog("주문", config.logTitle, selectedOrder.orderCode, action === "approveCancel" ? "danger" : "success");
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
      setShipmentActionState("idle");
      onOperationLog("주문", `${config.logTitle} 실패`, "잠시 후 다시 시도해 주세요.", "danger");
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
    setOrderRefreshState("idle");
    setShipmentActionState("saved");
    onOperationLog("주문", config.logTitle, orderCode, "success");
  };

  const summaryCards = summary
    ? [
        { label: "결제 대기", value: summary.pendingPaymentCount.toLocaleString("ko-KR"), tone: "warning" as const },
        { label: "배송 준비", value: summary.preparingShipmentCount.toLocaleString("ko-KR"), tone: "success" as const },
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
                <h2>주문 흐름, 결제 상태, 예약 재고를 한 화면에서 확인</h2>
              </div>
              <div className="admin-filter-row">
                <button
                  className="admin-secondary-button"
                  onClick={() => onOperationLog("주문", "상태 이력 확인", "선택 주문의 상태 흐름을 확인", "neutral")}
                  type="button"
                >
                  상태 이력
                </button>
                <button
                  className="admin-primary-button"
                  disabled={listRequestInProgress || shipmentActionInProgress}
                  onClick={handleOrderRefresh}
                  type="button"
                >
                  새로고침
                </button>
              </div>
            </div>
            {summary ? (
              <div className="admin-excel-summary-grid">
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
                  <optgroup label="반품·환불·교환">
                    <option value="RETURN_REQUESTED">{ORDER_STATUS_LABELS.RETURN_REQUESTED}</option>
                    <option value="RETURNED">{ORDER_STATUS_LABELS.RETURNED}</option>
                    <option value="REFUND_REQUESTED">{ORDER_STATUS_LABELS.REFUND_REQUESTED}</option>
                    <option value="REFUNDED">{ORDER_STATUS_LABELS.REFUNDED}</option>
                    <option value="EXCHANGE_REQUESTED">{ORDER_STATUS_LABELS.EXCHANGE_REQUESTED}</option>
                    <option value="EXCHANGED">{ORDER_STATUS_LABELS.EXCHANGED}</option>
                  </optgroup>
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
                  {PAYMENT_STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {PAYMENT_STATUS_LABELS[status]}
                    </option>
                  ))}
                </select>
                <button
                  className="admin-secondary-button"
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
            <div className="admin-table-wrap">
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
                        <strong className="admin-product-name">{order.orderCode}</strong>
                        <small className="admin-product-code">
                          {order.customer} · {order.updatedAt}
                        </small>
                      </td>
                      <td>
                        <strong>{order.productSummary}</strong>
                        <small className="admin-product-code">{order.itemCount}개 상품</small>
                      </td>
                      <td>{formatCurrency(order.totalAmount)}</td>
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
                      <td className="admin-file-name">{order.recommendationId}</td>
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
            {hasMore && (
              <button
                className="admin-secondary-button"
                disabled={listRequestInProgress || shipmentActionInProgress}
                onClick={loadMore}
                type="button"
              >
                {loadingMore ? "불러오는 중..." : "더 보기"}
              </button>
            )}
          </section>

          <aside className="admin-panel admin-order-detail">
            <div className="admin-panel-header compact">
              <div>
                <p>선택 주문</p>
                <h2>{selectedOrder ? selectedOrder.orderCode : "선택된 주문 없음"}</h2>
              </div>
              {selectedOrder && (
                <span className={`admin-badge ${ORDER_STATUS_TONE[selectedOrder.orderStatusRaw]}`}>
                  {selectedOrder.status}
                </span>
              )}
            </div>
            {selectedOrder ? (
              <>
                <dl className="admin-metric-list">
                  <div>
                    <dt>고객</dt>
                    <dd>{selectedOrder.customer}</dd>
                  </div>
                  <div>
                    <dt>상품</dt>
                    <dd>{selectedOrder.productSummary}</dd>
                  </div>
                  <div>
                    <dt>결제 상태</dt>
                    <dd>{selectedOrder.paymentStatus}</dd>
                  </div>
                  <div>
                    <dt>결제일</dt>
                    <dd>{selectedOrder.paidAt ?? "결제 미완료"}</dd>
                  </div>
                  <div>
                    <dt>배송 시작일</dt>
                    <dd>{selectedOrder.shippedAt ?? "배송 시작 전"}</dd>
                  </div>
                  <div>
                    <dt>배송완료일</dt>
                    <dd>{selectedOrder.deliveredAt ?? "배송완료 전"}</dd>
                  </div>
                  <div>
                    <dt>추천 ID</dt>
                    <dd>{selectedOrder.recommendationId}</dd>
                  </div>
                </dl>
                <div className={`admin-state-banner ${orderRefreshState === "saved" ? "success" : "neutral"}`}>
                  <strong>{orderRefreshState === "saved" ? "상태 동기화 완료" : "동기화 전"}</strong>
                  <span>
                    {orderRefreshState === "saved"
                      ? "선택 주문의 최신 상태 확인 기록을 예외 목록에 남겼습니다."
                      : "새로고침을 누르면 결제/재고 상태 확인 기록이 남습니다."}
                  </span>
                </div>

                {/* 배송 액션: 서버가 계산한 availableActions 기준으로만 버튼 표시 — 프론트는 직접 계산하지 않는다 */}
                {actionError && (
                  <div className="admin-state-banner danger">
                    <strong>배송 상태 변경 실패</strong>
                    <span>{actionError}</span>
                  </div>
                )}
                {syncWarning && (
                  <div className="admin-state-banner warning">
                    <strong>목록 동기화 필요</strong>
                    <span>{syncWarning}</span>
                  </div>
                )}
                {shipmentActionState === "saved" && (
                  <div className="admin-state-banner success">
                    <strong>배송 상태 반영 완료</strong>
                    <span>서버에 실제로 반영됐고, 새로고침해도 유지됩니다.</span>
                  </div>
                )}
                {/* 결제 만료·취소 승인: 팀원 API 계약 확정 전 로컬 미리보기(M1.5-B) */}
                <div className={`admin-state-banner ${previewActionState === "saved" ? "success" : "review"}`}>
                  <strong>운영 액션 미리보기</strong>
                  <span>결제 만료·취소 승인은 팀원 API 계약 확정 전이라 화면에서만 갱신되고 서버 데이터는 바뀌지 않습니다.</span>
                </div>
                <div className="admin-order-action-grid" aria-label="주문 운영 액션">
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.expirePayment.requiredStatus}
                    onClick={() => handlePreviewAction("expirePayment")}
                    type="button"
                  >
                    결제 만료
                  </button>
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.approveCancel.requiredStatus}
                    onClick={() => handlePreviewAction("approveCancel")}
                    type="button"
                  >
                    취소 승인
                  </button>
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
              </>
            ) : (
              <div className="admin-state-banner neutral">
                <strong>선택된 주문 없음</strong>
                <span>표에서 주문을 선택하면 상세 정보가 표시됩니다.</span>
              </div>
            )}
          </aside>

          <section className="admin-panel">
            <div className="admin-panel-header compact">
              <div>
                <p>확인 필요</p>
                <h2>결제·재고 예외</h2>
              </div>
              <span className="admin-badge warning">운영 확인</span>
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
