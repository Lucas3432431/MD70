import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// These types mirror what the backend /api/portal/data returns
export interface PortalInvestment {
  id: string;
  developmentId: string;
  invested: number;
  value: number;
  cdiValue: number;
  rent: number;
  cdiRent: number;
  series: Array<{ month: string; invested: number; value: number; cdiValue: number; cdiRate: number; returnRate: number }>;
}

export interface PortalData {
  investor: { id: string; name: string; email: string };
  investments: PortalInvestment[];
  announcements: Array<{ id: string; date: string; title: string; summary: string; developmentId?: string }>;
}

export function usePortalData() {
  return useQuery<PortalData>({
    queryKey: ["portal-data"],
    queryFn: () => api.get<PortalData>("/portal/data"),
    staleTime: 60_000,
  });
}

export function usePortalDevelopments() {
  return useQuery({
    queryKey: ["portal-developments"],
    queryFn: () => api.get<Array<{ id: string; name: string; city: string; status: string; progress: number; forecast: string; image_url: string | null }>>("/portal/developments"),
    staleTime: 60_000,
  });
}

export interface PortalDocument {
  id: string;
  name: string;
  category: string;
  date: string;
  size: string;
  fileUrl: string | null;
  developmentId: string | null;
  developmentName: string | null;
}

export interface PortalDevelopmentDetail {
  id: string;
  name: string;
  city: string;
  status: string;
  progress: number;
  plannedProgress: number;
  capital: number;
  budget: number;
  remaining: number;
  forecast: string | null;
  imageUrl: string | null;
  category: string | null;
  summary: string | null;
  currentStage: string | null;
  nextStage: string | null;
  gallery: Array<{ url: string | null; caption: string }>;
  plan: {
    opportunity?: string;
    market?: string;
    strategy?: string;
    assumptions?: Array<{ label: string; value: string }>;
  };
  scenarios: Array<{ row: string; conservative: string; base: string; optimistic: string }>;
  milestones: Array<{ stage: string; start: number; end: number; done: number }>;
  ganttMonths: string[];
  diary: Array<{ date: string; title: string; description: string; images: string[] }>;
  budgetSeries: Array<{ month: string; planned: number; actual: number | null }>;
  budgetItems: Array<{ category: string; planned: number; actual: number }>;
  result: Array<{ label: string; planned: string; updated: string; kind: string }>;
  monthChanges: Array<{ tone: "positive" | "neutral" | "attention"; text: string }>;
  monthImpact: string;
}

export function usePortalDocuments() {
  return useQuery<PortalDocument[]>({
    queryKey: ["portal-documents"],
    queryFn: () => api.get<PortalDocument[]>("/portal/documents"),
    staleTime: 60_000,
  });
}

export function usePortalDevelopmentDetail(id: string) {
  return useQuery<PortalDevelopmentDetail>({
    queryKey: ["portal-development-detail", id],
    queryFn: () => api.get<PortalDevelopmentDetail>(`/portal/developments/${id}`),
    staleTime: 60_000,
    enabled: !!id,
  });
}
