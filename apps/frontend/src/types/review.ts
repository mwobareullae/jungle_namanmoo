export type ReviewableOrderItem = {
  order_item_id: number;
  order_code: string;
  product_id: string;
  product_name: string;
  brand_name: string;
  thumbnail_storage_key: string | null;
  order_item_status: string;
  review_id: string | null;
  review_status: string | null;
  can_write: boolean;
};

export type ReviewableOrderItemsResponse = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  items: ReviewableOrderItem[];
};

export type CreateProductReviewRequest = {
  order_item_id: number;
  rating: number;
  review_text: string;
  is_repurchase_review: boolean | null;
};

export type ProductReviewMutationResponse = {
  review_id: string;
  product_id: string;
  status: string;
};

export type MyProductReview = {
  review_id: string;
  rating: number | null;
  review_text: string | null;
  reviewed_at: string | null;
  is_repurchase_review: boolean | null;
  helpful_count: number;
  can_edit: boolean;
  can_delete: boolean;
};

export type MyProductReviewItem = {
  product_id: string;
  product_name: string;
  brand_name: string;
  thumbnail_storage_key: string | null;
  status: string;
  review: MyProductReview;
};

export type MyProductReviewsResponse = {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  items: MyProductReviewItem[];
};

export type UpdateProductReviewRequest = {
  rating: number;
  review_text: string;
  is_repurchase_review: boolean | null;
};
