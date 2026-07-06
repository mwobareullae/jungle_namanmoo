export type UserAddressCreateRequest = {
  address_name?: string | null;
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2?: string | null;
  delivery_memo?: string | null;
  is_default?: boolean;
};

export type UserAddressUpdateRequest = {
  address_name?: string | null;
  recipient_name?: string;
  phone?: string;
  postal_code?: string;
  address1?: string;
  address2?: string | null;
  delivery_memo?: string | null;
  is_default?: boolean | null;
};

export type UserAddress = {
  id: number;
  address_name?: string | null;
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2: string | null;
  delivery_memo: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
};

export type UserAddressesResponse = {
  items: UserAddress[];
};

export type DeleteUserAddressResponse = {
  success: boolean;
};
