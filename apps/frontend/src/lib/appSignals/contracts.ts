export type OfficialEventName =
  | "home_view"
  | "page_view"
  | "home_product_impression"
  | "home_product_click"
  | "search_result_impression"
  | "search_result_click"
  | "recommendation_product_click"
  | "recommendation_product_impression"
  | "search_no_result";

export type EventMetadata = Record<string, string | number | boolean | null>;

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
  cart_id?: string;
  order_id?: string;
  metadata?: EventMetadata;
};

export type TrackEventPayload = {
  eventId?: string;
  occurredAt?: string;
  requestId?: string;
  recommendationId?: string;
  productId?: string;
  rank?: number;
  source?: string;
  page?: string;
  cartId?: string;
  orderId?: string;
  metadata?: EventMetadata;
};
