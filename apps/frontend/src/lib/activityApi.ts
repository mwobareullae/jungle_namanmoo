import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";
import { getProductImageUrl } from "./imageUrls";

type BackendActivityProduct = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
  in_stock: boolean;
};

type BackendWishlistItem = {
  id: number;
  product_id: string;
  added_at: string;
  product: BackendActivityProduct;
};

type BackendRecentViewItem = {
  id: number;
  product_id: string;
  viewed_at: string;
  product: BackendActivityProduct;
};

type BackendWishlistResponse = {
  items: BackendWishlistItem[];
};

type BackendRecentViewsResponse = {
  items: BackendRecentViewItem[];
};

type BackendDeleteResponse = {
  success: boolean;
};

type BackendActivityRequest = {
  product_id: string;
};

export type ActivityProductItem = {
  id: string;
  productId: string;
  brand: string;
  name: string;
  price: number;
  thumbnailUrl: string | null;
  dateLabel?: string;
  rawDate?: string;
  tags: string[];
  isWished: boolean;
  salesStatus: string;
  stockStatus: string;
  availableQuantity: number | null;
  inStock: boolean;
};

const formatActivityDateLabel = (dateText: string) => {
  const date = new Date(dateText);

  if (Number.isNaN(date.getTime())) {
    return undefined;
  }

  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";

  return `${year}.${month}.${day}.`;
};

const mapProductTags = (product: BackendActivityProduct) =>
  [product.category_name, product.category_code].filter(
    (value, index, values): value is string =>
      typeof value === "string" && value.trim().length > 0 && values.indexOf(value) === index
  );

const mapActivityProduct = (
  item: BackendWishlistItem | BackendRecentViewItem,
  options: { dateText?: string; isWished: boolean }
): ActivityProductItem => ({
  id: String(item.id),
  productId: item.product.product_id || item.product_id,
  brand: item.product.brand,
  name: item.product.name,
  price: item.product.lowest_price,
  thumbnailUrl: getProductImageUrl(item.product.thumbnail_url, "w400") || null,
  dateLabel: options.dateText ? formatActivityDateLabel(options.dateText) : undefined,
  rawDate: options.dateText,
  tags: mapProductTags(item.product),
  isWished: options.isWished,
  salesStatus: item.product.sales_status,
  stockStatus: item.product.stock_status,
  availableQuantity: item.product.available_quantity,
  inStock: item.product.in_stock
});

export const getMyWishlist = async (limit = 50): Promise<ActivityProductItem[]> => {
  const query = new URLSearchParams({ limit: String(limit) });
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/wishlist?${query}`);
  const data = await parseJson<BackendWishlistResponse>(response);

  return data.items.map((item) => mapActivityProduct(item, { dateText: item.added_at, isWished: true }));
};

export const addMyWishlistItem = async (productId: string): Promise<ActivityProductItem> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/wishlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_id: productId } satisfies BackendActivityRequest)
  });
  const data = await parseJson<BackendWishlistItem>(response);

  return mapActivityProduct(data, { isWished: true });
};

export const deleteMyWishlistItem = async (productId: string) => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/wishlist/${encodeURIComponent(productId)}`, {
    method: "DELETE"
  });
  return parseJson<BackendDeleteResponse>(response);
};

export const getMyRecentProducts = async (limit = 50): Promise<ActivityProductItem[]> => {
  const query = new URLSearchParams({ limit: String(limit) });
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/recent?${query}`);
  const data = await parseJson<BackendRecentViewsResponse>(response);

  return data.items.map((item) =>
    mapActivityProduct(item, {
      dateText: item.viewed_at,
      isWished: false
    })
  );
};

export const addMyRecentProduct = async (productId: string): Promise<ActivityProductItem> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/recent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_id: productId } satisfies BackendActivityRequest)
  });
  const data = await parseJson<BackendRecentViewItem>(response);

  return mapActivityProduct(data, {
    dateText: data.viewed_at,
    isWished: false
  });
};

export const deleteMyRecentProduct = async (productId: string) => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/recent/${encodeURIComponent(productId)}`, {
    method: "DELETE"
  });
  return parseJson<BackendDeleteResponse>(response);
};
