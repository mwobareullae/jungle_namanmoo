export type UserAddressCreateRequest = {
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2: string;
  delivery_memo?: string | null;
  is_default?: boolean;
};

export type UserAddressUpdateRequest = {
  recipient_name?: string;
  phone?: string;
  postal_code?: string;
  address1?: string;
  address2?: string;
  delivery_memo?: string | null;
  is_default?: boolean | null;
};

export type UserAddress = {
  id: number;
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
