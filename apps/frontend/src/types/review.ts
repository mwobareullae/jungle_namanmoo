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
  review: MyProductReview | null;
  review_id: string;
  product_id: string;
  status: string;
  review_summary: ProductReviewSummaryResponse;
};

export type ProductReviewSummaryResponse = {
  review_count: number;
  average_rating: number | null;
  rating_distribution: Record<string, number>;
  general_review_count: number;
  month_use_review_count: number;
  repurchase_known_count: number;
  repurchase_review_count: number;
  repurchase_rate: number | null;
  profile_labeled_review_count: number;
  last_reviewed_at: string | null;
};

export type ProductReviewAuthor = {
  display_name: string;
  profile_image_url: string | null;
};

export type ProductReviewProfileLabel = {
  dimension: string;
  value_code: string;
  display_label: string;
};

export type ProductReviewMedia = {
  media_type: string;
  url: string;
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
  verified_purchase?: boolean | null;
  updated_at?: string | null;
  is_mine?: boolean;
  badges?: string[];
  author?: ProductReviewAuthor | null;
  profile_labels?: ProductReviewProfileLabel[];
  media?: ProductReviewMedia[];
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
