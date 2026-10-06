import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AdminData, LeadStatus, PurchaseStatus } from "@/lib/data/admin-types";

export function useAdminData() {
  return useQuery<AdminData>({
    queryKey: ["admin-data"],
    queryFn: () => api.get<AdminData>("/portal-admin/data"),
    staleTime: 30_000,
    retry: false,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post("/portal-admin/projects", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function usePatchProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      api.patch(`/portal-admin/projects/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function usePatchLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; status?: LeadStatus; notes?: string } & Record<string, unknown>) =>
      api.patch(`/portal-admin/leads/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useCreateLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post("/portal-admin/leads", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useDeleteLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/portal-admin/leads/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function usePatchPurchase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { id: string } & Record<string, unknown>) => {
      const { id, ...body } = patch;
      return api.patch(`/portal-admin/purchases/${id}`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useCreatePurchase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post("/portal-admin/purchases", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useDeletePurchase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/portal-admin/purchases/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useCreateMovement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post("/portal-admin/movements", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function usePatchMovement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { id: string } & Record<string, unknown>) => {
      const { id, ...body } = patch;
      return api.patch(`/portal-admin/movements/${id}`, body);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useCreateQuote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post("/portal-admin/quotes", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function usePatchQuote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      api.patch(`/portal-admin/quotes/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useDeleteQuote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/portal-admin/quotes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}

export function useDeleteMovement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/portal-admin/movements/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-data"] }),
  });
}
