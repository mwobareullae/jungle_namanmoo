import type {
  DeleteUserAddressResponse,
  UserAddress,
  UserAddressCreateRequest,
  UserAddressesResponse,
  UserAddressUpdateRequest,
} from "../types/address";
import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

const requestAddressApi = async <T>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}${path}`, options);
  return parseJson<T>(response);
};

export const getAddresses = (): Promise<UserAddressesResponse> => {
  return requestAddressApi<UserAddressesResponse>("/me/addresses");
};

export const createAddress = (request: UserAddressCreateRequest): Promise<UserAddress> => {
  return requestAddressApi<UserAddress>("/me/addresses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
};

export const updateAddress = (
  addressId: number,
  request: UserAddressUpdateRequest,
): Promise<UserAddress> => {
  return requestAddressApi<UserAddress>(`/me/addresses/${addressId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
};

export const deleteAddress = (addressId: number): Promise<DeleteUserAddressResponse> => {
  return requestAddressApi<DeleteUserAddressResponse>(`/me/addresses/${addressId}`, {
    method: "DELETE",
  });
};
