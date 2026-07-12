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
