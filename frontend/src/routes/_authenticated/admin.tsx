import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { AdminGate } from "@/components/admin/AdminLayout";
import { api } from "@/lib/api";
import type { AdminData } from "@/lib/data/admin-types";

const searchSchema = z.object({ chat: z.string().optional() });

export const Route = createFileRoute("/_authenticated/admin")({
  validateSearch: searchSchema,
  loader: async ({ context: { queryClient } }) => {
    try {
      await queryClient.ensureQueryData({
        queryKey: ["admin-data"],
        queryFn: () => api.get<AdminData>("/portal-admin/data"),
        staleTime: 30_000,
      });
    } catch {
      // Non-admin user — AdminGate shows the restricted-access UI
    }
  },
  component: AdminGate,
});
