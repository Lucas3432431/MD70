import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ChevronDown, Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { usePatchProject } from "@/lib/hooks/useAdminData";
import { projectSummary } from "@/lib/data/admin-calculations";
import { brl, dateBR } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AdminProject, ProjectStage } from "@/lib/data/admin-types";

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
    capital: String(project.capital ?? 0),
    budget: String(project.budget ?? 0),
    remaining: String(project.remaining ?? 0),
    progress: String(project.progress ?? 0),
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
        capital: parseFloat(form.capital) || 0,
        budget: parseFloat(form.budget) || 0,
        remaining: parseFloat(form.remaining) || 0,
        progress: parseInt(form.progress) || 0,
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
          {/* Photo */}
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Foto do projeto (URL)</label>
            {form.image_url && (
              <img src={form.image_url} alt="" className="mt-2 mb-2 h-28 w-full object-cover"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
            )}
            <input type="url" value={form.image_url} onChange={(e) => set("image_url", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="https://…" />
          </div>

          {/* Basic info */}
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

          {/* Financials */}
          <div>
            <label className="block text-sm font-medium">Capital total (R$)</label>
            <input type="number" min="0" step="1000" value={form.capital} onChange={(e) => set("capital", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Orçamento (R$)</label>
            <input type="number" min="0" step="1000" value={form.budget} onChange={(e) => set("budget", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Saldo restante (R$)</label>
            <input type="number" min="0" step="1000" value={form.remaining} onChange={(e) => set("remaining", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Previsão de conclusão</label>
            <input type="date" value={form.forecast} onChange={(e) => set("forecast", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>

          {/* Progress */}
          <div>
            <label className="block text-sm font-medium">Progresso físico (%)</label>
            <div className="mt-1.5 flex items-center gap-3">
              <input type="range" min="0" max="100" value={form.progress}
                onChange={(e) => set("progress", e.target.value)} className="flex-1" />
              <span className="num w-10 shrink-0 text-right text-sm font-semibold">{form.progress}%</span>
            </div>
          </div>

          {/* Summary */}
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

// ─── Page ─────────────────────────────────────────────────────────────────────

function Detail() {
  const { id } = Route.useParams();
  const { data } = useAdmin();
  const [editing, setEditing] = useState(false);
  const [openSection, setOpenSection] = useState<string | null>("financeiro");

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

  return (
    <>
      <Link to="/admin/empreendimentos" className="text-xs text-muted-foreground underline underline-offset-4">
        ← Empreendimentos
      </Link>

      {/* Header */}
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

      {/* Photo preview (when not editing) */}
      {!editing && project.imageUrl && (
        <div className="mt-4 overflow-hidden border">
          <img src={project.imageUrl} alt={project.name} className="max-h-52 w-full object-cover" />
        </div>
      )}

      {/* Edit form */}
      {editing && <EditForm project={project} onClose={() => setEditing(false)} />}

      {/* KPI cards */}
      <section className="mt-6 grid gap-px border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {([
          ["Capital aportado", s.capital],
          ["Caixa disponível", s.cash],
          ["Orçamento", s.budget],
          ["Realizado", s.spent],
          ["Forecast", s.forecast],
          ["Saldo Forecast", s.saldoForecast],
        ] as [string, number][]).map(([l, v]) => (
          <div key={l} className="bg-card p-5">
            <p className="text-xs text-muted-foreground">{l}</p>
            <p className="num mt-2 font-display text-2xl text-primary">{brl(v)}</p>
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
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[650px] text-sm">
                      <thead>
                        <tr className="bg-muted text-left text-xs text-muted-foreground">
                          {["Categoria / item", "Orçado", "Realizado", "Comprometido", "Forecast", "Saldo"].map((h) => (
                            <th key={h} className="p-3">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {budgets.map((b) => {
                          const forecast = b.realized + b.committed + b.remaining;
                          return (
                            <tr key={b.id} className="border-t">
                              <td className="p-3 font-medium">{b.category} / {b.item}</td>
                              {[b.planned, b.realized, b.committed, forecast, b.planned - forecast].map((v, i) => (
                                <td key={i} className="num p-3">{brl(v)}</td>
                              ))}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
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
