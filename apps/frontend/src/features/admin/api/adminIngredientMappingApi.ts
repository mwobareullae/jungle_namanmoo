import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 성분 매핑 검수 조회 API 레이어 (P1-M2-A Chunk 4, 조회 전용).
// 백엔드는 snake_case·영문 상태를 반환하고, 여기서 camelCase 로 변환한다.
// 검수 단위(외부 식별자)는 (pendingCode, normalizedSourceName) 복합키.
// 계약: docs/admin/admin-m2a-ingredient-mapping-api-contract.md

export type IngredientMappingStatus = "PENDING" | "HELD" | "APPROVED" | "REJECTED";
export type IngredientMappingMatchSource = "ALIAS_EXACT" | "CANONICAL_NAME_EXACT";
export type IngredientMappingAction = "APPROVE" | "HOLD" | "REJECT" | "REOPEN";
export type IngredientMappingDecisionStatus = "HELD" | "APPROVED" | "REJECTED";

// 목록 필터. "ALL" 은 프론트 전용(백엔드로는 status 미전송).
export type IngredientMappingStatusFilter = "ALL" | IngredientMappingStatus;

export type IngredientMappingSuggestion = {
  targetIngredientId: number;
  targetIngredientCode: string;
  targetIngredientName: string;
  matchSource: IngredientMappingMatchSource;
};

export type IngredientMappingDecision = {
  status: IngredientMappingDecisionStatus;
  targetIngredientCode: string | null;
  targetIngredientName: string | null;
  decisionReason: string | null;
  reviewedByUserId: number;
  reviewedAt: string;
};

export type IngredientMappingRow = {
  pendingCode: string;
  rawName: string;
  normalizedSourceName: string;
  productCount: number;
  connectionCount: number;
  status: IngredientMappingStatus;
  suggestion: IngredientMappingSuggestion | null;
  decision: IngredientMappingDecision | null;
  availableActions: IngredientMappingAction[];
};

export type IngredientMappingSummary = {
  pendingCount: number;
  heldCount: number;
  approvedCount: number;
  rejectedCount: number;
};

export type IngredientMappingListResult = {
  items: IngredientMappingRow[];
  summary: IngredientMappingSummary;
  nextCursor: string | null;
};

export type IngredientMappingRawNameVariant = {
  rawName: string;
  productCount: number;
  connectionCount: number;
};

export type IngredientMappingSampleProduct = {
  productCode: string;
  productName: string;
  rawName: string;
  displayOrder: number | null;
  concentrationText: string | null;
};

export type IngredientMappingEvent = {
  fromStatus: IngredientMappingDecisionStatus | null;
  toStatus: IngredientMappingDecisionStatus;
  fromTargetIngredientCode: string | null;
  toTargetIngredientCode: string | null;
  actorId: number;
  reason: string | null;
  createdAt: string;
};

export type IngredientMappingDetail = IngredientMappingRow & {
  pendingIngredientName: string;
  rawNameVariants: IngredientMappingRawNameVariant[];
  sampleProducts: IngredientMappingSampleProduct[];
  events: IngredientMappingEvent[];
};

export type IngredientMappingQuery = {
  status?: IngredientMappingStatusFilter;
  q?: string | null;
  limit?: number;
  cursor?: string | null;
};

type BackendSuggestion = {
  target_ingredient_id: number;
  target_ingredient_code: string;
  target_ingredient_name: string;
  match_source: IngredientMappingMatchSource;
};

type BackendDecision = {
  status: IngredientMappingDecisionStatus;
  target_ingredient_code: string | null;
  target_ingredient_name: string | null;
  decision_reason: string | null;
  reviewed_by_user_id: number;
  reviewed_at: string;
};

type BackendRow = {
  pending_code: string;
  raw_name: string;
  normalized_source_name: string;
  product_count: number;
  connection_count: number;
  status: IngredientMappingStatus;
  suggestion: BackendSuggestion | null;
  decision: BackendDecision | null;
  available_actions: IngredientMappingAction[];
};

type BackendSummary = {
  pending_count: number;
  held_count: number;
  approved_count: number;
  rejected_count: number;
};

type BackendListResponse = {
  items: BackendRow[];
  summary: BackendSummary;
  next_cursor: string | null;
};

type BackendRawNameVariant = {
  raw_name: string;
  product_count: number;
  connection_count: number;
};

type BackendSampleProduct = {
  product_code: string;
  product_name: string;
  raw_name: string;
  display_order: number | null;
  concentration_text: string | null;
};

type BackendEvent = {
  from_status: IngredientMappingDecisionStatus | null;
  to_status: IngredientMappingDecisionStatus;
  from_target_ingredient_code: string | null;
  to_target_ingredient_code: string | null;
  actor_id: number;
  reason: string | null;
  created_at: string;
};

type BackendDetail = BackendRow & {
  pending_ingredient_name: string;
  raw_name_variants: BackendRawNameVariant[];
  sample_products: BackendSampleProduct[];
  events: BackendEvent[];
};

// 백엔드가 UTC ISO 를 주므로 KST(Asia/Seoul) "YYYY-MM-DD HH:mm" 로 표시한다.
const seoulDateTimeParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23"
});

const formatKstDateTime = (iso: string | null): string | null => {
  if (iso === null) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const parts = seoulDateTimeParts.formatToParts(date);
  const pick = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
};

const adaptSuggestion = (suggestion: BackendSuggestion | null): IngredientMappingSuggestion | null =>
  suggestion === null
    ? null
    : {
        targetIngredientId: suggestion.target_ingredient_id,
        targetIngredientCode: suggestion.target_ingredient_code,
        targetIngredientName: suggestion.target_ingredient_name,
        matchSource: suggestion.match_source
      };

const adaptDecision = (decision: BackendDecision | null): IngredientMappingDecision | null =>
  decision === null
    ? null
    : {
        status: decision.status,
        targetIngredientCode: decision.target_ingredient_code,
        targetIngredientName: decision.target_ingredient_name,
        decisionReason: decision.decision_reason,
        reviewedByUserId: decision.reviewed_by_user_id,
        reviewedAt: formatKstDateTime(decision.reviewed_at) ?? decision.reviewed_at
      };

const adaptRow = (row: BackendRow): IngredientMappingRow => ({
  pendingCode: row.pending_code,
  rawName: row.raw_name,
  normalizedSourceName: row.normalized_source_name,
  productCount: row.product_count,
  connectionCount: row.connection_count,
  status: row.status,
  suggestion: adaptSuggestion(row.suggestion),
  decision: adaptDecision(row.decision),
  availableActions: row.available_actions
});

const adaptDetail = (detail: BackendDetail): IngredientMappingDetail => ({
  ...adaptRow(detail),
  pendingIngredientName: detail.pending_ingredient_name,
  rawNameVariants: detail.raw_name_variants.map((variant) => ({
    rawName: variant.raw_name,
    productCount: variant.product_count,
    connectionCount: variant.connection_count
  })),
  sampleProducts: detail.sample_products.map((product) => ({
    productCode: product.product_code,
    productName: product.product_name,
    rawName: product.raw_name,
    displayOrder: product.display_order,
    concentrationText: product.concentration_text
  })),
  events: detail.events.map((event) => ({
    fromStatus: event.from_status,
    toStatus: event.to_status,
    fromTargetIngredientCode: event.from_target_ingredient_code,
    toTargetIngredientCode: event.to_target_ingredient_code,
    actorId: event.actor_id,
    reason: event.reason,
    createdAt: formatKstDateTime(event.created_at) ?? event.created_at
  }))
});

export const getIngredientMappings = async (
  query: IngredientMappingQuery = {}
): Promise<IngredientMappingListResult> => {
  const params = new URLSearchParams();
  if (query.status && query.status !== "ALL") params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);

  const queryString = params.toString();
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/ingredient-mappings${queryString ? `?${queryString}` : ""}`
  );
  const body = await parseJson<BackendListResponse>(response);
  return {
    items: body.items.map(adaptRow),
    summary: {
      pendingCount: body.summary.pending_count,
      heldCount: body.summary.held_count,
      approvedCount: body.summary.approved_count,
      rejectedCount: body.summary.rejected_count
    },
    nextCursor: body.next_cursor
  };
};

export const getIngredientMappingDetail = async (
  pendingCode: string,
  normalizedSourceName: string
): Promise<IngredientMappingDetail> => {
  const params = new URLSearchParams({ normalized_source_name: normalizedSourceName });
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/ingredient-mappings/${encodeURIComponent(pendingCode)}?${params.toString()}`
  );
  return adaptDetail(await parseJson<BackendDetail>(response));
};
