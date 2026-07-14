import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";

// 관리자 상품 조회 API 레이어 (P1-M3-A, 조회 전용).
// 백엔드는 snake_case·영문 상태를 반환하고, 여기서 camelCase 로 변환한다.
// 계약: docs/admin/admin-m3a-product-crud-contract.md

export type AdminSalesStatus = "ON_SALE" | "SOLD_OUT" | "HIDDEN" | "UNKNOWN";
export type AdminStockStatus = "IN_STOCK" | "LOW_STOCK" | "SOLD_OUT" | "HIDDEN" | "UNKNOWN";

export type AdminProductAvailability = {
  salesStatus: AdminSalesStatus;
  stockStatus: AdminStockStatus;
  availableQuantity: number | null;
  inStock: boolean;
};

export type AdminProductRow = {
  productCode: string;
  name: string;
  brandCode: string;
  brand: string;
  categoryCode: string;
  categoryName: string;
  price: number | null;
  isActive: boolean;
  isRecommendable: boolean;
  availability: AdminProductAvailability;
  stockQuantity: number | null;
  imageCount: number;
  // 대표 이미지 storage_key(계약: 완성 CDN URL 조합은 프론트 책임). 없으면 "".
  thumbnailStorageKey: string;
  updatedAt: string;
};

export type AdminProductDetail = AdminProductRow & {
  sellerCode: string;
  sellerName: string;
  description: string | null;
  releasedAt: string | null;
  createdAt: string;
};

export type AdminProductPagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
};

export type AdminProductListResult = {
  items: AdminProductRow[];
  pagination: AdminProductPagination;
};

export type AdminProductQuery = {
  q?: string | null;
  brandCode?: string | null;
  categoryCode?: string | null;
  isActive?: boolean | null;
  salesStatus?: AdminSalesStatus | null;
  page?: number;
  pageSize?: number;
};

type BackendAvailability = {
  sales_status: AdminSalesStatus;
  stock_status: AdminStockStatus;
  available_quantity: number | null;
  in_stock: boolean;
};

type BackendProductListItem = {
  product_code: string;
  name: string;
  brand_code: string;
  brand: string;
  category_code: string;
  category_name: string;
  price: number | null;
  is_active: boolean;
  is_recommendable: boolean;
  availability: BackendAvailability;
  stock_quantity: number | null;
  image_count: number;
  thumbnail_url: string;
  updated_at: string;
};

type BackendProductDetail = BackendProductListItem & {
  seller_code: string;
  seller_name: string;
  description: string | null;
  released_at: string | null;
  created_at: string;
};

type BackendProductPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

type BackendProductListResponse = {
  items: BackendProductListItem[];
  pagination: BackendProductPagination;
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

const adaptAvailability = (availability: BackendAvailability): AdminProductAvailability => ({
  salesStatus: availability.sales_status,
  stockStatus: availability.stock_status,
  availableQuantity: availability.available_quantity,
  inStock: availability.in_stock
});

const adaptRow = (item: BackendProductListItem): AdminProductRow => ({
  productCode: item.product_code,
  name: item.name,
  brandCode: item.brand_code,
  brand: item.brand,
  categoryCode: item.category_code,
  categoryName: item.category_name,
  price: item.price,
  isActive: item.is_active,
  isRecommendable: item.is_recommendable,
  availability: adaptAvailability(item.availability),
  stockQuantity: item.stock_quantity,
  imageCount: item.image_count,
  thumbnailStorageKey: item.thumbnail_url,
  updatedAt: formatKstDateTime(item.updated_at) ?? item.updated_at
});

const adaptDetail = (item: BackendProductDetail): AdminProductDetail => ({
  ...adaptRow(item),
  sellerCode: item.seller_code,
  sellerName: item.seller_name,
  description: item.description,
  releasedAt: formatKstDateTime(item.released_at),
  createdAt: formatKstDateTime(item.created_at) ?? item.created_at
});

export const getAdminProducts = async (query: AdminProductQuery = {}): Promise<AdminProductListResult> => {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.brandCode) params.set("brand_code", query.brandCode);
  if (query.categoryCode) params.set("category_code", query.categoryCode);
  if (query.isActive !== null && query.isActive !== undefined) params.set("is_active", String(query.isActive));
  if (query.salesStatus) params.set("sales_status", query.salesStatus);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));

  const queryString = params.toString();
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/products${queryString ? `?${queryString}` : ""}`
  );
  const body = await parseJson<BackendProductListResponse>(response);
  return {
    items: body.items.map(adaptRow),
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

export const getAdminProductDetail = async (productCode: string): Promise<AdminProductDetail> => {
  const response = await fetchWithTimeout(
    `${ADMIN_API_BASE}/products/${encodeURIComponent(productCode)}`
  );
  return adaptDetail(await parseJson<BackendProductDetail>(response));
};
