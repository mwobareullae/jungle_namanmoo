export type OrderClaimType = "RETURN" | "EXCHANGE" | "REFUND";

export type OrderClaimEligibilityItem = {
  order_item_id: number;
  ordered_quantity: number;
  claimable_quantity: number;
  status: string;
};

export type OrderClaimEligibilityResponse = {
  order_code: string;
  eligible: boolean;
  reason_code?: string | null;
  claim_window_ends_at?: string | null;
  items: OrderClaimEligibilityItem[];
};

export type OrderClaimCreateRequest = {
  order_code: string;
  claim_type: OrderClaimType;
  reason_code: string;
  reason_detail?: string | null;
  items: Array<{ order_item_id: number; quantity: number }>;
};

export type OrderClaimResponse = {
  claim_code: string;
  order_code: string;
  claim_type: OrderClaimType;
  status: string;
  reason_code: string;
  reason_detail?: string | null;
  refund_amount?: number | null;
  requested_at: string;
  processed_at?: string | null;
  completed_at?: string | null;
  items: Array<{ order_item_id: number; quantity: number; resolution: "REFUND" | "EXCHANGE" }>;
};

export type OrderClaimListResponse = {
  items: OrderClaimResponse[];
};
