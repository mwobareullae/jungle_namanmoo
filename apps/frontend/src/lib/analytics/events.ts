import { API_BASE_URL } from "../api";
import { createEventId, getAnonymousUserId, getSessionId } from "./identity";
import { trackGa4Event } from "./ga4";
import type { EventLogRequest, EventMetadata, OfficialEventName, TrackEventPayload } from "./types";

const sensitiveMetadataKeys = new Set([
  "access_token",
  "address",
  "address1",
  "address2",
  "authorization",
  "card_number",
  "concern_text",
  "email",
  "g_csrf_token",
  "id_token",
  "llm_prompt",
  "llm_response",
  "name",
  "password",
  "phone",
  "phone_number",
  "prompt",
  "raw_prompt",
  "raw_response",
  "recipient_name",
  "refresh_token",
  "response",
  "token",
  "user_email",
  "user_name"
]);

const normalizeMetadataKey = (key: string) => key.trim().toLowerCase().replace(/-/g, "_");

const sanitizeMetadata = (metadata: EventMetadata = {}): EventMetadata => {
  return Object.fromEntries(
    Object.entries(metadata).filter(([key]) => !sensitiveMetadataKeys.has(normalizeMetadataKey(key)))
  );
};

const stripUndefined = <T extends Record<string, unknown>>(value: T) =>
  Object.fromEntries(Object.entries(value).filter(([, fieldValue]) => fieldValue !== undefined)) as T;

const buildEventLogRequest = (eventName: OfficialEventName, payload: TrackEventPayload = {}): EventLogRequest => {
  return stripUndefined({
    event_id: payload.eventId ?? createEventId(),
    event_name: eventName,
    occurred_at: payload.occurredAt ?? new Date().toISOString(),
    anonymous_user_id: getAnonymousUserId(),
    session_id: getSessionId(),
    request_id: payload.requestId,
    recommendation_id: payload.recommendationId,
    product_id: payload.productId,
    rank: payload.rank,
    source: payload.source,
    page: payload.page,
    cart_id: payload.cartId,
    order_id: payload.orderId,
    metadata: sanitizeMetadata(payload.metadata)
  });
};

const toGaParams = (event: EventLogRequest): EventMetadata => ({
  ...event.metadata,
  recommendation_id: event.recommendation_id ?? null,
  product_id: event.product_id ?? null,
  rank: event.rank ?? null,
  source: event.source ?? null,
  page: event.page ?? null
});

export const trackEvent = (eventName: OfficialEventName, payload: TrackEventPayload = {}) => {
  if (typeof window === "undefined") {
    return;
  }

  const event = buildEventLogRequest(eventName, payload);
  trackGa4Event(eventName, toGaParams(event));

  void fetch(`${API_BASE_URL}/events`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    keepalive: true,
    body: JSON.stringify(event)
  }).catch(() => {
    // Event logging is best effort and must never block the user flow.
  });
};
