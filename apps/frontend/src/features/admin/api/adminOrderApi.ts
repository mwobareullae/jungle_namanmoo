import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 주문·결제 조회 API 레이어 (P1-M1).
// 백엔드는 영문 enum 을 그대로 반환하고, 화면 표시용 한글 변환은 여기서 담당한다.
// 계약: docs/admin/admin-m1-order-contract.md

// 백엔드 enum 과 1:1 (commerce.py ORDER/PAYMENT_STATUS_VALUES, contract §3·§4)
export type AdminOrderStatus =
  | "PENDING_PAYMENT"
  | "PAID"
  | "PAYMENT_FAILED"
  | "EXPIRED"
  | "PREPARING_SHIPMENT"
  | "SHIPPED"
  | "DELIVERED"
  | "CANCEL_REQUESTED"
  | "CANCELED"
  | "RETURN_REQUESTED"
  | "RETURNED"
  | "REFUND_REQUESTED"
  | "REFUNDED"
  | "EXCHANGE_REQUESTED"
  | "EXCHANGED";

export type AdminPaymentStatus =
  | "READY"
  | "CONFIRMING"
  | "UNKNOWN"
  | "APPROVED"
  | "FAILED"
  | "CANCELED"
  | "EXPIRED"
  | "REFUND_REQUESTED"
  | "REFUNDED"
  | "PARTIALLY_REFUNDED";

// 영문 enum → 한글 라벨. satisfies 로 15/10개 누락 시 타입검사가 잡도록 고정.
export const ORDER_STATUS_LABELS = {
  PENDING_PAYMENT: "결제대기",
  PAID: "결제완료",
  PAYMENT_FAILED: "결제실패",
  EXPIRED: "주문만료",
  PREPARING_SHIPMENT: "배송준비중",
  SHIPPED: "배송중",
  DELIVERED: "배송완료",
  CANCEL_REQUESTED: "취소요청",
  CANCELED: "주문취소완료",
  RETURN_REQUESTED: "반품요청",
  RETURNED: "반품 회수완료",
  REFUND_REQUESTED: "환불요청",
  REFUNDED: "환불완료",
  EXCHANGE_REQUESTED: "교환요청",
  EXCHANGED: "교환완료"
} satisfies Record<AdminOrderStatus, string>;

export const PAYMENT_STATUS_LABELS = {
  READY: "결제준비",
  CONFIRMING: "승인처리중",
  UNKNOWN: "상태확인필요",
  APPROVED: "승인완료",
  FAILED: "승인실패",
  CANCELED: "결제취소완료",
  EXPIRED: "결제만료",
  REFUND_REQUESTED: "환불처리중",
  REFUNDED: "환불완료",
  PARTIALLY_REFUNDED: "부분환불완료"
} satisfies Record<AdminPaymentStatus, string>;

// 결제 레코드 자체가 없는 이상 주문(payment_issue=PAYMENT_NOT_FOUND) 표시 라벨
export const PAYMENT_MISSING_LABEL = "결제정보 없음";

// 백엔드 응답(snake_case, 영문 enum) 원본 타입
type BackendAdminOrderListItem = {
  id: number;
  order_code: string;
  customer_id: number;
  customer_display: string;
  product_summary: string;
  item_count: number;
  total_quantity: number;
  total_amount: number;
  currency: string;
  order_status: AdminOrderStatus;
  payment_status: AdminPaymentStatus | null;
  payment_issue: "PAYMENT_NOT_FOUND" | null;
  reserved_quantity: number;
  recommendation_ids: string[];
  updated_at: string;
};

type BackendAdminOrderSummary = {
  pending_payment_count: number;
  preparing_shipment_count: number;
  cancel_requested_count: number;
  reserved_quantity_total: number;
};

type BackendAdminOrderListResponse = {
  items: BackendAdminOrderListItem[];
  summary: BackendAdminOrderSummary;
  next_cursor: string | null;
};

// 화면이 쓰는 행 모양 (한글 라벨 + 원본 영문 enum 병행 보관).
export type AdminOrderRow = {
  id: string;
  orderCode: string;
  customer: string;
  productSummary: string;
  itemCount: number;
  totalAmount: number;
  status: string; // 한글 라벨
  orderStatusRaw: AdminOrderStatus; // 영문 enum (필터 전송·로컬 프리뷰용)
  paymentStatus: string; // 한글 라벨 (또는 "결제정보 없음")
  paymentStatusRaw: AdminPaymentStatus | null; // 영문 enum, 결제 없으면 null
  paymentMissing: boolean;
  stockReserved: number;
  recommendationId: string;
  updatedAt: string;
};

export type AdminOrderSummary = {
  pendingPaymentCount: number;
  preparingShipmentCount: number;
  cancelRequestedCount: number;
  reservedQuantityTotal: number;
};

export type AdminOrderListResult = {
  items: AdminOrderRow[];
  summary: AdminOrderSummary;
  nextCursor: string | null;
};

export type AdminOrderQuery = {
  orderStatus?: AdminOrderStatus | null;
  paymentStatus?: AdminPaymentStatus | null;
  limit?: number;
  cursor?: string | null;
};

// 백엔드가 UTC(예: ...Z)를 반환하므로 KST(Asia/Seoul)로 변환해 "YYYY-MM-DD HH:mm" 표기.
const seoulDateTimeParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23"
});

const formatUpdatedAt = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const parts = seoulDateTimeParts.formatToParts(date);
  const pick = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
};

const adaptOrderRow = (item: BackendAdminOrderListItem): AdminOrderRow => ({
  id: String(item.id),
  orderCode: item.order_code,
  customer: item.customer_display,
  productSummary: item.product_summary,
  itemCount: item.item_count,
  totalAmount: item.total_amount,
  status: ORDER_STATUS_LABELS[item.order_status],
  orderStatusRaw: item.order_status,
  paymentStatus:
    item.payment_status === null ? PAYMENT_MISSING_LABEL : PAYMENT_STATUS_LABELS[item.payment_status],
  paymentStatusRaw: item.payment_status,
  paymentMissing: item.payment_issue === "PAYMENT_NOT_FOUND",
  stockReserved: item.reserved_quantity,
  recommendationId: item.recommendation_ids.length > 0 ? item.recommendation_ids.join(", ") : "-",
  updatedAt: formatUpdatedAt(item.updated_at)
});

export const getAdminOrders = async (query: AdminOrderQuery = {}): Promise<AdminOrderListResult> => {
  const params = new URLSearchParams();
  if (query.orderStatus) params.set("order_status", query.orderStatus);
  if (query.paymentStatus) params.set("payment_status", query.paymentStatus);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);

  const queryString = params.toString();
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/orders${queryString ? `?${queryString}` : ""}`
  );
  const body = await parseJson<BackendAdminOrderListResponse>(response);
  return {
    items: body.items.map(adaptOrderRow),
    summary: {
      pendingPaymentCount: body.summary.pending_payment_count,
      preparingShipmentCount: body.summary.preparing_shipment_count,
      cancelRequestedCount: body.summary.cancel_requested_count,
      reservedQuantityTotal: body.summary.reserved_quantity_total
    },
    nextCursor: body.next_cursor
  };
};
