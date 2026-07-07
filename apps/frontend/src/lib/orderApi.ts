import type {
  CreateOrderRequest,
  CreateOrderResponse,
  OrderCancelResponse,
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

export const cancelOrder = (orderCode: string): Promise<OrderCancelResponse> => {
  return fetchWithTimeout(`${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}/cancel`, {
    method: "POST",
  }).then((response) => parseJson<OrderCancelResponse>(response));
};
