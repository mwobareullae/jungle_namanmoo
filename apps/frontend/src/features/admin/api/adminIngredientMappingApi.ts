import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 성분 매핑 검수 조회 API 레이어 (P1-M2-A Chunk 4, 조회 전용).
// 백엔드는 snake_case·영문 상태를 반환하고, 여기서 camelCase 로 변환한다.
// 검수 단위(외부 식별자)는 (pendingCode, normalizedSourceName) 복합키.
// 계약: docs/admin/admin-m2a-ingredient-mapping-api-contract.md

export type IngredientMappingStatus = "PENDING" | "HELD" | "NEEDS_REVIEW" | "APPROVED" | "REJECTED";
export type IngredientMappingFinalDisposition =
  | "MAPPED"
  | "NON_INGREDIENT"
  | "COMPOUND_MATERIAL"
  | "SOURCE_ERROR"
  | "UNRESOLVABLE";
export type IngredientMappingNonMappingFinalDisposition = Exclude<
  IngredientMappingFinalDisposition,
  "MAPPED"
>;
export type IngredientMappingMatchSource = "ALIAS_EXACT" | "CANONICAL_NAME_EXACT";
export type IngredientMappingCandidateType =
  | "CANONICAL_EXACT_MATCH"
  | "ALIAS_EXACT_MATCH"
  | "EXACT_MATCH_CONFLICT"
  | "NO_EXACT_MATCH";
export type IngredientMappingAction = "APPROVE" | "HOLD" | "REJECT" | "REOPEN";
export type IngredientMappingDecisionStatus = "HELD" | "NEEDS_REVIEW" | "APPROVED" | "REJECTED";

// 목록 필터. "ALL" 은 프론트 전용(백엔드로는 status 미전송).
export type IngredientMappingStatusFilter = "ALL" | IngredientMappingStatus;
export type IngredientMappingSort = "CODE_ASC" | "CONNECTION_DESC";
export type IngredientMappingCandidateFilter = "ALL" | IngredientMappingCandidateType;

export type IngredientMappingSuggestion = {
  targetIngredientId: number;
  targetIngredientCode: string;
  targetIngredientName: string;
  matchSource: IngredientMappingMatchSource;
};

export type IngredientMappingCandidate = {
  candidateType: IngredientMappingCandidateType;
  evidence: string;
};

export type IngredientMappingDecision = {
  status: IngredientMappingDecisionStatus;
  finalDisposition: IngredientMappingFinalDisposition | null;
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
  candidate: IngredientMappingCandidate;
  suggestion: IngredientMappingSuggestion | null;
  decision: IngredientMappingDecision | null;
  availableActions: IngredientMappingAction[];
};

export type IngredientMappingSummary = {
  pendingCount: number;
  heldCount: number;
  needsReviewCount: number;
  unclassifiedCount: number;
  approvedCount: number;
  rejectedCount: number;
};

export type IngredientMappingListResult = {
  items: IngredientMappingRow[];
  summary: IngredientMappingSummary;
  nextCursor: string | null;
};

export type IngredientMappingBulkApprovalPreviewItem = {
  pendingCode: string;
  normalizedSourceName: string;
  rawName: string;
  productCount: number;
  connectionCount: number;
  targetIngredientCode: string;
  targetIngredientName: string;
  aliasSource: string;
  canonicalSourceUrl: string;
};

export type IngredientMappingBulkApprovalPreview = {
  criteria: "KCIA_ALIAS_EXACT";
  maximumCount: number;
  eligibleCount: number;
  items: IngredientMappingBulkApprovalPreviewItem[];
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
  fromFinalDisposition: IngredientMappingFinalDisposition | null;
  toFinalDisposition: IngredientMappingFinalDisposition | null;
  fromTargetIngredientCode: string | null;
  toTargetIngredientCode: string | null;
  actorId: number;
  reason: string | null;
  evidenceSourceUrl: string | null;
  sourceReference: string | null;
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
  finalDisposition?: IngredientMappingFinalDisposition | null;
  sort?: IngredientMappingSort;
  candidateType?: IngredientMappingCandidateType | null;
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

type BackendCandidate = {
  candidate_type: IngredientMappingCandidateType;
  evidence: string;
};

type BackendDecision = {
  status: IngredientMappingDecisionStatus;
  final_disposition: IngredientMappingFinalDisposition | null;
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
  candidate: BackendCandidate;
  suggestion: BackendSuggestion | null;
  decision: BackendDecision | null;
  available_actions: IngredientMappingAction[];
};

type BackendSummary = {
  pending_count: number;
  held_count: number;
  needs_review_count: number;
  unclassified_count: number;
  approved_count: number;
  rejected_count: number;
};

type BackendListResponse = {
  items: BackendRow[];
  summary: BackendSummary;
  next_cursor: string | null;
};

type BackendBulkApprovalPreviewItem = {
  pending_code: string;
  normalized_source_name: string;
  raw_name: string;
  product_count: number;
  connection_count: number;
  target_ingredient_code: string;
  target_ingredient_name: string;
  alias_source: string;
  canonical_source_url: string;
};

type BackendBulkApprovalPreview = {
  criteria: "KCIA_ALIAS_EXACT";
  maximum_count: number;
  eligible_count: number;
  items: BackendBulkApprovalPreviewItem[];
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
  from_final_disposition: IngredientMappingFinalDisposition | null;
  to_final_disposition: IngredientMappingFinalDisposition | null;
  from_target_ingredient_code: string | null;
  to_target_ingredient_code: string | null;
  actor_id: number;
  reason: string | null;
  evidence_source_url: string | null;
  source_reference: string | null;
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

const adaptCandidate = (candidate: BackendCandidate): IngredientMappingCandidate => ({
  candidateType: candidate.candidate_type,
  evidence: candidate.evidence
});

const adaptDecision = (decision: BackendDecision | null): IngredientMappingDecision | null =>
  decision === null
    ? null
    : {
        status: decision.status,
        finalDisposition: decision.final_disposition,
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
  candidate: adaptCandidate(row.candidate),
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
    fromFinalDisposition: event.from_final_disposition,
    toFinalDisposition: event.to_final_disposition,
    fromTargetIngredientCode: event.from_target_ingredient_code,
    toTargetIngredientCode: event.to_target_ingredient_code,
    actorId: event.actor_id,
    reason: event.reason,
    evidenceSourceUrl: event.evidence_source_url,
    sourceReference: event.source_reference,
    createdAt: formatKstDateTime(event.created_at) ?? event.created_at
  }))
});

export const getIngredientMappings = async (
  query: IngredientMappingQuery = {}
): Promise<IngredientMappingListResult> => {
  const params = new URLSearchParams();
  if (query.status && query.status !== "ALL") params.set("status", query.status);
  if (query.finalDisposition) params.set("final_disposition", query.finalDisposition);
  if (query.sort && query.sort !== "CODE_ASC") params.set("sort", query.sort);
  if (query.candidateType) params.set("candidate_type", query.candidateType);
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
      needsReviewCount: body.summary.needs_review_count,
      unclassifiedCount: body.summary.unclassified_count,
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

export const getKciaAliasExactBulkApprovalPreview = async (): Promise<IngredientMappingBulkApprovalPreview> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/bulk-approve/preview`);
  const body = await parseJson<BackendBulkApprovalPreview>(response);
  return {
    criteria: body.criteria,
    maximumCount: body.maximum_count,
    eligibleCount: body.eligible_count,
    items: body.items.map((item) => ({
      pendingCode: item.pending_code,
      normalizedSourceName: item.normalized_source_name,
      rawName: item.raw_name,
      productCount: item.product_count,
      connectionCount: item.connection_count,
      targetIngredientCode: item.target_ingredient_code,
      targetIngredientName: item.target_ingredient_name,
      aliasSource: item.alias_source,
      canonicalSourceUrl: item.canonical_source_url
    }))
  };
};

// --- 판정 액션 (쓰기) ------------------------------------------------------

export type IngredientMappingActionResult = {
  pendingCode: string;
  normalizedSourceName: string;
  status: IngredientMappingDecisionStatus;
  finalDisposition: IngredientMappingFinalDisposition | null;
  targetIngredientCode: string | null;
  targetIngredientName: string | null;
  decisionReason: string | null;
  reviewedAt: string;
  availableActions: IngredientMappingAction[];
};

type BackendActionResult = {
  pending_code: string;
  normalized_source_name: string;
  status: IngredientMappingDecisionStatus;
  final_disposition: IngredientMappingFinalDisposition | null;
  target_ingredient_code: string | null;
  target_ingredient_name: string | null;
  decision_reason: string | null;
  reviewed_at: string;
  available_actions: IngredientMappingAction[];
};

const adaptActionResult = (result: BackendActionResult): IngredientMappingActionResult => ({
  pendingCode: result.pending_code,
  normalizedSourceName: result.normalized_source_name,
  status: result.status,
  finalDisposition: result.final_disposition,
  targetIngredientCode: result.target_ingredient_code,
  targetIngredientName: result.target_ingredient_name,
  decisionReason: result.decision_reason,
  reviewedAt: formatKstDateTime(result.reviewed_at) ?? result.reviewed_at,
  availableActions: result.available_actions
});

const postDecision = async (
  pendingCode: string,
  action: "approve" | "hold" | "reject" | "reopen",
  body: Record<string, unknown>
): Promise<IngredientMappingActionResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/ingredient-mappings/${encodeURIComponent(pendingCode)}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }
  );
  return adaptActionResult(await parseJson<BackendActionResult>(response));
};

export const approveIngredientMapping = (
  pendingCode: string,
  normalizedSourceName: string,
  targetIngredientCode: string,
  decisionReason: string | null
): Promise<IngredientMappingActionResult> =>
  postDecision(pendingCode, "approve", {
    normalized_source_name: normalizedSourceName,
    target_ingredient_code: targetIngredientCode,
    ...(decisionReason ? { decision_reason: decisionReason } : {})
  });

export const holdIngredientMapping = (
  pendingCode: string,
  normalizedSourceName: string,
  decisionReason: string
): Promise<IngredientMappingActionResult> =>
  postDecision(pendingCode, "hold", {
    normalized_source_name: normalizedSourceName,
    decision_reason: decisionReason
  });

export const rejectIngredientMapping = (
  pendingCode: string,
  normalizedSourceName: string,
  decisionReason: string,
  finalDisposition: IngredientMappingNonMappingFinalDisposition,
  evidenceSourceUrl: string | null,
  sourceReference: string | null
): Promise<IngredientMappingActionResult> =>
  postDecision(pendingCode, "reject", {
    normalized_source_name: normalizedSourceName,
    decision_reason: decisionReason,
    final_disposition: finalDisposition,
    ...(evidenceSourceUrl ? { evidence_source_url: evidenceSourceUrl } : {}),
    ...(sourceReference ? { source_reference: sourceReference } : {})
  });

export const reopenIngredientMapping = (
  pendingCode: string,
  normalizedSourceName: string,
  decisionReason: string
): Promise<IngredientMappingActionResult> =>
  postDecision(pendingCode, "reopen", {
    normalized_source_name: normalizedSourceName,
    decision_reason: decisionReason
  });

export type IngredientMappingBulkApprovalResult = {
  batchReference: string;
  approvedCount: number;
  items: IngredientMappingActionResult[];
};

type BackendBulkApprovalResult = {
  batch_reference: string;
  approved_count: number;
  items: BackendActionResult[];
};

export const approveKciaAliasExactMappings = async (
  items: IngredientMappingBulkApprovalPreviewItem[]
): Promise<IngredientMappingBulkApprovalResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/bulk-approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      confirmed_count: items.length,
      items: items.map((item) => ({
        pending_code: item.pendingCode,
        normalized_source_name: item.normalizedSourceName,
        target_ingredient_code: item.targetIngredientCode
      }))
    })
  });
  const body = await parseJson<BackendBulkApprovalResult>(response);
  return {
    batchReference: body.batch_reference,
    approvedCount: body.approved_count,
    items: body.items.map(adaptActionResult)
  };
};

// --- canonical 검색 (승인 target 선택용, §6) -------------------------------

export type CanonicalIngredientSearchItem = {
  ingredientCode: string;
  nameKo: string;
  nameEn: string | null;
  normalizedName: string | null;
  sourceUrl: string | null;
};

export type CanonicalIngredientSearchResult = {
  items: CanonicalIngredientSearchItem[];
  nextCursor: string | null;
};

type BackendCanonicalSearchItem = {
  ingredient_code: string;
  name_ko: string;
  name_en: string | null;
  normalized_name: string | null;
  source_url: string | null;
};

type BackendCanonicalSearchResponse = {
  items: BackendCanonicalSearchItem[];
  next_cursor: string | null;
};

export const searchCanonicalIngredients = async (
  q: string,
  limit = 20,
  cursor: string | null = null
): Promise<CanonicalIngredientSearchResult> => {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/ingredients/search?${params.toString()}`
  );
  const body = await parseJson<BackendCanonicalSearchResponse>(response);
  return {
    items: body.items.map((item) => ({
      ingredientCode: item.ingredient_code,
      nameKo: item.name_ko,
      nameEn: item.name_en,
      normalizedName: item.normalized_name,
      sourceUrl: item.source_url
    })),
    nextCursor: body.next_cursor
  };
};
