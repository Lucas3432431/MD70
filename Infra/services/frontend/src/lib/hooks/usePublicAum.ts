import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface AumData {
  aum: number;
  aum_current: number;
  rate_per_second: number;
}

export function usePublicAum() {
  return useQuery<AumData>({
    queryKey: ["public-aum"],
    queryFn: () => api.get<AumData>("/public/aum"),
    staleTime: 5 * 60_000,
    retry: false,
  });
}
