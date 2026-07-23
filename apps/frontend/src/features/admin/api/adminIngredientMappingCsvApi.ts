import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

export type IngredientMappingCsvAction = "MAP_EXISTING" | "CREATE_AND_MAP";

export type IngredientMappingCsvRowInput = {
  rowNumber: number;
  action: IngredientMappingCsvAction;
  pendingCode: string;
  normalizedSourceName: string;
  expectedConnectionCount: number;
  targetIngredientCode: string;
  targetNameKo: string | null;
  targetNameEn: string | null;
  decisionReason: string | null;
  sourceReference: string | null;
};

export type IngredientMappingCsvPreviewRow = {
  rowNumber: number;
  status: "VALID" | "INVALID" | "ALREADY_APPLIED";
  action: IngredientMappingCsvAction;
  pendingCode: string;
  normalizedSourceName: string;
  targetIngredientCode: string;
  targetIngredientName: string | null;
  expectedConnectionCount: number;
  currentConnectionCount: number;
  errorCode: string | null;
  message: string | null;
};

export type IngredientMappingCsvPreview = {
  previewDigest: string;
  summary: {
    total: number;
    valid: number;
    invalid: number;
    alreadyApplied: number;
    connectionCount: number;
  };
  rows: IngredientMappingCsvPreviewRow[];
};

export type IngredientMappingCsvApplyResult = {
  batchReference: string;
  total: number;
  applied: number;
  alreadyApplied: number;
  movedConnections: number;
  collapsedDuplicates: number;
  createdCanonicals: number;
  affectedProducts: number;
  reviewRefresh: "OK" | "FAILED" | "NOT_REQUIRED";
  searchReindexRequired: boolean;
};

type BackendCsvPreview = {
  preview_digest: string;
  summary: {
    total: number;
    valid: number;
    invalid: number;
    already_applied: number;
    connection_count: number;
  };
  rows: Array<{
    row_number: number;
    status: "VALID" | "INVALID" | "ALREADY_APPLIED";
    action: IngredientMappingCsvAction;
    pending_code: string;
    normalized_source_name: string;
    target_ingredient_code: string;
    target_ingredient_name: string | null;
    expected_connection_count: number;
    current_connection_count: number;
    error_code: string | null;
    message: string | null;
  }>;
};

type BackendCsvApplyResult = {
  batch_reference: string;
  total: number;
  applied: number;
  already_applied: number;
  moved_connections: number;
  collapsed_duplicates: number;
  created_canonicals: number;
  affected_products: number;
  review_refresh: "OK" | "FAILED" | "NOT_REQUIRED";
  search_reindex_required: boolean;
};

const toBackendRow = (row: IngredientMappingCsvRowInput) => ({
  row_number: row.rowNumber,
  action: row.action,
  pending_code: row.pendingCode,
  normalized_source_name: row.normalizedSourceName,
  expected_connection_count: row.expectedConnectionCount,
  target_ingredient_code: row.targetIngredientCode,
  target_name_ko: row.targetNameKo,
  target_name_en: row.targetNameEn,
  decision_reason: row.decisionReason,
  source_reference: row.sourceReference
});

const adaptPreview = (body: BackendCsvPreview): IngredientMappingCsvPreview => ({
  previewDigest: body.preview_digest,
  summary: {
    total: body.summary.total,
    valid: body.summary.valid,
    invalid: body.summary.invalid,
    alreadyApplied: body.summary.already_applied,
    connectionCount: body.summary.connection_count
  },
  rows: body.rows.map((row) => ({
    rowNumber: row.row_number,
    status: row.status,
    action: row.action,
    pendingCode: row.pending_code,
    normalizedSourceName: row.normalized_source_name,
    targetIngredientCode: row.target_ingredient_code,
    targetIngredientName: row.target_ingredient_name,
    expectedConnectionCount: row.expected_connection_count,
    currentConnectionCount: row.current_connection_count,
    errorCode: row.error_code,
    message: row.message
  }))
});

export async function downloadPendingIngredientMappingCsv(): Promise<Blob> {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/csv-export`);
  if (!response.ok) await parseJson<never>(response);
  return response.blob();
}

export async function previewIngredientMappingCsv(
  rows: IngredientMappingCsvRowInput[]
): Promise<IngredientMappingCsvPreview> {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/csv-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: rows.map(toBackendRow) })
  });
  return adaptPreview(await parseJson<BackendCsvPreview>(response));
}

export async function applyIngredientMappingCsv(
  rows: IngredientMappingCsvRowInput[],
  previewDigest: string,
  refreshPendingGroups: boolean
): Promise<IngredientMappingCsvApplyResult> {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/csv-apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rows: rows.map(toBackendRow),
      preview_digest: previewDigest,
      confirmed_count: rows.length,
      refresh_pending_groups: refreshPendingGroups
    })
  });
  const body = await parseJson<BackendCsvApplyResult>(response);
  return {
    batchReference: body.batch_reference,
    total: body.total,
    applied: body.applied,
    alreadyApplied: body.already_applied,
    movedConnections: body.moved_connections,
    collapsedDuplicates: body.collapsed_duplicates,
    createdCanonicals: body.created_canonicals,
    affectedProducts: body.affected_products,
    reviewRefresh: body.review_refresh,
    searchReindexRequired: body.search_reindex_required
  };
}

export async function refreshIngredientMappingPendingGroups(): Promise<void> {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/ingredient-mappings/csv-refresh`, {
    method: "POST"
  });
  await parseJson<{ status: "OK" }>(response);
}
