export type CartItemAddRequest = {
  product_id: string;
  quantity?: number;
  source?: string | null;
  recommendation_id?: string | null;
  recommendation_rank?: number | null;
};

export type CartItemUpdateRequest = {
  quantity: number;
};

export type CartProduct = {
  product_id: string;
  brand: string;
  name: string;
  category_code: string;
  category_name: string;
  thumbnail_url: string;
  current_price: number | null;
  currency: string;
  sales_status: string;
  stock_status: string;
  available_quantity: number | null;
};

export type CartWarning = {
  code: string;
  message: string;
  severity: "INFO" | "BLOCKING";
  product_id?: string | null;
  item_id?: number | null;
};

export type CartItem = {
  id: number;
  product_id: string;
  quantity: number;
  unit_price_snapshot: number;
  current_unit_price: number | null;
  currency: string;
  line_subtotal: number;
  price_changed: boolean;
  source?: string | null;
  recommendation_id?: string | null;
  recommendation_rank?: number | null;
  added_at: string;
  updated_at: string;
  product: CartProduct;
};

export type CartResponse = {
  cart_id: number | null;
  owner_type: "user" | "anonymous";
  items: CartItem[];
  total_quantity: number;
  subtotal: number;
  currency: string;
  warnings: CartWarning[];
};

export type DeleteCartItemResponse = {
  success: boolean;
  cart: CartResponse;
};

export type DeleteCartItemsResponse = {
  success: boolean;
  deleted_item_ids: number[];
  cart: CartResponse;
};

export type CartMergeResponse = {
  merged: boolean;
  cart: CartResponse;
};

export type CheckoutPreviewRequest = {
  cart_item_ids: number[];
  address_id?: number | null;
};

export type CheckoutShippingGroup = {
  seller_code: string;
  seller_name: string;
  item_subtotal: number;
  base_shipping_fee: number;
  free_shipping_threshold?: number | null;
  shipping_fee: number;
};

export type CheckoutPreviewResponse = {
  cart_id: number;
  items: CartItem[];
  subtotal: number;
  shipping_fee: number;
  shipping_groups: CheckoutShippingGroup[];
  total: number;
  currency: string;
  can_checkout: boolean;
  warnings: CartWarning[];
};
