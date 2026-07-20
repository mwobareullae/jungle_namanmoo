import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

export type AdminImageBulkLinkRowInput = {
  importSku: string;
  imageType: "thumbnail" | "detail";
  displayOrder: number;
  storageKey: string;
};

export type AdminImageBulkLinkRowResult = {
  rowNumber: number;
  importSku: string | null;
  status: "UPDATED" | "SKIPPED" | "FAILED";
  productCode: string | null;
  field: string | null;
  errorCode: string | null;
  message: string | null;
};

export type AdminImageBulkLinkResult = {
  summary: {
    total: number;
    updated: number;
    skipped: number;
    failed: number;
  };
  rows: AdminImageBulkLinkRowResult[];
};

type BackendImageBulkLinkRowResult = {
  row_number: number;
  import_sku: string | null;
  status: "UPDATED" | "SKIPPED" | "FAILED";
  product_code: string | null;
  field: string | null;
  error_code: string | null;
  message: string | null;
};

type BackendImageBulkLinkResponse = {
  summary: AdminImageBulkLinkResult["summary"];
  rows: BackendImageBulkLinkRowResult[];
};

const adaptRow = (row: BackendImageBulkLinkRowResult): AdminImageBulkLinkRowResult => ({
  rowNumber: row.row_number,
  importSku: row.import_sku,
  status: row.status,
  productCode: row.product_code,
  field: row.field,
  errorCode: row.error_code,
  message: row.message
});

export const linkAdminProductImages = async (
  rows: AdminImageBulkLinkRowInput[]
): Promise<AdminImageBulkLinkResult> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/products/images/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rows: rows.map((row) => ({
        import_sku: row.importSku,
        image_type: row.imageType,
        display_order: row.displayOrder,
        storage_key: row.storageKey
      }))
    })
  });
  const body = await parseJson<BackendImageBulkLinkResponse>(response);
  return { summary: body.summary, rows: body.rows.map(adaptRow) };
};
