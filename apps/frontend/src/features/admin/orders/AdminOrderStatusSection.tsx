import { useState } from "react";

import {
  AdminOrderStatus,
  AdminPaymentStatus,
  ORDER_STATUS_LABELS,
  PAYMENT_STATUS_LABELS
} from "../api/adminOrderApi";
import { AdminOrderPreviewPatch, useAdminOrders } from "./useAdminOrders";

// 관리자 주문·결제 상태 화면 (Chunk 3: 실 API 연결).
// 부모(AdminDashboardPage)와는 onOperationLog(공용 운영 로그)만 공유하고,
// 주문 데이터는 useAdminOrders 가 자체적으로 서버에서 조회한다.
// M4 재고/M5 대시보드가 쓰는 mock(orders, adminOrderMock.ts)과는 완전히 분리되어 서로 영향을 주지 않는다.
// 로그인/권한 확인은 AdminDashboardPage 가 페이지 진입 시점에 이미 게이트로 막으므로
// 이 컴포넌트는 항상 인증된 상태에서만 렌더링된다(자체 접근 확인 없음).

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type OrderAdminAction = "expirePayment" | "approveCancel" | "prepareShipping" | "startShipping";
type OrderUiState = "idle" | "saved";

type OrderExceptionRow = {
  time: string;
  orderCode: string;
  issue: string;
  action: string;
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

const ORDER_ACTION_CONFIG: Record<
  OrderAdminAction,
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
  },
  prepareShipping: {
    requiredStatus: "PAID",
    nextOrderStatus: "PREPARING_SHIPMENT",
    issue: "배송 준비 전환",
    logTitle: "배송 준비 처리"
  },
  startShipping: {
    requiredStatus: "PREPARING_SHIPMENT",
    nextOrderStatus: "SHIPPED",
    issue: "배송 시작 전환",
    logTitle: "배송 시작 처리"
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
    applyPreviewOverride
  } = useAdminOrders({ enabled: true }); // 이 컴포넌트가 마운트된 시점엔 이미 AdminDashboardPage 의 접근 게이트를 통과한 상태

  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [orderExceptions, setOrderExceptions] = useState<OrderExceptionRow[]>([]);
  const [orderRefreshState, setOrderRefreshState] = useState<OrderUiState>("idle");
  const [orderActionState, setOrderActionState] = useState<OrderUiState>("idle");

  const selectedOrder = items.find((order) => order.id === selectedOrderId) ?? items[0] ?? null;

  const handleOrderRefresh = async () => {
    const succeeded = await refresh();
    if (!succeeded) {
      setOrderRefreshState("idle");
      onOperationLog("주문", "주문 상태 새로고침 실패", "잠시 후 다시 시도해 주세요.", "danger");
      return;
    }
    if (selectedOrder) {
      setOrderExceptions((current) => [
        {
          time: formatCurrentTime(),
          orderCode: selectedOrder.orderCode,
          issue: "상태 동기화 완료",
          action: `${selectedOrder.status} / ${selectedOrder.paymentStatus}`
        },
        ...current
      ]);
    }
    setOrderRefreshState("saved");
    setOrderActionState("idle");
    onOperationLog("주문", "주문 상태 새로고침", selectedOrder?.orderCode ?? "-", "success");
  };

  const handleSelectOrder = (orderId: string) => {
    setSelectedOrderId(orderId);
    setOrderRefreshState("idle");
    setOrderActionState("idle");
  };

  const handleOrderFilterReset = () => {
    resetFilters();
    setOrderRefreshState("idle");
    setOrderActionState("idle");
    onOperationLog("주문", "필터 초기화", "전체 주문 목록 표시", "neutral");
  };

  const handleOrderAction = (action: OrderAdminAction) => {
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
        time: formatCurrentTime(),
        orderCode: selectedOrder.orderCode,
        issue: config.issue,
        action: `${previousStatusLabel} → ${ORDER_STATUS_LABELS[config.nextOrderStatus]}`
      },
      ...current
    ]);
    setOrderRefreshState("idle");
    setOrderActionState("saved");
    onOperationLog("주문", config.logTitle, selectedOrder.orderCode, action === "approveCancel" ? "danger" : "success");
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
                <button className="admin-primary-button" disabled={loading} onClick={handleOrderRefresh} type="button">
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
                  onChange={(event) =>
                    setOrderStatusFilter(event.target.value === "" ? null : (event.target.value as AdminOrderStatus))
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
                  onChange={(event) =>
                    setPaymentStatusFilter(event.target.value === "" ? null : (event.target.value as AdminPaymentStatus))
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
                <button className="admin-secondary-button" onClick={handleOrderFilterReset} type="button">
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
              <button className="admin-secondary-button" disabled={loadingMore} onClick={loadMore} type="button">
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
                <div className={`admin-state-banner ${orderActionState === "saved" ? "success" : "review"}`}>
                  <strong>{orderActionState === "saved" ? "운영 액션 반영" : "운영 액션 미리보기"}</strong>
                  <span>
                    {orderActionState === "saved"
                      ? "선택 주문의 상태가 화면에서만 갱신되고 예외 이력에 남았습니다. 서버 데이터는 바뀌지 않습니다."
                      : "실제 API 연결 전, 관리자가 필요한 조치를 눌러 흐름을 확인하는 상태입니다."}
                  </span>
                </div>
                <div className="admin-order-action-grid" aria-label="주문 운영 액션">
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.expirePayment.requiredStatus}
                    onClick={() => handleOrderAction("expirePayment")}
                    type="button"
                  >
                    결제 만료
                  </button>
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.approveCancel.requiredStatus}
                    onClick={() => handleOrderAction("approveCancel")}
                    type="button"
                  >
                    취소 승인
                  </button>
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.prepareShipping.requiredStatus}
                    onClick={() => handleOrderAction("prepareShipping")}
                    type="button"
                  >
                    배송 준비
                  </button>
                  <button
                    className="admin-secondary-button"
                    disabled={selectedOrder.orderStatusRaw !== ORDER_ACTION_CONFIG.startShipping.requiredStatus}
                    onClick={() => handleOrderAction("startShipping")}
                    type="button"
                  >
                    배송 시작
                  </button>
                </div>
                <div className="admin-stock-warning">
                  현재 액션은 원우 API 계약 확인 전 로컬 미리보기입니다. 결제 만료, 취소 승인, 배송 전이 규칙은 백엔드 계약 확정 후 연결합니다.
                </div>
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
                    <tr key={`${row.time}-${row.orderCode}`}>
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
