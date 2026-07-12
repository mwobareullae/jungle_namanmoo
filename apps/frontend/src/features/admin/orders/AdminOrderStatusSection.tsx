import { Dispatch, SetStateAction, useMemo, useState } from "react";

import {
  MockOrderExceptionRow,
  MockOrderRow,
  MockOrderStatus,
  MockPaymentStatus,
  mockOrderExceptionRows
} from "./adminOrderMock";

// 관리자 주문·결제 상태 화면 (Chunk 2: mock 동작 그대로 추출).
// 부모(AdminDashboardPage)와 공유하는 orders/setOrders/onOperationLog 만 props 로 받고,
// 나머지 주문 전용 상태·헬퍼·타입은 이 파일 안에 캡슐화한다. 페이지 파일을 역참조하지 않는다.

// 페이지에도 있는 공용 성격이지만, 순환 의존을 피하려고 주문 컴포넌트 내부 사본을 둔다.
type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";
type OrderAdminAction = "expirePayment" | "approveCancel" | "prepareShipping" | "startShipping";
type OrderUiState = "idle" | "saved";

type AdminOrderStatusSectionProps = {
  active: boolean;
  orders: MockOrderRow[];
  setOrders: Dispatch<SetStateAction<MockOrderRow[]>>;
  onOperationLog: (area: string, title: string, detail: string, tone?: BadgeTone) => void;
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

function getOrderTone(status: MockOrderStatus | MockPaymentStatus): BadgeTone {
  if (status === "결제완료" || status === "배송준비" || status === "배송중" || status === "승인완료") {
    return "success";
  }

  if (status === "결제대기" || status === "승인대기") {
    return "warning";
  }

  if (status === "취소요청") {
    return "review";
  }

  if (status === "만료" || status === "실패" || status === "취소완료") {
    return "danger";
  }

  return "neutral";
}

export function AdminOrderStatusSection({
  active,
  orders,
  setOrders,
  onOperationLog
}: AdminOrderStatusSectionProps) {
  const [selectedOrderId, setSelectedOrderId] = useState(orders[0]?.id ?? "");
  const [orderStatusFilter, setOrderStatusFilter] = useState<MockOrderStatus | "전체">("전체");
  const [paymentStatusFilter, setPaymentStatusFilter] = useState<MockPaymentStatus | "전체">("전체");
  const [orderExceptions, setOrderExceptions] = useState<MockOrderExceptionRow[]>(mockOrderExceptionRows);
  const [orderRefreshState, setOrderRefreshState] = useState<OrderUiState>("idle");
  const [orderActionState, setOrderActionState] = useState<OrderUiState>("idle");

  const filteredOrders = useMemo(
    () =>
      orders.filter((order) => {
        const matchesOrderStatus = orderStatusFilter === "전체" ? true : order.status === orderStatusFilter;
        const matchesPaymentStatus =
          paymentStatusFilter === "전체" ? true : order.paymentStatus === paymentStatusFilter;

        return matchesOrderStatus && matchesPaymentStatus;
      }),
    [orders, orderStatusFilter, paymentStatusFilter]
  );
  const selectedOrder = orders.find((order) => order.id === selectedOrderId) ?? filteredOrders[0] ?? orders[0];
  const liveOrderStatusSummary = useMemo(
    () => [
      {
        label: "결제 대기",
        value: orders.filter((order) => order.status === "결제대기").length.toLocaleString("ko-KR"),
        tone: "warning" as const
      },
      {
        label: "배송 준비",
        value: orders.filter((order) => order.status === "배송준비").length.toLocaleString("ko-KR"),
        tone: "success" as const
      },
      {
        label: "취소 요청",
        value: orders.filter((order) => order.status === "취소요청").length.toLocaleString("ko-KR"),
        tone: "danger" as const
      },
      {
        label: "재고 예약",
        value: orders.reduce((sum, order) => sum + order.stockReserved, 0).toLocaleString("ko-KR"),
        tone: "neutral" as const
      }
    ],
    [orders]
  );

  const handleOrderRefresh = () => {
    setOrderExceptions((currentRows) => [
      {
        time: formatCurrentTime(),
        orderCode: selectedOrder.orderCode,
        issue: "상태 동기화 완료",
        action: `${selectedOrder.status} / ${selectedOrder.paymentStatus}`
      },
      ...currentRows
    ]);
    setOrderRefreshState("saved");
    setOrderActionState("idle");
    onOperationLog("주문", "주문 상태 새로고침", selectedOrder.orderCode, "success");
  };

  const handleSelectOrder = (orderId: string) => {
    setSelectedOrderId(orderId);
    setOrderRefreshState("idle");
    setOrderActionState("idle");
  };

  const handleOrderFilterReset = () => {
    setOrderStatusFilter("전체");
    setPaymentStatusFilter("전체");
    setOrderRefreshState("idle");
    setOrderActionState("idle");
    onOperationLog("주문", "필터 초기화", "전체 주문 목록 표시", "neutral");
  };

  const handleOrderAction = (action: OrderAdminAction) => {
    const actionConfig: Record<
      OrderAdminAction,
      { issue: string; logTitle: string; nextPaymentStatus?: MockPaymentStatus; nextStatus: MockOrderStatus; reservedStock?: number }
    > = {
      expirePayment: {
        issue: "결제 대기 만료 처리",
        logTitle: "결제 만료 처리",
        nextPaymentStatus: "실패",
        nextStatus: "만료",
        reservedStock: 0
      },
      approveCancel: {
        issue: "취소 요청 승인",
        logTitle: "취소 승인",
        nextPaymentStatus: "취소완료",
        nextStatus: "취소완료",
        reservedStock: 0
      },
      prepareShipping: {
        issue: "배송 준비 전환",
        logTitle: "배송 준비 처리",
        nextStatus: "배송준비"
      },
      startShipping: {
        issue: "배송 시작 전환",
        logTitle: "배송 시작 처리",
        nextStatus: "배송중"
      }
    };
    const config = actionConfig[action];

    setOrders((currentOrders) =>
      currentOrders.map((order) =>
        order.id === selectedOrder.id
          ? {
              ...order,
              paymentStatus: config.nextPaymentStatus ?? order.paymentStatus,
              status: config.nextStatus,
              stockReserved: config.reservedStock ?? order.stockReserved,
              updatedAt: `로컬 처리 ${formatCurrentTime()}`
            }
          : order
      )
    );
    setOrderExceptions((currentRows) => [
      {
        time: formatCurrentTime(),
        orderCode: selectedOrder.orderCode,
        issue: config.issue,
        action: `${selectedOrder.status} → ${config.nextStatus}`
      },
      ...currentRows
    ]);
    setOrderStatusFilter(config.nextStatus);
    setPaymentStatusFilter("전체");
    setOrderRefreshState("idle");
    setOrderActionState("saved");
    onOperationLog("주문", config.logTitle, selectedOrder.orderCode, action === "approveCancel" ? "danger" : "success");
  };

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
            <button className="admin-primary-button" onClick={handleOrderRefresh} type="button">
              새로고침
            </button>
          </div>
        </div>
        <div className="admin-excel-summary-grid">
          {liveOrderStatusSummary.map((item) => (
            <article className={`admin-excel-summary ${item.tone}`} key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
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
              onChange={(event) => setOrderStatusFilter(event.target.value as MockOrderStatus | "전체")}
              value={orderStatusFilter}
            >
              <option value="전체">주문 전체</option>
              <option value="결제대기">결제대기</option>
              <option value="결제완료">결제완료</option>
              <option value="배송준비">배송준비</option>
              <option value="배송중">배송중</option>
              <option value="취소요청">취소요청</option>
              <option value="취소완료">취소완료</option>
              <option value="만료">만료</option>
            </select>
            <select
              aria-label="결제 상태 필터"
              onChange={(event) => setPaymentStatusFilter(event.target.value as MockPaymentStatus | "전체")}
              value={paymentStatusFilter}
            >
              <option value="전체">결제 전체</option>
              <option value="승인완료">승인완료</option>
              <option value="승인대기">승인대기</option>
              <option value="실패">실패</option>
              <option value="취소완료">취소완료</option>
            </select>
            <button className="admin-secondary-button" onClick={handleOrderFilterReset} type="button">
              초기화
            </button>
          </div>
        </div>
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
              {filteredOrders.map((order) => (
                <tr
                  className={order.id === selectedOrder.id ? "selected" : undefined}
                  key={order.id}
                  onClick={() => handleSelectOrder(order.id)}
                >
                  <td>
                    <strong className="admin-product-name">{order.orderCode}</strong>
                    <small className="admin-product-code">{order.customer} · {order.updatedAt}</small>
                  </td>
                  <td>
                    <strong>{order.productSummary}</strong>
                    <small className="admin-product-code">{order.itemCount}개 상품</small>
                  </td>
                  <td>{formatCurrency(order.totalAmount)}</td>
                  <td>
                    <span className={`admin-badge ${getOrderTone(order.status)}`}>{order.status}</span>
                  </td>
                  <td>
                    <span className={`admin-badge ${getOrderTone(order.paymentStatus)}`}>
                      {order.paymentStatus}
                    </span>
                  </td>
                  <td>{order.stockReserved}개</td>
                  <td className="admin-file-name">{order.recommendationId}</td>
                </tr>
              ))}
              {filteredOrders.length === 0 && (
                <tr>
                  <td className="admin-empty-row" colSpan={7}>
                    조건에 맞는 주문이 없습니다. 필터를 초기화해 주세요.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <aside className="admin-panel admin-order-detail">
        <div className="admin-panel-header compact">
          <div>
            <p>선택 주문</p>
            <h2>{selectedOrder.orderCode}</h2>
          </div>
          <span className={`admin-badge ${getOrderTone(selectedOrder.status)}`}>
            {selectedOrder.status}
          </span>
        </div>
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
              ? "선택 주문의 상태가 로컬 화면에서 갱신되고 예외 이력에 남았습니다."
              : "실제 API 연결 전, 관리자가 필요한 조치를 눌러 흐름을 확인하는 상태입니다."}
          </span>
        </div>
        <div className="admin-order-action-grid" aria-label="주문 운영 액션">
          <button
            className="admin-secondary-button"
            disabled={selectedOrder.status !== "결제대기"}
            onClick={() => handleOrderAction("expirePayment")}
            type="button"
          >
            결제 만료
          </button>
          <button
            className="admin-secondary-button"
            disabled={selectedOrder.status !== "취소요청"}
            onClick={() => handleOrderAction("approveCancel")}
            type="button"
          >
            취소 승인
          </button>
          <button
            className="admin-secondary-button"
            disabled={selectedOrder.status !== "결제완료"}
            onClick={() => handleOrderAction("prepareShipping")}
            type="button"
          >
            배송 준비
          </button>
          <button
            className="admin-secondary-button"
            disabled={selectedOrder.status !== "배송준비"}
            onClick={() => handleOrderAction("startShipping")}
            type="button"
          >
            배송 시작
          </button>
        </div>
        <div className="admin-stock-warning">
          현재 액션은 원우 API 계약 확인 전 로컬 미리보기입니다. 결제 만료, 취소 승인, 배송 전이 규칙은 백엔드 계약 확정 후 연결합니다.
        </div>
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
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
