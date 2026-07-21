import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 클레임(반품·교환·환불) 조회·승인·거절·처리시작·완료 API 레이어 (M1.5-B).
// 계약: docs/admin/admin-dashboard-milestone-plan.md P1-M1.5-B "클레임 계약"

export type AdminClaimType = "RETURN" | "EXCHANGE" | "REFUND";
export type AdminClaimStatus = "REQUESTED" | "APPROVED" | "REJECTED" | "IN_PROGRESS" | "COMPLETED" | "WITHDRAWN";
export type AdminClaimAction = "APPROVE" | "REJECT" | "START" | "COMPLETE";
export type AdminClaimItemResolution = "REFUND" | "EXCHANGE";

export const CLAIM_TYPE_LABELS = {
  RETURN: "반품",
  EXCHANGE: "교환",
  REFUND: "환불"
} satisfies Record<AdminClaimType, string>;

export const CLAIM_STATUS_LABELS = {
  REQUESTED: "승인 대기",
  APPROVED: "승인완료",
  REJECTED: "거절됨",
  IN_PROGRESS: "처리중",
  COMPLETED: "완료",
  WITHDRAWN: "고객 철회"
} satisfies Record<AdminClaimStatus, string>;

type BackendAdminClaimListItem = {
  claim_code: string;
  order_code: string;
  customer_id: number;
  customer_display: string;
  product_summary: string;
  claim_type: AdminClaimType;
  status: AdminClaimStatus;
  reason_code: string;
  reason_detail: string | null;
  refund_amount: number | null;
  requested_at: string;
  processed_at: string | null;
  completed_at: string | null;
  available_actions: AdminClaimAction[];
};

type BackendAdminClaimListResponse = {
  items: BackendAdminClaimListItem[];
  page: number;
  page_size: number;
  total_count: number;
};

type BackendAdminClaimItemDetail = {
  order_item_id: number;
  product_name_snapshot: string;
  quantity: number;
  resolution: AdminClaimItemResolution;
};

type BackendAdminClaimEventDetail = {
  from_status: AdminClaimStatus | null;
  to_status: AdminClaimStatus;
  actor_type: string;
  actor_id: number | null;
  reason: string | null;
  created_at: string;
};

type BackendAdminClaimDetailResponse = BackendAdminClaimListItem & {
  order_status: string;
  payment_provider: string | null;
  items: BackendAdminClaimItemDetail[];
  events: BackendAdminClaimEventDetail[];
};

// 승인·거절·처리시작·완료 공통 응답. status 는 액션별로 다른 값(APPROVED/REJECTED/IN_PROGRESS/COMPLETED)이고
// processed_at 은 승인·거절 시각, completed_at 은 완료 시각이라 둘 다 독립적으로 내려온다.
type BackendAdminClaimActionResponse = {
  claim_code: string;
  order_code: string;
  status: AdminClaimStatus;
  processed_at: string | null;
  completed_at: string | null;
  available_actions: AdminClaimAction[];
};

export type AdminClaimRow = {
  claimCode: string;
  orderCode: string;
  customerId: number;
  customerDisplay: string;
  productSummary: string;
  claimType: AdminClaimType;
  claimTypeLabel: string;
  status: AdminClaimStatus;
  statusLabel: string;
  reasonCode: string;
  reasonDetail: string | null;
  refundAmount: number | null;
  requestedAt: string;
  processedAt: string | null;
  completedAt: string | null;
  availableActions: AdminClaimAction[];
};

export type AdminClaimItemDetail = {
  orderItemId: number;
  productNameSnapshot: string;
  quantity: number;
  resolution: AdminClaimItemResolution;
};

export type AdminClaimEventDetail = {
  fromStatus: AdminClaimStatus | null;
  toStatus: AdminClaimStatus;
  actorType: string;
  actorId: number | null;
  reason: string | null;
  createdAt: string;
};

export type AdminClaimDetail = AdminClaimRow & {
  orderStatus: string;
  paymentProvider: string | null;
  items: AdminClaimItemDetail[];
  events: AdminClaimEventDetail[];
};

export type AdminClaimListResult = {
  items: AdminClaimRow[];
  page: number;
  pageSize: number;
  totalCount: number;
};

export type AdminClaimQuery = {
  status?: AdminClaimStatus | null;
  claimType?: AdminClaimType | null;
  page?: number;
  pageSize?: number;
};

export type AdminClaimActionResult = {
  claimCode: string;
  orderCode: string;
  status: AdminClaimStatus;
  statusLabel: string;
  processedAt: string | null;
  completedAt: string | null;
  availableActions: AdminClaimAction[];
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

const adaptClaimRow = (item: BackendAdminClaimListItem): AdminClaimRow => ({
  claimCode: item.claim_code,
  orderCode: item.order_code,
  customerId: item.customer_id,
  customerDisplay: item.customer_display,
  productSummary: item.product_summary,
  claimType: item.claim_type,
  claimTypeLabel: CLAIM_TYPE_LABELS[item.claim_type],
  status: item.status,
  statusLabel: CLAIM_STATUS_LABELS[item.status],
  reasonCode: item.reason_code,
  reasonDetail: item.reason_detail,
  refundAmount: item.refund_amount,
  requestedAt: formatKstDateTime(item.requested_at),
  processedAt: item.processed_at === null ? null : formatKstDateTime(item.processed_at),
  completedAt: item.completed_at === null ? null : formatKstDateTime(item.completed_at),
  availableActions: item.available_actions
});

export const getAdminClaims = async (query: AdminClaimQuery = {}): Promise<AdminClaimListResult> => {
  const params = new URLSearchParams();
  if (query.status) params.set("status", query.status);
  if (query.claimType) params.set("claim_type", query.claimType);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));

  const queryString = params.toString();
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims${queryString ? `?${queryString}` : ""}`);
  const body = await parseJson<BackendAdminClaimListResponse>(response);
  return {
    items: body.items.map(adaptClaimRow),
    page: body.page,
    pageSize: body.page_size,
    totalCount: body.total_count
  };
};

export const getAdminClaimDetail = async (claimCode: string): Promise<AdminClaimDetail> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims/${encodeURIComponent(claimCode)}`);
  const body = await parseJson<BackendAdminClaimDetailResponse>(response);
  return {
    ...adaptClaimRow(body),
    orderStatus: body.order_status,
    paymentProvider: body.payment_provider,
    items: body.items.map((item) => ({
      orderItemId: item.order_item_id,
      productNameSnapshot: item.product_name_snapshot,
      quantity: item.quantity,
      resolution: item.resolution
    })),
    events: body.events.map((event) => ({
      fromStatus: event.from_status,
      toStatus: event.to_status,
      actorType: event.actor_type,
      actorId: event.actor_id,
      reason: event.reason,
      createdAt: formatKstDateTime(event.created_at)
    }))
  };
};

const adaptClaimActionResponse = (body: BackendAdminClaimActionResponse): AdminClaimActionResult => ({
  claimCode: body.claim_code,
  orderCode: body.order_code,
  status: body.status,
  statusLabel: CLAIM_STATUS_LABELS[body.status],
  processedAt: body.processed_at === null ? null : formatKstDateTime(body.processed_at),
  completedAt: body.completed_at === null ? null : formatKstDateTime(body.completed_at),
  availableActions: body.available_actions
});

export const postApproveClaim = async (claimCode: string): Promise<AdminClaimActionResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims/${encodeURIComponent(claimCode)}/approve`, {
    method: "POST"
  });
  return adaptClaimActionResponse(await parseJson<BackendAdminClaimActionResponse>(response));
};

export const postRejectClaim = async (claimCode: string, rejectionReason: string): Promise<AdminClaimActionResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims/${encodeURIComponent(claimCode)}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rejection_reason: rejectionReason })
  });
  return adaptClaimActionResponse(await parseJson<BackendAdminClaimActionResponse>(response));
};

export const postStartClaim = async (claimCode: string): Promise<AdminClaimActionResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims/${encodeURIComponent(claimCode)}/start`, {
    method: "POST"
  });
  return adaptClaimActionResponse(await parseJson<BackendAdminClaimActionResponse>(response));
};

export const postCompleteClaim = async (claimCode: string, restock: boolean): Promise<AdminClaimActionResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/order-claims/${encodeURIComponent(claimCode)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ restock })
  });
  return adaptClaimActionResponse(await parseJson<BackendAdminClaimActionResponse>(response));
};
