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
