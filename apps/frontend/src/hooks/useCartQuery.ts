import { useQuery } from "@tanstack/react-query";
import { getCart } from "../lib/cartApi";

export const cartQueryKey = (userId: number | null) => ["cart", userId] as const;

export const useCartQuery = (userId: number | null) => useQuery({
  queryKey: cartQueryKey(userId),
  queryFn: getCart,
  enabled: userId !== null,
  staleTime: 30_000,
  retry: false,
});
