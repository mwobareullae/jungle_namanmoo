import type {
  CreateOrderRequest,
  CreateOrderResponse,
  OrderCancelResponse,
  OrderDetailResponse,
  OrderListResponse,
  MockPaymentConfirmResponse,
  TossPaymentConfirmRequest,
  TossPaymentConfirmResponse,
} from "../types/order";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

const createIdempotencyKey = () => {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }

  return `mwb-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

export const createOrder = (request: CreateOrderRequest): Promise<CreateOrderResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": createIdempotencyKey(),
    },
    body: JSON.stringify(request),
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
  return fetchWithTimeout(`${API_BASE_URL}/orders${queryString ? `?${queryString}` : ""}`).then((response) =>
    parseJson<OrderListResponse>(response),
  );
};

export const confirmTossPayment = (
  request: TossPaymentConfirmRequest,
): Promise<TossPaymentConfirmResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/payments/toss/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  }).then((response) => parseJson<TossPaymentConfirmResponse>(response));
};

export const confirmMockPayment = (paymentCode: string): Promise<MockPaymentConfirmResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/payments/${encodeURIComponent(paymentCode)}/mock/confirm`, {
    method: "POST",
  }).then((response) => parseJson<MockPaymentConfirmResponse>(response));
};

export const cancelOrder = (orderCode: string): Promise<OrderCancelResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}/cancel`, {
    method: "POST",
  }).then((response) => parseJson<OrderCancelResponse>(response));
};

export const getOrderDetail = (orderCode: string): Promise<OrderDetailResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}`).then((response) =>
    parseJson<OrderDetailResponse>(response),
  );
};
