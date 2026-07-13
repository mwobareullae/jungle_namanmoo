export type OrderPaymentProvider = "TOSS";

export type CreateOrderShippingAddress = {
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2?: string | null;
  delivery_memo?: string | null;
  save_to_address_book?: boolean;
  set_as_default?: boolean;
};

export type CreateOrderRequest = {
  cart_item_ids: number[];
  address_id?: number | null;
  shipping_address?: CreateOrderShippingAddress;
  payment_provider: OrderPaymentProvider;
};

export type CreateOrderPayment = {
  payment_code: string;
  provider: OrderPaymentProvider;
  status: string;
  amount: number;
  currency: string;
};

export type CreateOrderResponse = {
  order_code: string;
  status: string;
  payment: CreateOrderPayment;
  subtotal: number;
  shipping_fee: number;
  discount_total: number;
  total: number;
  currency: string;
  payment_expires_at: string;
};

export type TossPaymentConfirmRequest = {
  payment_key: string;
  order_code: string;
  amount: number;
};

export type TossPaymentConfirmResponse = {
  order_code: string;
  payment_code: string;
  order_status: string;
  payment_status: string;
  approved_at?: string | null;
};

export type MockPaymentConfirmResponse = {
  order_code: string;
  payment_code: string;
  order_status: string;
  payment_status: string;
  approved_at?: string | null;
  failed_at?: string | null;
};

export type OrderCancelResponse = {
  order_code: string;
  status: string;
};

export type OrderListItem = {
  order_code: string;
  status: string;
  total: number;
  currency: string;
  item_count: number;
  ordered_at: string;
  paid_at?: string | null;
  thumbnail_storage_key?: string | null;
  title: string;
};

export type OrderListResponse = {
  items: OrderListItem[];
  next_cursor?: string | null;
};

export type OrderDetailPayment = {
  payment_code: string;
  provider: OrderPaymentProvider;
  status: string;
  approved_at?: string | null;
};

export type OrderDetailItem = {
  id: number;
  product_id: string;
  product_name: string;
  brand_name: string;
  seller_name: string;
  thumbnail_storage_key?: string | null;
  unit_price: number;
  quantity: number;
  line_subtotal: number;
  line_discount_amount: number;
  line_total: number;
  currency: string;
  status: string;
  source?: string | null;
  recommendation_id?: string | null;
  recommendation_rank?: number | null;
};

export type OrderDetailShippingAddress = {
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2?: string | null;
  delivery_memo?: string | null;
};

export type OrderDetailShippingGroup = {
  seller_name: string;
  item_subtotal: number;
  shipping_fee: number;
  free_shipping_threshold?: number | null;
};

export type OrderDetailResponse = {
  order_code: string;
  status: string;
  subtotal: number;
  shipping_fee: number;
  discount_total: number;
  total: number;
  currency: string;
  ordered_at: string;
  paid_at?: string | null;
  payment_expires_at?: string | null;
  payment: OrderDetailPayment;
  items: OrderDetailItem[];
  shipping_address?: OrderDetailShippingAddress | null;
  shipping_groups: OrderDetailShippingGroup[];
};
