import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { Plus, X, ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { useCreateProject } from "@/lib/hooks/useAdminData";
import { projectSummary, budgetStatus } from "@/lib/data/admin-calculations";
import { brlShort } from "@/lib/format";
import type { ProjectStage } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/empreendimentos/")({
  head: () => ({ meta: [
    { title: "Empreendimentos — Administração MD70" },
    { name: "description", content: "Pipeline de projetos e indicadores financeiros da área interna MD70." },
    { property: "og:title", content: "Empreendimentos MD70" },
    { property: "og:type", content: "website" },
  ] }),
  component: AdminProjects,
});

const STAGES: ProjectStage[] = [
  "Oferecido / Interessado",
  "Visita",
  "Business Plan / Capital",
  "Projeto",
  "Proposta / Negociação",
  "Construção / Reforma",
  "Vendido",
];

const STAGE_COLOR: Record<ProjectStage, string> = {
  "Oferecido / Interessado":  "border-t-muted-foreground/30",
  "Visita":                   "border-t-blue-300",
  "Business Plan / Capital":  "border-t-blue-500",
  "Projeto":                  "border-t-warning",
  "Proposta / Negociação":    "border-t-orange-400",
  "Construção / Reforma":     "border-t-primary",
  "Vendido":                  "border-t-positive",
};

const HEALTH_DOT: Record<ReturnType<typeof budgetStatus>, string> = {
  ok:   "bg-positive",
  warn: "bg-warning",
  over: "bg-destructive",
};

// ─── New project dialog ───────────────────────────────────────────────────────

function NewProjectDialog({ onClose }: { onClose: () => void }) {
  const createProject = useCreateProject();
  const [form, setForm] = useState({
    name: "",
    city: "",
    status: "Oferecido / Interessado" as ProjectStage,
    category: "",
    capital: "",
    budget: "",
    forecast: "",
    image_url: "",
    summary: "",
  });

  function set(k: string, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nome obrigatório."); return; }
    try {
      await createProject.mutateAsync({
        name: form.name.trim(),
        city: form.city || "",
        status: form.status,
        ...(form.category ? { category: form.category } : {}),
        capital: parseFloat(form.capital) || 0,
        budget: parseFloat(form.budget) || 0,
        remaining: parseFloat(form.budget) || 0,
        ...(form.forecast ? { forecast: form.forecast } : {}),
        ...(form.image_url ? { image_url: form.image_url } : {}),
        ...(form.summary ? { summary: form.summary } : {}),
      });
      toast.success("Empreendimento criado.");
      onClose();
    } catch {
      toast.error("Erro ao criar empreendimento.");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/60 p-4" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="my-8 w-full max-w-2xl border bg-card p-6 shadow-xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-display text-2xl text-primary">Novo empreendimento</h2>
          <button type="button" onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Nome *</label>
            <input required value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={200}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="Ex: Edifício Aurora" />
          </div>
          <div>
            <label className="block text-sm font-medium">Cidade</label>
            <input value={form.city} onChange={(e) => set("city", e.target.value)} maxLength={100}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="São Paulo, SP" />
          </div>
          <div>
            <label className="block text-sm font-medium">Categoria</label>
            <input value={form.category} onChange={(e) => set("category", e.target.value)} maxLength={80}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="Residencial, Comercial…" />
          </div>
          <div>
            <label className="block text-sm font-medium">Status (pipeline)</label>
            <select value={form.status} onChange={(e) => set("status", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
              {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Previsão de conclusão</label>
            <input type="date" value={form.forecast} onChange={(e) => set("forecast", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Capital total (R$)</label>
            <input type="number" min="0" step="1000" value={form.capital} onChange={(e) => set("capital", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="0" />
          </div>
          <div>
            <label className="block text-sm font-medium">Forecast (R$)</label>
            <input type="number" min="0" step="1000" value={form.budget} onChange={(e) => set("budget", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="0" />
            <p className="mt-1 text-xs text-muted-foreground">Estimativa inicial no começo da obra.</p>
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">URL da imagem</label>
            <input type="url" value={form.image_url} onChange={(e) => set("image_url", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="https://…" />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Descrição / resumo</label>
            <textarea value={form.summary} onChange={(e) => set("summary", e.target.value)} maxLength={600} rows={3}
              className="mt-1.5 w-full border bg-background p-2 text-sm" />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="border px-5 py-2.5 text-sm text-muted-foreground hover:bg-muted">Cancelar</button>
          <button type="submit" disabled={createProject.isPending}
            className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {createProject.isPending ? "Criando…" : "Criar empreendimento"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function ProjectCard({ p, data }: { p: ReturnType<typeof useAdmin>["data"]["projects"][number]; data: ReturnType<typeof useAdmin>["data"] }) {
  const s = projectSummary(data, p.id);
  const health = s.budget > 0 ? budgetStatus(s.saldoForecast, s.budget) : null;
  return (
    <Link
      to="/admin/empreendimentos/$id"
      params={{ id: p.id }}
      className="block border bg-card p-3 transition-colors hover:bg-accent/20"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-primary leading-tight">{p.name}</p>
        {health && <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${HEALTH_DOT[health]}`} />}
      </div>
      {p.city && <p className="mt-0.5 text-[10px] text-muted-foreground">{p.city}</p>}
      {p.progress > 0 && (
        <div className="mt-2">
          <div className="h-1 bg-muted"><div className="h-full bg-primary" style={{ width: `${p.progress}%` }} /></div>
          <p className="mt-1 text-[10px] text-muted-foreground">{p.progress}%</p>
        </div>
      )}
      {s.capital > 0 && (
        <div className="mt-2 grid grid-cols-2 gap-x-2 text-[10px]">
          <span className="text-muted-foreground">Capital</span>
          <span className="num text-right">{brlShort(s.capital)}</span>
          <span className="text-muted-foreground">VGV</span>
          <span className="num text-right">{brlShort(s.forecast)}</span>
        </div>
      )}
    </Link>
  );
}

function AdminProjects() {
  const { data } = useAdmin();
  const [showNew, setShowNew] = useState(false);
  const [openStages, setOpenStages] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  const visibleProjects = useMemo(() => {
    const q = search.toLowerCase().trim();
    return q ? data.projects.filter(p => p.name.toLowerCase().includes(q) || (p.city ?? "").toLowerCase().includes(q)) : data.projects;
  }, [data.projects, search]);

  function toggleStage(stage: string) {
    setOpenStages((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage); else next.add(stage);
      return next;
    });
  }

  return (
    <>
      <AdminHeading title="Empreendimentos">Pipeline de projetos — do primeiro contato à venda.</AdminHeading>

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar empreendimento..."
            className="border bg-background pl-8 pr-3 py-2 text-sm w-52 sm:w-64"
          />
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="flex items-center gap-2 bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="size-4" /> Novo empreendimento
        </button>
      </div>

      {/* Mobile: collapsible stacked cards */}
      <div className="sm:hidden space-y-1">
        {STAGES.map((stage) => {
          const projects = visibleProjects.filter((p) => p.status === stage);
          const isOpen = openStages.has(stage);
          return (
            <div key={stage} className="border">
              <button
                onClick={() => toggleStage(stage)}
                className={cn("flex w-full items-center justify-between border-t-2 px-4 py-3 text-left", STAGE_COLOR[stage])}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{stage}</span>
                  <span className="num font-display text-xl text-primary">{projects.length}</span>
                </div>
                <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
              </button>
              {isOpen && (
                <div className="space-y-2 p-3">
                  {projects.map((p) => <ProjectCard key={p.id} p={p} data={data} />)}
                  {projects.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Desktop: horizontal kanban */}
      <div className="hidden sm:block overflow-x-auto pb-4">
        <div className="flex gap-3" style={{ minWidth: `${STAGES.length * 216}px` }}>
          {STAGES.map((stage) => {
            const projects = visibleProjects.filter((p) => p.status === stage);
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                <div className={`mb-3 border-t-2 pt-3 ${STAGE_COLOR[stage]}`}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground leading-tight">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{projects.length}</p>
                </div>
                <div className="space-y-2">
                  {projects.map((p) => <ProjectCard key={p.id} p={p} data={data} />)}
                  {projects.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showNew && <NewProjectDialog onClose={() => setShowNew(false)} />}
    </>
  );
}
