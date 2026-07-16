import { useQuery } from "@tanstack/react-query";
import { getCart } from "../lib/cartApi";

export const cartQueryKey = (userId: number | null) => ["cart", userId] as const;

export const useCartQuery = (userId: number | null, enabled = true) => useQuery({
  queryKey: cartQueryKey(userId),
  queryFn: getCart,
  enabled,
  staleTime: 30_000,
  retry: false,
});
