import type {
  CreateOrderRequest,
  CreateOrderResponse,
  OrderCancelRequest,
  OrderCancelResponse,
  OrderDetailResponse,
  OrderListResponse,
  OrderSummaryResponse,
  TossPaymentConfirmRequest,
  TossPaymentConfirmResponse
} from "../types/order";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

const createIdempotencyKey = () => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }

  return `mwb-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const ORDER_SUMMARY_CACHE_TTL_MS = 10_000;
const orderSummaryCache = new Map<number, { value: OrderSummaryResponse; expiresAt: number }>();
const orderSummaryRequests = new Map<number, Promise<OrderSummaryResponse>>();

export const invalidateOrderSummary = (userId?: number | null) => {
  if (typeof userId === "number") orderSummaryCache.delete(userId);
  else orderSummaryCache.clear();
};

export const createOrder = (request: CreateOrderRequest): Promise<CreateOrderResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": createIdempotencyKey()
    },
    body: JSON.stringify(request)
  }).then((response) => parseJson<CreateOrderResponse>(response));
};

export type GetOrdersParams = {
  status?: string | null;
  limit?: number;
  cursor?: string | null;
};

export const getOrders = (params: GetOrdersParams = {}): Promise<OrderListResponse> => {
  const searchParams = new URLSearchParams();

  if (params.status) searchParams.set("status", params.status);
  if (params.limit) searchParams.set("limit", String(params.limit));
  if (params.cursor) searchParams.set("cursor", params.cursor);

  const queryString = searchParams.toString();
  return fetchWithTimeout(`${API_BASE_URL}/orders${queryString ? `?${queryString}` : ""}`).then(
    (response) => parseJson<OrderListResponse>(response)
  );
};

export const getOrderSummary = (userId?: number | null): Promise<OrderSummaryResponse> => {
  if (typeof userId !== "number") {
    return fetchWithTimeout(`${API_BASE_URL}/orders/summary`).then((response) => parseJson<OrderSummaryResponse>(response));
  }
  const cached = orderSummaryCache.get(userId);
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.value);
  const pending = orderSummaryRequests.get(userId);
  if (pending) return pending;
  const request = fetchWithTimeout(`${API_BASE_URL}/orders/summary`)
    .then((response) => parseJson<OrderSummaryResponse>(response))
    .then((value) => {
      orderSummaryCache.set(userId, { value, expiresAt: Date.now() + ORDER_SUMMARY_CACHE_TTL_MS });
      return value;
    })
    .finally(() => {
      orderSummaryRequests.delete(userId);
    });
  orderSummaryRequests.set(userId, request);
  return request;
};

export const confirmTossPayment = (
  request: TossPaymentConfirmRequest
): Promise<TossPaymentConfirmResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/payments/toss/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(request)
  }).then((response) => parseJson<TossPaymentConfirmResponse>(response));
};

export const cancelOrder = (
  orderCode: string,
  request?: OrderCancelRequest
): Promise<OrderCancelResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}/cancel`, {
    method: "POST",
    ...(request
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request)
        }
      : {})
  }).then((response) => parseJson<OrderCancelResponse>(response));
};

export const getOrderDetail = (orderCode: string): Promise<OrderDetailResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}`).then(
    (response) => parseJson<OrderDetailResponse>(response)
  );
};
