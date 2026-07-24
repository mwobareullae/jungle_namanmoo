import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";
import type { AdminProductPagination } from "./adminProductApi";

export type AdminInventoryAvailability = {
  salesStatus: "ON_SALE" | "SOLD_OUT" | "HIDDEN" | null;
  stockStatus: "IN_STOCK" | "LOW_STOCK" | "SOLD_OUT" | "HIDDEN" | "UNKNOWN";
  availableQuantity: number | null;
  inStock: boolean;
};

export type AdminInventoryPriceItem = {
  productCode: string;
  name: string;
  brandCode: string;
  brand: string;
  categoryCode: string;
  categoryName: string;
  isActive: boolean;
  price: number | null;
  stockQuantity: number | null;
  reservedQuantity: number | null;
  safetyStock: number | null;
  availability: AdminInventoryAvailability;
  updatedAt: string;
};

export type AdminInventoryMovement = {
  movementType: string;
  quantityDelta: number;
  stockAfter: number;
  reason: string | null;
  referenceType: string | null;
  referenceId: string | null;
  createdAt: string;
};

export type AdminInventoryFilters = {
  query?: string;
  brandCode?: string;
  categoryCode?: string;
  isActive?: boolean;
  salesStatus?: "ON_SALE" | "SOLD_OUT" | "HIDDEN";
  stockStatus?: "IN_STOCK" | "LOW_STOCK" | "SOLD_OUT" | "HIDDEN";
  page?: number;
  pageSize?: number;
};

export type AdminInventoryListResult = {
  items: AdminInventoryPriceItem[];
  pagination: AdminProductPagination;
};

export type AdminInventorySummaryFilters = {
  query?: string;
  brandCode?: string;
  categoryCode?: string;
  isActive?: boolean;
};

export type AdminInventorySummary = {
  lowStockCount: number;
  hiddenCount: number;
  unknownCount: number;
};

export type AdminInventoryAdjustmentResult = {
  changed: boolean;
  productCode: string;
  stockQuantity: number;
  reservedQuantity: number;
  safetyStock: number;
  availability: AdminInventoryAvailability;
  updatedAt: string;
  movement: AdminInventoryMovement | null;
};

export type AdminInventoryPriceUpdateResult = {
  changed: boolean;
  productCode: string;
  price: number;
  currency: string;
  isLowest: boolean;
  collectedAt: string;
  updatedAt: string;
};

export type AdminProductSaleStartResult = {
  productCode: string;
  salesStatus: "ON_SALE";
  isActive: true;
  startedAt: string;
};

type BackendAvailability = {
  sales_status: AdminInventoryAvailability["salesStatus"];
  stock_status: AdminInventoryAvailability["stockStatus"];
  available_quantity: number | null;
  in_stock: boolean;
};

type BackendInventoryPriceItem = {
  product_code: string;
  name: string;
  brand_code: string;
  brand: string;
  category_code: string;
  category_name: string;
  is_active: boolean;
  price: number | null;
  stock_quantity: number | null;
  reserved_quantity: number | null;
  safety_stock: number | null;
  availability: BackendAvailability;
  updated_at: string;
};

type BackendInventoryMovement = {
  movement_type: string;
  quantity_delta: number;
  stock_after: number;
  reason: string | null;
  reference_type: string | null;
  reference_id: string | null;
  created_at: string;
};

type BackendPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

type BackendInventoryListResponse = {
  items: BackendInventoryPriceItem[];
  pagination: BackendPagination;
};

type BackendInventorySummaryResponse = {
  low_stock_count: number;
  hidden_count: number;
  unknown_count: number;
};

type BackendInventoryHistoryResponse = {
  product_code: string;
  items: BackendInventoryMovement[];
};

type BackendInventoryAdjustmentResponse = {
  changed: boolean;
  product_code: string;
  stock_quantity: number;
  reserved_quantity: number;
  safety_stock: number;
  availability: BackendAvailability;
  updated_at: string;
  movement: BackendInventoryMovement | null;
};

type BackendInventoryPriceUpdateResponse = {
  changed: boolean;
  product_code: string;
  price: number;
  currency: string;
  is_lowest: boolean;
  collected_at: string;
  updated_at: string;
};

type BackendProductSaleStartResponse = {
  product_code: string;
  sales_status: "ON_SALE";
  is_active: true;
  started_at: string;
};

const adaptAvailability = (availability: BackendAvailability): AdminInventoryAvailability => ({
  salesStatus: availability.sales_status,
  stockStatus: availability.stock_status,
  availableQuantity: availability.available_quantity,
  inStock: availability.in_stock
});

const adaptItem = (item: BackendInventoryPriceItem): AdminInventoryPriceItem => ({
  productCode: item.product_code,
  name: item.name,
  brandCode: item.brand_code,
  brand: item.brand,
  categoryCode: item.category_code,
  categoryName: item.category_name,
  isActive: item.is_active,
  price: item.price,
  stockQuantity: item.stock_quantity,
  reservedQuantity: item.reserved_quantity,
  safetyStock: item.safety_stock,
  availability: adaptAvailability(item.availability),
  updatedAt: item.updated_at
});

const adaptMovement = (movement: BackendInventoryMovement): AdminInventoryMovement => ({
  movementType: movement.movement_type,
  quantityDelta: movement.quantity_delta,
  stockAfter: movement.stock_after,
  reason: movement.reason,
  referenceType: movement.reference_type,
  referenceId: movement.reference_id,
  createdAt: movement.created_at
});

export const listAdminInventoryPrices = async (
  filters: AdminInventoryFilters
): Promise<AdminInventoryListResult> => {
  const params = new URLSearchParams();
  if (filters.query?.trim()) params.set("q", filters.query.trim());
  if (filters.brandCode) params.set("brand_code", filters.brandCode);
  if (filters.categoryCode) params.set("category_code", filters.categoryCode);
  if (filters.isActive !== undefined) params.set("is_active", String(filters.isActive));
  if (filters.salesStatus) params.set("sales_status", filters.salesStatus);
  if (filters.stockStatus) params.set("stock_status", filters.stockStatus);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.pageSize) params.set("page_size", String(filters.pageSize));

  const query = params.toString();
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/inventory${query ? `?${query}` : ""}`);
  const body = await parseJson<BackendInventoryListResponse>(response);
  return {
    items: body.items.map(adaptItem),
    pagination: {
      page: body.pagination.page,
      pageSize: body.pagination.page_size,
      totalItems: body.pagination.total_items,
      totalPages: body.pagination.total_pages,
      hasNext: body.pagination.has_next,
      hasPrev: body.pagination.has_prev
    }
  };
};

export const getAdminInventorySummary = async (
  filters: AdminInventorySummaryFilters
): Promise<AdminInventorySummary> => {
  const params = new URLSearchParams();
  if (filters.query?.trim()) params.set("q", filters.query.trim());
  if (filters.brandCode) params.set("brand_code", filters.brandCode);
  if (filters.categoryCode) params.set("category_code", filters.categoryCode);
  if (filters.isActive !== undefined) params.set("is_active", String(filters.isActive));

  const query = params.toString();
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/inventory/summary${query ? `?${query}` : ""}`);
  const body = await parseJson<BackendInventorySummaryResponse>(response);
  return {
    lowStockCount: body.low_stock_count,
    hiddenCount: body.hidden_count,
    unknownCount: body.unknown_count
  };
};

export const getAdminInventoryHistory = async (
  productCode: string
): Promise<AdminInventoryMovement[]> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/inventory/${encodeURIComponent(productCode)}/history`
  );
  const body = await parseJson<BackendInventoryHistoryResponse>(response);
  return body.items.map(adaptMovement);
};

export const adjustAdminInventoryStock = async (
  productCode: string,
  stockQuantity: number,
  reason: string
): Promise<AdminInventoryAdjustmentResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/inventory/${encodeURIComponent(productCode)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stock_quantity: stockQuantity, reason })
    }
  );
  const body = await parseJson<BackendInventoryAdjustmentResponse>(response);
  return {
    changed: body.changed,
    productCode: body.product_code,
    stockQuantity: body.stock_quantity,
    reservedQuantity: body.reserved_quantity,
    safetyStock: body.safety_stock,
    availability: adaptAvailability(body.availability),
    updatedAt: body.updated_at,
    movement: body.movement ? adaptMovement(body.movement) : null
  };
};

export const updateAdminInventoryPrice = async (
  productCode: string,
  price: number
): Promise<AdminInventoryPriceUpdateResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/inventory/${encodeURIComponent(productCode)}/price`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ price })
    }
  );
  const body = await parseJson<BackendInventoryPriceUpdateResponse>(response);
  return {
    changed: body.changed,
    productCode: body.product_code,
    price: body.price,
    currency: body.currency,
    isLowest: body.is_lowest,
    collectedAt: body.collected_at,
    updatedAt: body.updated_at
  };
};

export const startAdminProductSale = async (
  productCode: string
): Promise<AdminProductSaleStartResult> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/inventory/${encodeURIComponent(productCode)}/sale-start`,
    { method: "POST" }
  );
  const body = await parseJson<BackendProductSaleStartResponse>(response);
  return {
    productCode: body.product_code,
    salesStatus: body.sales_status,
    isActive: body.is_active,
    startedAt: body.started_at
  };
};
