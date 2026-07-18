import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

export type AdminBulkImportRowInput = {
  importSku: string;
  productName: string;
  brandName: string;
  categoryName: string;
  price: number;
  stockQuantity: number;
  ingredientsRaw: string;
};

export type AdminBulkImportIngredientSummary = {
  inputCount: number;
  savedCount: number;
  canonicalCount: number;
  pendingCount: number;
  duplicateCount: number;
  createdPendingCount: number;
};

export type AdminBulkImportRowResult = {
  rowNumber: number;
  importSku: string | null;
  status: "CREATED" | "SKIPPED" | "FAILED";
  productCode: string | null;
  existingProductCode: string | null;
  field: string | null;
  errorCode: string | null;
  message: string | null;
  ingredientSummary: AdminBulkImportIngredientSummary | null;
};

export type AdminBulkImportResult = {
  summary: {
    total: number;
    created: number;
    skipped: number;
    failed: number;
  };
  rows: AdminBulkImportRowResult[];
  reviewRefresh: "OK" | "FAILED" | "NOT_REQUIRED";
};

type BackendIngredientSummary = {
  input_count: number;
  saved_count: number;
  canonical_count: number;
  pending_count: number;
  duplicate_count: number;
  created_pending_count: number;
};

type BackendRowResult = {
  row_number: number;
  import_sku: string | null;
  status: "CREATED" | "SKIPPED" | "FAILED";
  product_code: string | null;
  existing_product_code: string | null;
  field: string | null;
  error_code: string | null;
  message: string | null;
  ingredient_summary: BackendIngredientSummary | null;
};

type BackendBulkImportResponse = {
  summary: {
    total: number;
    created: number;
    skipped: number;
    failed: number;
  };
  rows: BackendRowResult[];
  review_refresh: "OK" | "FAILED" | "NOT_REQUIRED";
  // 서버 운영·로그용 정보다. 관리자 브라우저 화면에는 전달하지 않는다.
  refresh_recovery_command: string | null;
};

const adaptIngredientSummary = (
  summary: BackendIngredientSummary | null,
): AdminBulkImportIngredientSummary | null =>
  summary
    ? {
        inputCount: summary.input_count,
        savedCount: summary.saved_count,
        canonicalCount: summary.canonical_count,
        pendingCount: summary.pending_count,
        duplicateCount: summary.duplicate_count,
        createdPendingCount: summary.created_pending_count,
      }
    : null;

const adaptRowResult = (row: BackendRowResult): AdminBulkImportRowResult => ({
  rowNumber: row.row_number,
  importSku: row.import_sku,
  status: row.status,
  productCode: row.product_code,
  existingProductCode: row.existing_product_code,
  field: row.field,
  errorCode: row.error_code,
  message: row.message,
  ingredientSummary: adaptIngredientSummary(row.ingredient_summary),
});

export const importAdminProducts = async (
  rows: AdminBulkImportRowInput[],
): Promise<AdminBulkImportResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/products/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rows: rows.map((row) => ({
        import_sku: row.importSku,
        product_name: row.productName,
        brand_name: row.brandName,
        category_name: row.categoryName,
        price: row.price,
        stock_quantity: row.stockQuantity,
        ingredients_raw: row.ingredientsRaw,
      })),
    }),
  });
  const body = await parseJson<BackendBulkImportResponse>(response);
  return {
    summary: body.summary,
    rows: body.rows.map(adaptRowResult),
    reviewRefresh: body.review_refresh,
  };
};
