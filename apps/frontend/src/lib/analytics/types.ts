export type OfficialEventName =
  | "recommendation_requested"
  | "recommendation_analyzed"
  | "recommendation_viewed"
  | "recommendation_product_impression"
  | "recommendation_product_click"
  | "product_viewed"
  | "cart_added"
  | "checkout_started"
  | "order_completed"
  | "search_performed"
  | "search_no_result"
  | "payment_failed"
  | "llm_call"
  | "api_request_logged";

export type EventMetadata = Record<string, JsonValue>;

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type TrackEventPayload = {
  eventId?: string;
  occurredAt?: string;
  requestId?: string;
  recommendationId?: string;
  productId?: string;
  rank?: number;
  source?: string;
  page?: string;
  cartId?: number;
  orderId?: number;
  metadata?: EventMetadata;
};

export type EventLogRequest = {
  event_id: string;
  event_name: OfficialEventName;
  occurred_at: string;
  anonymous_user_id: string;
  session_id: string;
  request_id?: string;
  recommendation_id?: string;
  product_id?: string;
  rank?: number;
  source?: string;
  page?: string;
  cart_id?: number;
  order_id?: number;
  metadata: EventMetadata;
};

export type EventLogResponse = {
  id: number;
  event_id: string;
  event_name: string;
  occurred_at: string;
  created_at: string;
  official_event: boolean;
  duplicate: boolean;
};
