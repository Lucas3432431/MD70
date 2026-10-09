import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { ChevronDown, Pencil, X, Check } from "lucide-react";
import { toast } from "sonner";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { usePatchProject, usePatchBudgetLine } from "@/lib/hooks/useAdminData";
import { projectSummary, sum } from "@/lib/data/admin-calculations";
import { brl, dateBR } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AdminProject, BudgetLine, ProjectStage } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/empreendimentos/$id")({
  head: () => ({ meta: [
    { title: "Detalhe do empreendimento — Administração MD70" },
    { name: "description", content: "Caixa, orçamento, financeiro e compras do empreendimento na área interna MD70." },
  ] }),
  component: Detail,
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

// ─── Edit form ────────────────────────────────────────────────────────────────

function EditForm({ project, onClose }: { project: AdminProject; onClose: () => void }) {
  const patchProject = usePatchProject();
  const [form, setForm] = useState({
    name: project.name,
    city: project.city ?? "",
    status: project.status,
    category: project.category ?? "",
    budget: String(project.budget ?? 0),
    forecast: project.forecast ?? "",
    image_url: project.imageUrl ?? "",
    summary: project.summary ?? "",
  });

  function set(k: string, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nome obrigatório."); return; }
    try {
      await patchProject.mutateAsync({
        id: project.id,
        name: form.name.trim(),
        city: form.city,
        status: form.status,
        category: form.category || null,
        budget: parseFloat(form.budget) || 0,
        forecast: form.forecast || null,
        image_url: form.image_url || null,
        summary: form.summary || null,
      });
      toast.success("Empreendimento atualizado.");
      onClose();
    } catch {
      toast.error("Erro ao atualizar empreendimento.");
    }
  }

  return (
    <div className="mt-6 border bg-card">
      <div className="flex items-center justify-between border-b px-5 py-4">
        <h2 className="font-display text-xl text-primary">Editar informações</h2>
        <button type="button" onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
      </div>
      <form onSubmit={submit} className="p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Foto do projeto</label>
            {form.image_url && (
              <div className="relative mt-2 mb-2">
                <img src={form.image_url} alt="" className="h-28 w-full object-cover border"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                <button type="button" onClick={() => set("image_url", "")}
                  className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-destructive text-white text-xs">
                  ×
                </button>
              </div>
            )}
            <input type="file" accept="image/*"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => set("image_url", reader.result as string);
                reader.readAsDataURL(file);
              }}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Nome *</label>
            <input required value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={200}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Cidade</label>
            <input value={form.city} onChange={(e) => set("city", e.target.value)} maxLength={100}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
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
            <label className="block text-sm font-medium">Forecast (R$)</label>
            <input type="number" min="0" step="1000" value={form.budget} onChange={(e) => set("budget", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
            <p className="mt-1 text-xs text-muted-foreground">Estimativa inicial no começo da obra.</p>
          </div>
          <div>
            <label className="block text-sm font-medium">Previsão de conclusão</label>
            <input type="date" value={form.forecast} onChange={(e) => set("forecast", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Descrição / resumo</label>
            <textarea value={form.summary} onChange={(e) => set("summary", e.target.value)} maxLength={600} rows={3}
              className="mt-1.5 w-full border bg-background p-2 text-sm" />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="border px-5 py-2.5 text-sm text-muted-foreground hover:bg-muted">Cancelar</button>
          <button type="submit" disabled={patchProject.isPending}
            className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {patchProject.isPending ? "Salvando…" : "Salvar alterações"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Editable budget row ──────────────────────────────────────────────────────

function BudgetRow({
  b,
  realized,
  committed,
}: {
  b: BudgetLine;
  realized: number;
  committed: number;
}) {
  const patchLine = usePatchBudgetLine();
  const [editPlanned, setEditPlanned] = useState(false);
  const [editRemaining, setEditRemaining] = useState(false);
  const [plannedVal, setPlannedVal] = useState(String(b.planned));
  const [remainingVal, setRemainingVal] = useState(String(b.remaining));

  const forecast = realized + committed + (parseFloat(remainingVal) || b.remaining);
  const saldo = forecast - realized;

  function savePlanned() {
    const v = parseFloat(plannedVal);
    if (!isNaN(v) && v !== b.planned) {
      patchLine.mutate({ id: b.id, planned: v }, {
        onSuccess: () => toast.success("Orçado atualizado."),
        onError: () => { toast.error("Erro ao salvar."); setPlannedVal(String(b.planned)); },
      });
    }
    setEditPlanned(false);
  }

  function saveRemaining() {
    const v = parseFloat(remainingVal);
    if (!isNaN(v) && v !== b.remaining) {
      patchLine.mutate({ id: b.id, remaining: v }, {
        onSuccess: () => toast.success("Forecast atualizado."),
        onError: () => { toast.error("Erro ao salvar."); setRemainingVal(String(b.remaining)); },
      });
    }
    setEditRemaining(false);
  }

  return (
    <tr className="border-t">
      <td className="p-3 font-medium">{b.category} / {b.item}</td>
      {/* Projeção = realizado + comprometido + restante — restante editable */}
      <td className="num p-3">
        {editRemaining ? (
          <div className="flex items-center gap-1">
            <input type="number" autoFocus value={remainingVal} onChange={(e) => setRemainingVal(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveRemaining(); if (e.key === "Escape") setEditRemaining(false); }}
              className="w-28 border bg-background px-2 py-1 text-xs" />
            <button onClick={saveRemaining} className="text-positive"><Check className="size-3.5" /></button>
          </div>
        ) : (
          <button onClick={() => setEditRemaining(true)} className="hover:text-primary hover:underline">
            {brl(forecast)}
          </button>
        )}
      </td>
      {/* Orçamento — editable */}
      <td className="num p-3">
        {editPlanned ? (
          <div className="flex items-center gap-1">
            <input type="number" autoFocus value={plannedVal} onChange={(e) => setPlannedVal(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") savePlanned(); if (e.key === "Escape") setEditPlanned(false); }}
              className="w-28 border bg-background px-2 py-1 text-xs" />
            <button onClick={savePlanned} className="text-positive"><Check className="size-3.5" /></button>
          </div>
        ) : (
          <button onClick={() => setEditPlanned(true)} className="hover:text-primary hover:underline">
            {brl(parseFloat(plannedVal) || b.planned)}
          </button>
        )}
      </td>
      {/* Comprometido — computed */}
      <td className="num p-3">{brl(committed)}</td>
      {/* Realizado — computed */}
      <td className="num p-3">{brl(realized)}</td>
      {/* Saldo = Projeção − Realizado */}
      <td className={cn("num p-3", saldo < 0 ? "text-destructive" : saldo > 0 ? "text-positive" : "")}>{brl(saldo)}</td>
    </tr>
  );
}

// Movement category → budget line category
const MOVEMENT_TO_BUDGET_CAT: Record<string, string> = {
  "Aquisição do imóvel": "Aquisição e Docs",
  "Aprovação": "Aquisição e Docs",
  "Projetos": "Projeto / Estudos",
};

const OBRA_CATEGORIES = [
  "Aquisição do imóvel", "Aprovação", "Projetos",
  "Fundação", "Alvenaria", "Mão de obra",
  "Elétrica", "Hidráulica", "Máquinas e equipamentos",
  "Custo recorrente", "Outros",
];

// ─── Gantt cronograma ─────────────────────────────────────────────────────────

function movWeek(dateStr: string): string {
  const d = new Date(dateStr + "T12:00:00");
  const jan1 = new Date(d.getFullYear(), 0, 1);
  const w = Math.ceil(((d.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${String(w).padStart(2, "0")}`;
}

function GanttCronograma({
  movements,
  mode,
}: {
  movements: ReturnType<typeof useAdmin>["data"]["movements"];
  mode: "fisico" | "financeiro";
}) {
  const categories = useMemo(() =>
    OBRA_CATEGORIES.filter((cat) =>
      movements.some((m) => m.category === cat && m.direction === "Saída" && m.status === "Realizado"),
    ),
    [movements],
  );

  const weekEntries = useMemo((): { key: string; label: string }[] => {
    const dates = movements
      .filter((m) => m.direction === "Saída" && m.status === "Realizado")
      .map((m) => m.date.slice(0, 10))
      .sort();
    if (dates.length === 0) return [];
    const firstDate = new Date(dates[0]! + "T12:00:00");
    const lastDate = new Date(dates[dates.length - 1]! + "T12:00:00");
    const result: { key: string; label: string }[] = [];
    const seen = new Set<string>();
    const d = new Date(firstDate);
    const dow = d.getDay();
    d.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
    while (d <= lastDate) {
      const wk = movWeek(d.toISOString().slice(0, 10));
      if (!seen.has(wk)) {
        seen.add(wk);
        result.push({ key: wk, label: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}` });
      }
      d.setDate(d.getDate() + 7);
    }
    return result;
  }, [movements]);

  const spendMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of movements.filter((m) => m.direction === "Saída" && m.status === "Realizado" && m.category !== "Capital")) {
      const key = `${m.category}|${movWeek(m.date)}`;
      map.set(key, (map.get(key) ?? 0) + m.value);
    }
    return map;
  }, [movements]);

  const categoryTotals = useMemo(() => {
    const map = new Map<string, number>();
    for (const [key, v] of spendMap) {
      const cat = key.split("|")[0]!;
      map.set(cat, (map.get(cat) ?? 0) + v);
    }
    return map;
  }, [spendMap]);

  const maxSpend = useMemo(() =>
    Math.max(1, ...Array.from(spendMap.values())),
    [spendMap],
  );

  if (weekEntries.length === 0 || categories.length === 0) {
    return <p className="text-sm text-muted-foreground">Sem dados para exibir.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-xs" style={{ minWidth: `${160 + (mode === "financeiro" ? 80 : 0) + weekEntries.length * 56}px` }}>
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-card border border-border px-3 py-2 text-left font-semibold min-w-[160px]">Categoria</th>
            {mode === "financeiro" && (
              <th className="sticky left-[160px] z-10 bg-card border border-border px-2 py-2 text-right font-semibold whitespace-nowrap min-w-[80px]">Total</th>
            )}
            {weekEntries.map(({ key, label }) => (
              <th key={key} className="border border-border px-1 py-2 font-medium text-muted-foreground min-w-[52px]">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((cat) => {
            const catTotal = categoryTotals.get(cat) ?? 0;
            return (
              <tr key={cat} className="hover:bg-muted/30">
                <td className="sticky left-0 z-10 bg-card border border-border px-3 py-2 font-medium">{cat}</td>
                {mode === "financeiro" && (
                  <td className="sticky left-[160px] z-10 bg-card num border border-border px-2 py-2 text-right whitespace-nowrap">
                    {catTotal > 0 ? brl(catTotal) : ""}
                  </td>
                )}
                {weekEntries.map(({ key: wk }) => {
                  const spend = spendMap.get(`${cat}|${wk}`) ?? 0;
                  const pct = spend / maxSpend;
                  return (
                    <td key={wk} className="border border-border p-1 text-center" title={mode === "financeiro" && spend > 0 ? brl(spend) : undefined}>
                      {mode === "financeiro" && spend > 0 && (
                        <div className="flex flex-col items-center gap-0.5">
                          <div
                            className="rounded-sm bg-positive opacity-80"
                            style={{ width: "100%", height: `${Math.max(6, Math.round(pct * 28))}px` }}
                          />
                          <span className="text-[9px] text-muted-foreground leading-none">{brl(spend).replace("R$ ", "")}</span>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
// ─── Page ─────────────────────────────────────────────────────────────────────

function Detail() {
  const { id } = Route.useParams();
  const { data } = useAdmin();
  const [editing, setEditing] = useState(false);
  const [openSection, setOpenSection] = useState<string | null>(null);
  const [cronMode, setCronMode] = useState<"fisico" | "financeiro">("financeiro");

  const s = projectSummary(data, id);
  if (!s.project) {
    return (
      <p className="text-sm">
        Empreendimento não encontrado.{" "}
        <Link to="/admin/empreendimentos" className="text-primary underline">Voltar</Link>
      </p>
    );
  }

  const project = s.project;
  const budgets = data.budgets.filter((b) => b.projectId === id);
  const movements = data.movements.filter((m) => m.projectId === id);
  const purchases = data.purchases.filter((p) => p.projectId === id);

  const realizedByCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of movements.filter((m) => m.direction === "Saída" && m.status === "Realizado" && m.category !== "Capital")) {
      const budgetCat = MOVEMENT_TO_BUDGET_CAT[m.category] ?? "Obra";
      map.set(budgetCat, (map.get(budgetCat) ?? 0) + m.value);
    }
    return map;
  }, [movements]);

  const committedByCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of movements.filter((m) => m.direction === "Saída" && m.status === "Comprometido" && m.category !== "Capital")) {
      const budgetCat = MOVEMENT_TO_BUDGET_CAT[m.category] ?? "Obra";
      map.set(budgetCat, (map.get(budgetCat) ?? 0) + m.value);
    }
    return map;
  }, [movements]);

  const budgetRows = useMemo(() => budgets.map((b) => ({
    ...b,
    realizedCalc: realizedByCategory.get(b.category) ?? 0,
    committedCalc: committedByCategory.get(b.category) ?? b.committed,
    forecastCalc: (realizedByCategory.get(b.category) ?? 0) + (committedByCategory.get(b.category) ?? b.committed) + b.remaining,
  })), [budgets, realizedByCategory, committedByCategory]);

  const totals = useMemo(() => ({
    planned: sum(budgetRows.map((r) => r.planned)),
    realized: sum(budgetRows.map((r) => r.realizedCalc)),
    committed: sum(budgetRows.map((r) => r.committedCalc)),
    forecast: sum(budgetRows.map((r) => r.forecastCalc)),
    saldo: sum(budgetRows.map((r) => r.forecastCalc - r.realizedCalc)),
  }), [budgetRows]);

  const financialPct = totals.planned > 0 ? Math.min(100, Math.round((totals.realized / totals.planned) * 100)) : 0;

  return (
    <>
      <Link to="/admin/empreendimentos" className="text-xs text-muted-foreground underline underline-offset-4">
        ← Empreendimentos
      </Link>

      <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
        <AdminHeading title={project.name}>
          {project.city ? `${project.city} · ` : ""}{project.status} · obra {project.progress}%
        </AdminHeading>
        <button
          onClick={() => setEditing((v) => !v)}
          className={cn(
            "flex shrink-0 items-center gap-2 border px-4 py-2 text-sm font-medium transition-colors",
            editing ? "border-primary bg-primary/5 text-primary" : "hover:bg-muted",
          )}
        >
          {editing ? <X className="size-4" /> : <Pencil className="size-4" />}
          {editing ? "Fechar edição" : "Editar"}
        </button>
      </div>

      {!editing && project.imageUrl && (
        <div className="mt-4 overflow-hidden border">
          <img src={project.imageUrl} alt={project.name} className="max-h-52 w-full object-cover" />
        </div>
      )}

      {editing && <EditForm project={project} onClose={() => setEditing(false)} />}

      {/* KPI cards — forecast from budget sum */}
      <section className="mt-6 grid gap-px border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {([
          ["Capital aportado", s.capital, null],
          ["Caixa disponível", s.cash, null],
          ...(project.budget > 0 ? [["Forecast", project.budget, null] as [string, number, null]] : []),
          ["Orçamento", totals.planned, null],
          ["Realizado", totals.realized, null],
          ["Projeção", totals.forecast, null],
          ["Saldo", totals.forecast - totals.realized, totals.forecast - totals.realized],
        ] as [string, number, number | null][]).map(([l, v, colorVal]) => (
          <div key={l} className="bg-card p-5">
            <p className="text-xs text-muted-foreground">{l}</p>
            <p className={cn("num mt-2 font-display text-2xl", colorVal !== null ? (colorVal >= 0 ? "text-positive" : "text-destructive") : "text-primary")}>{brl(v)}</p>
          </div>
        ))}
        {project.vgv != null && project.vgv > 0 && (
          <div className="bg-card p-5">
            <p className="text-xs text-muted-foreground">VGV</p>
            <p className="num mt-2 font-display text-2xl text-primary">{brl(project.vgv)}</p>
          </div>
        )}
        {project.forecast && (
          <div className="bg-card p-5">
            <p className="text-xs text-muted-foreground">Previsão</p>
            <p className="num mt-2 font-display text-2xl text-primary">{dateBR(project.forecast)}</p>
          </div>
        )}
      </section>

      {/* ── Cronograma físico-financeiro ─────────────────────────────── */}
      <section className="mt-6 border bg-card px-5 py-4 space-y-4">
        <h2 className="font-display text-xl text-primary">Cronograma físico-financeiro</h2>
        <GanttCronograma movements={movements} mode={cronMode} />
        {/* Toggle */}
        <div className="flex items-center gap-3">
          <span className={cn("text-xs transition-colors", cronMode === "fisico" ? "font-semibold text-primary" : "text-muted-foreground")}>Físico</span>
          <button
            type="button"
            role="switch"
            aria-checked={cronMode === "financeiro"}
            onClick={() => setCronMode((v) => v === "fisico" ? "financeiro" : "fisico")}
            className={cn(
              "relative h-6 w-11 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              cronMode === "financeiro" ? "bg-positive" : "bg-primary",
            )}
          >
            <span className={cn(
              "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200",
              cronMode === "financeiro" && "translate-x-5",
            )} />
          </button>
          <span className={cn("text-xs transition-colors", cronMode === "financeiro" ? "font-semibold text-positive" : "text-muted-foreground")}>Financeiro</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted-foreground mb-1">Progresso físico</p>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden">
                <div className="h-3 rounded-full bg-primary transition-all" style={{ width: `${project.progress}%` }} />
              </div>
              <span className="num w-10 shrink-0 text-right text-sm font-semibold">{project.progress}%</span>
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Progresso financeiro</p>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden">
                <div className="h-3 rounded-full bg-positive transition-all" style={{ width: `${financialPct}%` }} />
              </div>
              <span className="num w-10 shrink-0 text-right text-sm font-semibold">{financialPct}%</span>
            </div>
          </div>
          {project.forecast && (
            <div>
              <p className="text-xs text-muted-foreground">Previsão de conclusão</p>
              <p className="mt-1 text-sm font-semibold">{dateBR(project.forecast)}</p>
            </div>
          )}
          <div>
            <p className="text-xs text-muted-foreground">Realizado vs. Orçado</p>
            <p className="num mt-1 text-sm font-semibold">
              {brl(totals.realized)}{" "}
              <span className="font-normal text-muted-foreground">de {brl(totals.planned)}</span>
            </p>
          </div>
        </div>
      </section>

      {/* Collapsible sections */}
      {[
        { key: "orcamento", label: "Orçamento", count: budgets.length },
        { key: "financeiro", label: "Financeiro", count: movements.length },
        { key: "compras", label: "Compras", count: purchases.length },
      ].map(({ key, label, count }) => (
        <section key={key} className="mt-6 border">
          <button
            onClick={() => setOpenSection(openSection === key ? null : key)}
            className="flex w-full items-center justify-between px-5 py-4 text-left"
          >
            <h2 className="font-display text-xl text-primary">{label} <span className="ml-2 text-sm font-normal text-muted-foreground">({count})</span></h2>
            <ChevronDown className={cn("size-5 text-muted-foreground transition-transform", openSection === key && "rotate-180")} />
          </button>

          {openSection === key && (
            <div className="border-t px-5 py-4">
              {key === "orcamento" && (
                budgets.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nenhuma linha orçamentária.</p>
                ) : (
                  <>
                    <p className="mb-3 text-xs text-muted-foreground">Clique em Orçamento ou Forecast para editar. Realizado e Comprometido são calculados do financeiro.</p>
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[650px] text-sm">
                        <thead>
                          <tr className="bg-muted text-left text-xs text-muted-foreground">
                            {["Categoria / item", "Projeção", "Orçamento", "Comprometido", "Realizado", "Saldo"].map((h) => (
                              <th key={h} className="p-3">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {budgetRows.map((b) => (
                            <BudgetRow
                              key={b.id}
                              b={b}
                              realized={b.realizedCalc}
                              committed={b.committedCalc}
                            />
                          ))}
                          <tr className="border-t-2 bg-muted/40 font-semibold">
                            <td className="p-3">Total</td>
                            {[totals.forecast, totals.planned, totals.committed, totals.realized, totals.saldo].map((v, i) => (
                              <td key={i} className={cn("num p-3", i === 4 ? (v < 0 ? "text-destructive" : v > 0 ? "text-positive" : "") : "")}>{brl(v)}</td>
                            ))}
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </>
                )
              )}

              {key === "financeiro" && (
                movements.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nenhum lançamento.</p>
                ) : (
                  <div className="divide-y">
                    {movements.map((m) => (
                      <div key={m.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 py-4 text-sm">
                        <div className="min-w-0">
                          <p className="font-medium">{m.description}</p>
                          <p className="text-xs text-muted-foreground">{dateBR(m.date)} · {m.category} · {m.status}</p>
                        </div>
                        <span className={cn("num shrink-0", m.direction === "Entrada" ? "text-positive" : "text-destructive")}>
                          {m.direction === "Saída" ? "−" : "+"}{brl(m.value)}
                        </span>
                      </div>
                    ))}
                  </div>
                )
              )}

              {key === "compras" && (
                purchases.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Nenhuma compra.</p>
                ) : (
                  <div className="divide-y">
                    {purchases.map((p) => (
                      <div key={p.id} className="flex flex-wrap justify-between gap-2 py-4 text-sm">
                        <span>{p.description}</span>
                        <span className="text-muted-foreground">{p.status} · {brl(p.estimate)}</span>
                      </div>
                    ))}
                  </div>
                )
              )}
            </div>
          )}
        </section>
      ))}
    </>
  );
}
