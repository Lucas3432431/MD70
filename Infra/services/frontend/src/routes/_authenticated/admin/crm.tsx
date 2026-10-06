import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { usePatchLead, useCreateLead, useDeleteLead } from "@/lib/hooks/useAdminData";
import { brl } from "@/lib/format";
import { sum } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose,
} from "@/components/ui/drawer";
import type { Lead, LeadStatus } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/crm")({
  head: () => ({ meta: [
    { title: "CRM — Administração MD70" },
    { name: "description", content: "Leads e investidores por empreendimento." },
  ] }),
  component: CRM,
});

const STAGES: LeadStatus[] = ["Interesse", "Qualificado", "Em negociação", "Investidor ativo", "Descartado/Adiado"];
const SOURCES = ["Site", "Indicação", "LinkedIn", "Instagram", "WhatsApp", "Evento", "Outro"];

const STAGE_COLOR: Record<LeadStatus, string> = {
  "Interesse":          "border-t-muted-foreground/30",
  "Qualificado":        "border-t-blue-300",
  "Em negociação":      "border-t-warning",
  "Investidor ativo":   "border-t-positive",
  "Descartado/Adiado":  "border-t-destructive/40",
};

// ─── Lead detail drawer ───────────────────────────────────────────────────────

function LeadDrawer({
  lead,
  projects,
  investedByName,
  onClose,
}: {
  lead: Lead | null;
  projects: { id: string; name: string }[];
  investedByName: Map<string, number>;
  onClose: () => void;
}) {
  const patchLead = usePatchLead();
  const deleteLead = useDeleteLead();

  const [name, setName] = useState(lead?.name ?? "");
  const [email, setEmail] = useState(lead?.email ?? "");
  const [phone, setPhone] = useState(lead?.phone ?? "");
  const [source, setSource] = useState(lead?.source ?? SOURCES[0]);
  const [status, setStatus] = useState<LeadStatus>(lead?.status ?? "Interesse");
  const [notes, setNotes] = useState(lead?.notes ?? "");
  // Multiple project interests: [{projectId, value}]
  const [interests, setInterests] = useState<{ projectId: string; value: string }[]>(
    () => (lead?.projectInterests ?? (lead?.projectInterest ? [{ projectId: lead.projectInterest, value: String(lead.value ?? "") }] : [])).map((pi) => ({ projectId: (pi as { projectId: string }).projectId, value: String((pi as { value?: number }).value ?? "") }))
  );

  if (!lead) return null;
  const currentLead = lead;

  function addInterest() {
    const defaultProject = projects.find((p) => p.id !== "fundo-md70")?.id ?? "";
    setInterests((prev) => [...prev, { projectId: defaultProject, value: "" }]);
  }

  function removeInterest(i: number) {
    setInterests((prev) => prev.filter((_, idx) => idx !== i));
  }

  function setInterestField(i: number, k: "projectId" | "value", v: string) {
    setInterests((prev) => prev.map((item, idx) => idx === i ? { ...item, [k]: v } : item));
  }

  function save() {
    const serialisedInterests = interests.filter((i) => i.projectId).map((i) => ({
      projectId: i.projectId,
      ...(i.value ? { value: parseFloat(i.value) } : {}),
    }));
    const totalValue = serialisedInterests.reduce((s, i) => s + ((i as { value?: number }).value ?? 0), 0);
    patchLead.mutate(
      {
        id: currentLead.id,
        status,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim() || undefined,
        source,
        project_interests: serialisedInterests,
        project_interest: serialisedInterests[0]?.projectId,
        value: totalValue || undefined,
      },
      {
        onSuccess: () => { toast.success("Lead salvo."); onClose(); },
        onError: () => toast.error("Erro ao salvar."),
      },
    );
  }

  function handleDelete() {
    if (!confirm(`Excluir o lead "${currentLead.name}"?`)) return;
    deleteLead.mutate(currentLead.id, {
      onSuccess: () => { toast.success("Lead excluído."); onClose(); },
      onError: () => toast.error("Erro ao excluir."),
    });
  }

  const isActiveInvestor = lead.status === "Investidor ativo";
  const totalPotential = interests.reduce((s, i) => s + (parseFloat(i.value) || 0), 0);
  const investedValue = investedByName.get(lead.name) ?? 0;

  return (
    <Drawer open onOpenChange={(v) => !v && onClose()}>
      <DrawerContent className="flex max-h-[92vh] flex-col lg:left-[25%] lg:right-[25%]">
        <DrawerHeader className="shrink-0 border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <DrawerTitle className="font-display text-2xl text-primary">{lead.name}</DrawerTitle>
            <DrawerClose asChild>
              <button onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
            </DrawerClose>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{lead.email}{lead.phone ? ` · ${lead.phone}` : ""}</p>
        </DrawerHeader>

        <div className="flex-1 overflow-y-auto">
        <div className="space-y-6 p-5">
          {/* Basic info */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Dados do lead</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs text-muted-foreground">Nome</label>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">E-mail</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Telefone</label>
                <input value={phone} onChange={(e) => setPhone(e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Origem</label>
                <select value={source} onChange={(e) => setSource(e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                  {SOURCES.map((s) => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Status</label>
                <select value={status} onChange={(e) => setStatus(e.target.value as LeadStatus)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                  {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">
                  {isActiveInvestor ? "Valor investido" : "Potencial total"}
                </label>
                <p className={`num mt-2 text-sm font-semibold ${isActiveInvestor ? "text-positive" : "text-primary"}`}>
                  {isActiveInvestor
                    ? (investedValue > 0 ? brl(investedValue) : "—")
                    : (totalPotential > 0 ? brl(totalPotential) : "—")}
                </p>
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted-foreground">Observações</label>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={500}
                  className="mt-1 w-full border bg-background p-2 text-sm" />
              </div>
            </div>
          </section>

          {/* Project interests */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-primary">Empreendimentos de interesse</h3>
              <button onClick={addInterest}
                className="flex items-center gap-1.5 border px-3 py-1.5 text-xs hover:bg-muted">
                <Plus className="size-3" /> Adicionar
              </button>
            </div>
            <div className="space-y-2">
              {interests.map((item, i) => (
                <div key={i} className="flex items-center gap-2">
                  <select value={item.projectId} onChange={(e) => setInterestField(i, "projectId", e.target.value)}
                    className="flex-1 border bg-background px-2 py-2 text-sm">
                    <option value="">— Selecionar —</option>
                    {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <input
                    type="number" min="0" step="1000"
                    value={item.value} onChange={(e) => setInterestField(i, "value", e.target.value)}
                    placeholder="Valor (R$)"
                    className="w-32 border bg-background px-2 py-2 text-sm"
                  />
                  <button onClick={() => removeInterest(i)} className="text-muted-foreground hover:text-destructive">
                    <Trash2 className="size-4" />
                  </button>
                </div>
              ))}
              {interests.length === 0 && (
                <p className="text-xs text-muted-foreground">Nenhum empreendimento associado.</p>
              )}
            </div>
          </section>

          {/* Actions */}
          <section className="flex flex-wrap items-center gap-3">
            <button onClick={save} disabled={patchLead.isPending}
              className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
              {patchLead.isPending ? "Salvando…" : "Salvar"}
            </button>
            <button onClick={handleDelete}
              className="flex items-center gap-2 border border-destructive/30 px-4 py-2.5 text-sm text-destructive hover:bg-destructive/5">
              <Trash2 className="size-4" /> Excluir lead
            </button>
          </section>
        </div>
        </div>
      </DrawerContent>
    </Drawer>
  );
}

// ─── New lead dialog ──────────────────────────────────────────────────────────

function NewLeadDialog({ projects, onClose }: { projects: { id: string; name: string }[]; onClose: () => void }) {
  const createLead = useCreateLead();
  const [form, setForm] = useState({ name: "", email: "", phone: "", project_interest: projects.find((p) => p.id !== "fundo-md70")?.id ?? "", source: SOURCES[0], value: "", notes: "" });
  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nome obrigatório."); return; }
    try {
      await createLead.mutateAsync({ name: form.name.trim(), ...(form.email ? { email: form.email } : {}), ...(form.phone ? { phone: form.phone } : {}), ...(form.project_interest ? { project_interest: form.project_interest } : {}), ...(form.source ? { source: form.source } : {}), ...(form.value ? { value: parseFloat(form.value) } : {}), ...(form.notes ? { notes: form.notes } : {}) });
      toast.success("Lead criado.");
      onClose();
    } catch { toast.error("Erro ao criar lead."); }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/60 p-4" onClick={onClose}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} className="w-full max-w-lg border bg-card p-6 shadow-xl">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-display text-2xl text-primary">Novo lead</h2>
          <button type="button" onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Nome *</label>
            <input required value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={200} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">E-mail</label>
            <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Telefone</label>
            <input value={form.phone} onChange={(e) => set("phone", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Empreendimento</label>
            <select value={form.project_interest} onChange={(e) => set("project_interest", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
              <option value="">— Nenhum —</option>
              {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Origem</label>
            <select value={form.source} onChange={(e) => set("source", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
              {SOURCES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Potencial (R$)</label>
            <input type="number" min="0" step="1000" value={form.value} onChange={(e) => set("value", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Observações</label>
            <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={500} rows={2} className="mt-1.5 w-full border bg-background p-2 text-sm" />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="border px-5 py-2.5 text-sm text-muted-foreground hover:bg-muted">Cancelar</button>
          <button type="submit" disabled={createLead.isPending} className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {createLead.isPending ? "Criando…" : "Criar lead"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function CRM() {
  const { data } = useAdmin();
  const [selected, setSelected] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const selectedLead = selected ? data.leads.find((l) => l.id === selected) ?? null : null;

  const investedByName = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of data.movements.filter((m) => m.category === "Capital" && m.status === "Realizado")) {
      const name = m.description.includes(" — ") ? m.description.split(" — ")[0]! : null;
      if (!name) continue;
      const delta = m.direction === "Entrada" ? m.value : -m.value;
      map.set(name, (map.get(name) ?? 0) + delta);
    }
    return map;
  }, [data.movements]);

  return (
    <>
      <AdminHeading title="CRM">Leads e investidores por empreendimento e estágio do funil.</AdminHeading>

      <div className="mb-5 flex justify-end">
        <button onClick={() => setShowNew(true)} className="flex items-center gap-2 bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
          <Plus className="size-4" /> Novo lead
        </button>
      </div>

      <div className="overflow-x-auto pb-4">
        <div className="flex gap-3" style={{ minWidth: `${STAGES.length * 216}px` }}>
          {STAGES.map((stage) => {
            const cards = data.leads.filter((l) => l.status === stage);
            const isActive = stage === "Investidor ativo";
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                <div className={cn("mb-3 border-t-2 pt-3", STAGE_COLOR[stage])}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground leading-tight">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{cards.length}</p>
                </div>
                <div className="space-y-2">
                  {cards.map((lead) => {
                    const interests = lead.projectInterests ?? (lead.projectInterest ? [{ projectId: lead.projectInterest, value: lead.value }] : []);
                    const projNames = interests.map((pi) => data.projects.find((p) => p.id === pi.projectId)?.name).filter(Boolean);
                    const invested = isActive ? (investedByName.get(lead.name) ?? 0) : 0;
                    const potentialValue = interests.reduce((s, i) => s + ((i as { value?: number }).value ?? 0), 0);
                    const displayValue = isActive ? invested : potentialValue;
                    return (
                      <button key={lead.id} onClick={() => setSelected(lead.id)}
                        className="w-full border bg-card p-3 text-left transition-colors hover:bg-accent/20">
                        <p className="truncate text-sm font-semibold text-primary">{lead.name}</p>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">
                          {projNames.length ? projNames.join(", ") : "—"}
                        </p>
                        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="truncate rounded-sm bg-muted px-1.5 py-0.5 text-[10px]">{lead.source}</span>
                          {displayValue > 0 && (
                            <span className={cn("num shrink-0", isActive && "text-positive")}>{brl(displayValue)}</span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                  {cards.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <p className="mt-5 text-xs text-muted-foreground">{data.leads.length} lead{data.leads.length !== 1 ? "s" : ""} no total.</p>

      <LeadDrawer
        key={selected ?? "none"}
        lead={selectedLead}
        projects={data.projects}
        investedByName={investedByName}
        onClose={() => setSelected(null)}
      />

      {showNew && <NewLeadDialog projects={data.projects} onClose={() => setShowNew(false)} />}
    </>
  );
}
