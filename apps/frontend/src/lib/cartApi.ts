import type {
  CartItemAddRequest,
  CartItemUpdateRequest,
  CartMergeResponse,
  CartResponse,
  CheckoutPreviewRequest,
  CheckoutPreviewResponse,
  DeleteCartItemResponse,
  DeleteCartItemsResponse,
} from "../types/cart";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

const requestCartApi = async <T>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}${path}`, options);
  return parseJson<T>(response);
};

export const getCart = (): Promise<CartResponse> => {
  return requestCartApi<CartResponse>("/cart");
};

export const addCartItem = (request: CartItemAddRequest): Promise<CartResponse> => {
  return requestCartApi<CartResponse>("/cart/items", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
};

export const updateCartItem = (
  itemId: number,
  request: CartItemUpdateRequest
): Promise<CartResponse> => {
  return requestCartApi<CartResponse>(`/cart/items/${itemId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
};

export const deleteCartItem = (itemId: number): Promise<DeleteCartItemResponse> => {
  return requestCartApi<DeleteCartItemResponse>(`/cart/items/${itemId}`, {
    method: "DELETE",
  });
};

export const deleteCartItems = (cartItemIds: number[]): Promise<DeleteCartItemsResponse> => {
  return requestCartApi<DeleteCartItemsResponse>("/cart/items/bulk", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cart_item_ids: cartItemIds }),
  });
};

export const mergeCart = (): Promise<CartMergeResponse> => {
  return requestCartApi<CartMergeResponse>("/cart/merge", {
    method: "POST",
  });
};

export const previewCheckout = (
  request: CheckoutPreviewRequest
): Promise<CheckoutPreviewResponse> => {
  return requestCartApi<CheckoutPreviewResponse>("/checkout/preview", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
};
