import type {
  CreateProductReviewRequest,
  MyProductReviewsResponse,
  ProductReviewMutationResponse,
  ReviewableOrderItemsResponse,
  UpdateProductReviewRequest
} from "../types/review";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

export const getReviewableOrderItems = (page = 1, pageSize = 50) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return fetchWithTimeout(`${API_BASE_URL}/me/reviewable-order-items?${params.toString()}`).then((response) =>
    parseJson<ReviewableOrderItemsResponse>(response)
  );
};

export const createProductReview = (productId: string, request: CreateProductReviewRequest) =>
  fetchWithTimeout(`${API_BASE_URL}/products/${encodeURIComponent(productId)}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  }).then((response) => parseJson<ProductReviewMutationResponse>(response));

export const getMyProductReviews = (page = 1, pageSize = 20) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return fetchWithTimeout(`${API_BASE_URL}/me/reviews?${params.toString()}`).then((response) =>
    parseJson<MyProductReviewsResponse>(response)
  );
};

export const updateProductReview = (reviewId: string, request: UpdateProductReviewRequest) =>
  fetchWithTimeout(`${API_BASE_URL}/reviews/${encodeURIComponent(reviewId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  }).then((response) => parseJson<ProductReviewMutationResponse>(response));

export const deleteProductReview = (reviewId: string) =>
  fetchWithTimeout(`${API_BASE_URL}/reviews/${encodeURIComponent(reviewId)}`, {
    method: "DELETE"
  }).then((response) => parseJson<ProductReviewMutationResponse>(response));
