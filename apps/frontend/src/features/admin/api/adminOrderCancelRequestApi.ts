import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 취소 요청 조회·승인·거절 API 레이어 (M1.5-B).
// 계약: docs/admin/admin-dashboard-milestone-plan.md P1-M1.5-B "취소 승인 계약"

export type AdminCancelRequestStatus = "REQUESTED" | "APPROVED" | "REJECTED";
export type AdminCancelRequestAction = "APPROVE" | "REJECT";

export const CANCEL_REQUEST_STATUS_LABELS = {
  REQUESTED: "승인 대기",
  APPROVED: "승인완료",
  REJECTED: "거절됨"
} satisfies Record<AdminCancelRequestStatus, string>;

type BackendAdminCancelRequestItem = {
  request_code: string;
  order_code: string;
  customer_id: number;
  customer_display: string;
  status: AdminCancelRequestStatus;
  reason_code: string | null;
  reason_detail: string | null;
  decision_reason: string | null;
  requested_at: string;
  processed_at: string | null;
  available_actions: AdminCancelRequestAction[];
};

type BackendAdminCancelRequestPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

type BackendAdminCancelRequestListResponse = {
  items: BackendAdminCancelRequestItem[];
  pagination: BackendAdminCancelRequestPagination;
};

type BackendAdminCancelRequestDetailResponse = BackendAdminCancelRequestItem & {
  order_status: string;
  payment_status: string | null;
  payment_provider: string | null;
  product_summary: string;
  total_amount: number;
  currency: string;
};

// 승인·거절 직후는 항상 결정된 상태(REQUESTED 없음)라 목록 항목과 다른 좁은 상태 타입을 쓴다.
type BackendAdminCancelRequestActionResponse = {
  request_code: string;
  order_code: string;
  status: "APPROVED" | "REJECTED";
  order_status: "CANCELED" | "PAID";
  decision_reason: string | null;
  processed_at: string;
  available_actions: AdminCancelRequestAction[];
};

export type AdminCancelRequestRow = {
  requestCode: string;
  orderCode: string;
  customerId: number;
  customerDisplay: string;
  status: AdminCancelRequestStatus;
  statusLabel: string;
  reasonCode: string | null;
  reasonDetail: string | null;
  decisionReason: string | null;
  requestedAt: string;
  processedAt: string | null;
  availableActions: AdminCancelRequestAction[];
};

export type AdminCancelRequestDetail = AdminCancelRequestRow & {
  orderStatus: string;
  paymentStatus: string | null;
  paymentProvider: string | null;
  productSummary: string;
  totalAmount: number;
  currency: string;
};

export type AdminCancelRequestPagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
};

export type AdminCancelRequestListResult = {
  items: AdminCancelRequestRow[];
  pagination: AdminCancelRequestPagination;
};

export type AdminCancelRequestActionResult = {
  requestCode: string;
  orderCode: string;
  status: "APPROVED" | "REJECTED";
  statusLabel: string;
  orderStatus: "CANCELED" | "PAID";
  decisionReason: string | null;
  processedAt: string;
  availableActions: AdminCancelRequestAction[];
};

export type AdminCancelRequestQuery = {
  status?: AdminCancelRequestStatus | null;
  page?: number;
  pageSize?: number;
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

const formatKstDateTime = (iso: string): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const parts = seoulDateTimeParts.formatToParts(date);
  const pick = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
};

const adaptCancelRequestRow = (item: BackendAdminCancelRequestItem): AdminCancelRequestRow => ({
  requestCode: item.request_code,
  orderCode: item.order_code,
  customerId: item.customer_id,
  customerDisplay: item.customer_display,
  status: item.status,
  statusLabel: CANCEL_REQUEST_STATUS_LABELS[item.status],
  reasonCode: item.reason_code,
  reasonDetail: item.reason_detail,
  decisionReason: item.decision_reason,
  requestedAt: formatKstDateTime(item.requested_at),
  processedAt: item.processed_at === null ? null : formatKstDateTime(item.processed_at),
  availableActions: item.available_actions
});

export const getAdminCancelRequests = async (
  query: AdminCancelRequestQuery = {}
): Promise<AdminCancelRequestListResult> => {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));

  const queryString = params.toString();
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/order-cancel-requests${queryString ? `?${queryString}` : ""}`
  );
  const body = await parseJson<BackendAdminCancelRequestListResponse>(response);
  return {
    items: body.items.map(adaptCancelRequestRow),
    pagination: {
      page: body.pagination.page,
      pageSize: body.pagination.page_size,
      totalItems: body.pagination.total_items,
      totalPages: body.pagination.total_pages,
      hasNext: body.pagination.has_next,
      hasPrev: body.pagination.has_prev
    }
  };
};

export const getAdminCancelRequestDetail = async (requestCode: string): Promise<AdminCancelRequestDetail> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/order-cancel-requests/${encodeURIComponent(requestCode)}`
  );
  const body = await parseJson<BackendAdminCancelRequestDetailResponse>(response);
  return {
    ...adaptCancelRequestRow(body),
    orderStatus: body.order_status,
    paymentStatus: body.payment_status,
    paymentProvider: body.payment_provider,
    productSummary: body.product_summary,
    totalAmount: body.total_amount,
    currency: body.currency
  };
};

const adaptCancelRequestActionResponse = (
  body: BackendAdminCancelRequestActionResponse
): AdminCancelRequestActionResult => ({
  requestCode: body.request_code,
  orderCode: body.order_code,
  status: body.status,
  statusLabel: CANCEL_REQUEST_STATUS_LABELS[body.status],
  orderStatus: body.order_status,
  decisionReason: body.decision_reason,
  processedAt: formatKstDateTime(body.processed_at),
  availableActions: body.available_actions
});

export const postApproveCancelRequest = async (requestCode: string): Promise<AdminCancelRequestActionResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/order-cancel-requests/${encodeURIComponent(requestCode)}/approve`,
    { method: "POST" }
  );
  return adaptCancelRequestActionResponse(await parseJson<BackendAdminCancelRequestActionResponse>(response));
};

export const postRejectCancelRequest = async (
  requestCode: string,
  rejectionReason: string
): Promise<AdminCancelRequestActionResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/order-cancel-requests/${encodeURIComponent(requestCode)}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rejection_reason: rejectionReason })
    }
  );
  return adaptCancelRequestActionResponse(await parseJson<BackendAdminCancelRequestActionResponse>(response));
};
