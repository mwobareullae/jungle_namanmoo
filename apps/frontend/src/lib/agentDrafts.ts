const AGENT_REVIEW_DRAFT_KEY = "mwobareullae-agent-review-draft-v1";
const AGENT_CLAIM_DRAFT_KEY = "mwobareullae-agent-claim-draft-v1";

export type AgentReviewDraft = {
  is_repurchase_review: boolean;
  order_code: string;
  order_item_id: number;
  product_id: string;
  rating: number;
  review_text: string;
};

export type AgentClaimDraft = {
  claim_type: "RETURN" | "EXCHANGE" | "REFUND";
  order_code: string;
  order_item_id: number;
  reason_code: "CHANGE_OF_MIND" | "DEFECTIVE" | "WRONG_ITEM" | "OTHER";
  reason_detail: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

export const storeAgentReviewDraft = (payload: Record<string, unknown>) => {
  if (typeof window === "undefined") return false;
  const draft: AgentReviewDraft = {
    is_repurchase_review: payload.is_repurchase_review === true,
    order_code: typeof payload.order_code === "string" ? payload.order_code : "",
    order_item_id: typeof payload.order_item_id === "number" ? payload.order_item_id : 0,
    product_id: typeof payload.product_id === "string" ? payload.product_id : "",
    rating: typeof payload.rating === "number" ? payload.rating : 5,
    review_text: typeof payload.review_text === "string" ? payload.review_text : "",
  };
  if (!draft.order_item_id || !draft.product_id || !draft.review_text) return false;
  window.sessionStorage.setItem(AGENT_REVIEW_DRAFT_KEY, JSON.stringify(draft));
  return true;
};

export const readAgentReviewDraft = (): AgentReviewDraft | null => {
  if (typeof window === "undefined") return null;
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(AGENT_REVIEW_DRAFT_KEY) ?? "null");
    if (!isRecord(parsed)) return null;
    const draft = parsed as Partial<AgentReviewDraft>;
    if (
      typeof draft.order_item_id !== "number"
      || typeof draft.product_id !== "string"
      || typeof draft.review_text !== "string"
      || typeof draft.rating !== "number"
    ) return null;
    return {
      is_repurchase_review: draft.is_repurchase_review === true,
      order_code: typeof draft.order_code === "string" ? draft.order_code : "",
      order_item_id: draft.order_item_id,
      product_id: draft.product_id,
      rating: Math.min(5, Math.max(1, draft.rating)),
      review_text: draft.review_text,
    };
  } catch {
    return null;
  }
};

export const clearAgentReviewDraft = () => {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(AGENT_REVIEW_DRAFT_KEY);
};

const isClaimType = (value: unknown): value is AgentClaimDraft["claim_type"] =>
  value === "RETURN" || value === "EXCHANGE" || value === "REFUND";

const isClaimReason = (value: unknown): value is AgentClaimDraft["reason_code"] =>
  value === "CHANGE_OF_MIND" || value === "DEFECTIVE" || value === "WRONG_ITEM" || value === "OTHER";

export const storeAgentClaimDraft = (payload: Record<string, unknown>) => {
  if (typeof window === "undefined") return false;
  if (
    typeof payload.order_code !== "string"
    || typeof payload.order_item_id !== "number"
    || !isClaimType(payload.claim_type)
    || !isClaimReason(payload.reason_code)
  ) return false;
  const draft: AgentClaimDraft = {
    claim_type: payload.claim_type,
    order_code: payload.order_code,
    order_item_id: payload.order_item_id,
    reason_code: payload.reason_code,
    reason_detail: typeof payload.reason_detail === "string" ? payload.reason_detail : "",
  };
  window.sessionStorage.setItem(AGENT_CLAIM_DRAFT_KEY, JSON.stringify(draft));
  return true;
};

export const readAgentClaimDraft = (): AgentClaimDraft | null => {
  if (typeof window === "undefined") return null;
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(AGENT_CLAIM_DRAFT_KEY) ?? "null");
    if (!isRecord(parsed)) return null;
    if (
      typeof parsed.order_code !== "string"
      || typeof parsed.order_item_id !== "number"
      || !isClaimType(parsed.claim_type)
      || !isClaimReason(parsed.reason_code)
    ) return null;
    return {
      claim_type: parsed.claim_type,
      order_code: parsed.order_code,
      order_item_id: parsed.order_item_id,
      reason_code: parsed.reason_code,
      reason_detail: typeof parsed.reason_detail === "string" ? parsed.reason_detail : "",
    };
  } catch {
    return null;
  }
};

export const clearAgentClaimDraft = () => {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(AGENT_CLAIM_DRAFT_KEY);
};
