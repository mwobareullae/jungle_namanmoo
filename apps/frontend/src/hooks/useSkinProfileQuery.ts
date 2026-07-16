import { useQuery } from "@tanstack/react-query";
import { getMySkinProfile } from "../lib/profileApi";

export const skinProfileQueryKey = (userId: number | null) => ["skin-profile", userId] as const;

export const useSkinProfileQuery = (userId: number | null, enabled = true) => useQuery({
  queryKey: skinProfileQueryKey(userId),
  queryFn: getMySkinProfile,
  enabled: enabled && userId !== null,
  staleTime: Infinity,
  gcTime: 30 * 60_000,
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  retry: false,
});
