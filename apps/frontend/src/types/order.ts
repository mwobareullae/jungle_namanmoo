export type OrderPaymentProvider = "MOCK" | "TOSS";

export type CreateOrderShippingAddress = {
  address_name?: string | null;
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
