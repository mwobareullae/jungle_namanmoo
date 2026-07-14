export type PopularProductItem = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number;
  purchase_url: string | null;
  popularity_score: number;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
  in_stock: boolean;
};

export type PopularProductsResponse = {
  window_days: number;
  items: PopularProductItem[];
};

export type ProductListingSort =
  | "popular"
  | "newest"
  | "price_low"
  | "price_high"
  | "rating"
  | "review_count";

export type ProductListingItem = {
  product_id: string;
  brand_code: string;
  brand: string;
  name: string;
  category_code: string;
  category_group: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number | null;
  rating: number | null;
  review_count: number;
  sales_status: string;
  in_stock: boolean;
  stock_status: string;
  available_quantity: number | null;
  released_at: string | null;
};

export type ProductListingPagination = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

export type ProductListingResponse = {
  items: ProductListingItem[];
  pagination: ProductListingPagination;
  applied_filters: {
    brand_codes: string[];
    category_codes: string[];
    category_groups: string[];
    min_price: number | null;
    max_price: number | null;
    min_rating: number | null;
    in_stock: boolean | null;
  };
  sort: ProductListingSort;
};

export type BrandListItem = {
  code: string;
  name: string;
  product_count: number;
};

export type BrandListResponse = {
  items: BrandListItem[];
};

export type CategoryListItem = {
  code: string;
  name: string;
  group: string;
  group_name: string;
  product_count: number;
};

export type CategoryListResponse = {
  items: CategoryListItem[];
};

export type CatalogSearchSort =
  | "relevance"
  | "popular"
  | "newest"
  | "price_asc"
  | "price_desc"
  | "rating";

export type CatalogSearchItem = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_group: string;
  category_name: string;
  thumbnail_url: string;
  lowest_price: number | null;
  rating: number | null;
  review_count: number;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
  in_stock: boolean;
};

export type CatalogSearchResponse = {
  query: string;
  corrected_query: string | null;
  items: CatalogSearchItem[];
  pagination: ProductListingPagination;
  facets: {
    brands: { value: string; label: string; count: number }[];
    categories: { value: string; label: string; count: number }[];
    price_ranges: { value: string; label: string; count: number }[];
    availability: { value: string; label: string; count: number }[];
  };
  applied_filters: {
    brands: string[];
    categories: string[];
    min_price: number | null;
    max_price: number | null;
    min_rating: number | null;
    in_stock: boolean | null;
  };
  sort: CatalogSearchSort;
};

export type CatalogSuggestionItem = {
  text: string;
  type: "PRODUCT" | "BRAND" | "CATEGORY" | "CORRECTION";
  product_id: string | null;
};

export type CatalogSuggestionsResponse = {
  query: string;
  items: CatalogSuggestionItem[];
};
