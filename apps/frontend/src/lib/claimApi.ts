import type {
  OrderClaimCreateRequest,
  OrderClaimEligibilityResponse,
  OrderClaimListResponse,
  OrderClaimResponse
} from "../types/claim";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

export const getClaimEligibility = (orderCode: string) =>
  fetchWithTimeout(
    `${API_BASE_URL}/orders/${encodeURIComponent(orderCode)}/claim-eligibility`
  ).then((response) => parseJson<OrderClaimEligibilityResponse>(response));

export const createOrderClaim = (request: OrderClaimCreateRequest) =>
  fetchWithTimeout(`${API_BASE_URL}/order-claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  }).then((response) => parseJson<OrderClaimResponse>(response));

export const getOrderClaims = () =>
  fetchWithTimeout(`${API_BASE_URL}/order-claims`).then((response) =>
    parseJson<OrderClaimListResponse>(response)
  );

export const getOrderClaim = (claimCode: string) =>
  fetchWithTimeout(`${API_BASE_URL}/order-claims/${encodeURIComponent(claimCode)}`).then(
    (response) => parseJson<OrderClaimResponse>(response)
  );

export const withdrawOrderClaim = (claimCode: string) =>
  fetchWithTimeout(`${API_BASE_URL}/order-claims/${encodeURIComponent(claimCode)}/withdraw`, {
    method: "POST"
  }).then((response) => parseJson<OrderClaimResponse>(response));
