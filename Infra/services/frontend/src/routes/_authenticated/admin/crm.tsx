import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { Plus, Trash2, X, ChevronDown, Search, Filter } from "lucide-react";
import { toast } from "sonner";
import { useAdmin } from "@/components/admin/AdminLayout";
import { usePatchLead, useCreateLead, useDeleteLead } from "@/lib/hooks/useAdminData";
import { brl, maskCpf, maskPhone, calcCdiFactor } from "@/lib/format";
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
  cdiByName,
  onClose,
}: {
  lead: Lead | null;
  projects: { id: string; name: string }[];
  cdiByName: Map<string, { invested: number; cdiValue: number }>;
  onClose: () => void;
}) {
  const patchLead = usePatchLead();
  const deleteLead = useDeleteLead();

  const [name, setName] = useState(lead?.name ?? "");
  const [email, setEmail] = useState(lead?.email ?? "");
  const [phone, setPhone] = useState(lead?.phone ?? "");
  const [cpf, setCpf] = useState(lead?.cpf ?? "");
  const [source, setSource] = useState(lead?.source ?? SOURCES[0]);
  const [status, setStatus] = useState<LeadStatus>(lead?.status ?? "Interesse");
  const [notes, setNotes] = useState(lead?.notes ?? "");
  // Multiple project interests: [{projectId, value}]
  const [interests, setInterests] = useState<{ projectId: string; value: string }[]>(
    () => (lead?.projectInterests ?? (lead?.projectInterest ? [{ projectId: lead.projectInterest, value: String(lead.value ?? "") }] : [])).map((pi) => ({ projectId: (pi as { projectId: string }).projectId, value: String((pi as { value?: number }).value ?? "") }))
  );
  const [deleteInput, setDeleteInput] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

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
        cpf: cpf.trim() || undefined,
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
    deleteLead.mutate(currentLead.id, {
      onSuccess: () => { toast.success("Lead excluído."); onClose(); },
      onError: () => toast.error("Erro ao excluir."),
    });
  }

  const isActiveInvestor = lead.status === "Investidor ativo";
  const totalPotential = interests.reduce((s, i) => s + (parseFloat(i.value) || 0), 0);
  const cdiData = cdiByName.get(lead.name);
  const investedValue = cdiData?.invested ?? 0;
  const cdiValue = cdiData?.cdiValue ?? 0;
  const cdiGain = cdiValue - investedValue;

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
          <p className="mt-1 text-xs text-muted-foreground">{lead.email}{lead.phone ? ` · ${lead.phone}` : ""}{lead.cpf ? ` · CPF ${lead.cpf}` : ""}</p>
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
                <input value={phone} onChange={(e) => setPhone(maskPhone(e.target.value))}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">CPF</label>
                <input value={cpf} onChange={(e) => setCpf(maskCpf(e.target.value))} placeholder="000.000.000-00"
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
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted-foreground">
                  {isActiveInvestor ? "Valor investido" : "Potencial total"}
                </label>
                {isActiveInvestor && investedValue > 0 ? (
                  <div className="mt-1 space-y-0.5">
                    <p className="num text-sm font-semibold text-primary">{brl(investedValue)} <span className="text-xs font-normal text-muted-foreground">aportado</span></p>
                    {cdiGain > 0 && <p className="num text-sm font-semibold text-positive">+{brl(cdiGain)} <span className="text-xs font-normal text-muted-foreground">rendimento CDI</span></p>}
                    {cdiGain > 0 && <p className="num text-xs text-muted-foreground">= {brl(cdiValue)} total</p>}
                  </div>
                ) : (
                  <p className="num mt-1 text-sm font-semibold text-primary">
                    {totalPotential > 0 ? brl(totalPotential) : "—"}
                  </p>
                )}
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

        </div>
        </div>

        <div className="shrink-0 border-t bg-background px-5 py-3">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-2">
              <input autoFocus value={deleteInput} onChange={(e) => setDeleteInput(e.target.value)}
                placeholder="Digite EXCLUIR" className="flex-1 border bg-background px-3 py-2 text-sm" />
              <button onClick={handleDelete} disabled={deleteInput !== "EXCLUIR" || deleteLead.isPending}
                className="bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-40">
                Confirmar
              </button>
              <button onClick={() => { setShowDeleteConfirm(false); setDeleteInput(""); }}
                className="px-3 py-2 text-sm text-muted-foreground">×</button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <button onClick={() => setShowDeleteConfirm(true)}
                className="flex shrink-0 items-center gap-2 text-sm text-destructive">
                <Trash2 className="size-4" /> Excluir
              </button>
              <button onClick={save} disabled={patchLead.isPending}
                className={cn(
                  "relative flex flex-1 items-center justify-center overflow-hidden py-2.5 text-sm font-semibold text-primary-foreground",
                  "bg-primary disabled:opacity-60",
                  "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
                )}>
                <span className="relative z-10">{patchLead.isPending ? "Salvando…" : "Salvar"}</span>
              </button>
            </div>
          )}
        </div>
      </DrawerContent>
    </Drawer>
  );
}

// ─── New lead dialog ──────────────────────────────────────────────────────────

function NewLeadDialog({ projects, onClose }: { projects: { id: string; name: string }[]; onClose: () => void }) {
  const createLead = useCreateLead();
  const [form, setForm] = useState({ name: "", email: "", phone: "", cpf: "", project_interest: projects.find((p) => p.id !== "fundo-md70")?.id ?? "", source: SOURCES[0], value: "", notes: "" });
  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nome obrigatório."); return; }
    try {
      await createLead.mutateAsync({ name: form.name.trim(), ...(form.email ? { email: form.email } : {}), ...(form.phone ? { phone: form.phone } : {}), ...(form.cpf ? { cpf: form.cpf } : {}), ...(form.project_interest ? { project_interest: form.project_interest } : {}), ...(form.source ? { source: form.source } : {}), ...(form.value ? { value: parseFloat(form.value) } : {}), ...(form.notes ? { notes: form.notes } : {}) });
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
            <input value={form.phone} onChange={(e) => set("phone", maskPhone(e.target.value))} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">CPF</label>
            <input value={form.cpf} onChange={(e) => set("cpf", maskCpf(e.target.value))} placeholder="000.000.000-00" className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
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
  const [openStages, setOpenStages] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const selectedLead = selected ? data.leads.find((l) => l.id === selected) ?? null : null;

  const visibleLeads = useMemo(() => {
    const q = search.toLowerCase().trim();
    return q ? data.leads.filter(l => l.name.toLowerCase().includes(q) || (l.email ?? "").toLowerCase().includes(q) || (l.phone ?? "").toLowerCase().includes(q)) : data.leads;
  }, [data.leads, search]);

  const cdiByName = useMemo(() => {
    const ratesMap = new Map<string, number>();
    (data.cdiRates ?? []).forEach((r) => ratesMap.set(r.yearMonth, r.rate));
    const supplierById = new Map(data.suppliers.map((s) => [s.id, s.name]));

    // Group Realizado movements by lead/supplier name
    const movsByName = new Map<string, { date: string; direction: string; value: number }[]>();
    for (const m of data.movements.filter((m) => m.status === "Realizado")) {
      let name: string | null = null;
      if (m.recipientName) name = m.recipientName;
      else if (m.supplierId) name = supplierById.get(m.supplierId) ?? null;
      else if (m.description.includes(" — ")) name = m.description.split(" — ")[0]!;
      if (!name) continue;
      const arr = movsByName.get(name) ?? [];
      arr.push({ date: m.date, direction: m.direction, value: m.value });
      movsByName.set(name, arr);
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

    const map = new Map<string, { invested: number; cdiValue: number }>();
    for (const [name, movs] of movsByName) {
      movs.sort((a, b) => a.date.localeCompare(b.date));
      let principal = 0;   // face value of active pool
      let cdiPool = 0;     // CDI-grown value of active pool
      let lastDate = movs[0]!.date;

      for (const m of movs) {
        // Grow existing pool from lastDate to this movement's date
        if (cdiPool > 0 && m.date > lastDate) {
          cdiPool *= calcCdiFactor(lastDate, m.date, ratesMap);
        }
        if (m.direction === "Entrada") {
          principal += m.value;
          cdiPool += m.value;
        } else {
          // Proportional withdrawal: remove the CDI-grown share
          if (principal > 0) {
            const ratio = Math.min(m.value / principal, 1);
            cdiPool *= (1 - ratio);
            principal = Math.max(principal - m.value, 0);
          }
        }
        lastDate = m.date;
      }

      // Grow remaining pool to today
      if (cdiPool > 0 && todayStr > lastDate) {
        cdiPool *= calcCdiFactor(lastDate, todayStr, ratesMap);
      }

      map.set(name, { invested: principal, cdiValue: cdiPool });
    }
    return map;
  }, [data.movements, data.suppliers, data.cdiRates]);

  function toggleStage(stage: string) {
    setOpenStages((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage); else next.add(stage);
      return next;
    });
  }

  function renderLeadCard(lead: ReturnType<typeof useAdmin>["data"]["leads"][number], isActive: boolean) {
    const interests = lead.projectInterests ?? (lead.projectInterest ? [{ projectId: lead.projectInterest, value: lead.value }] : []);
    const projNames = interests.map((pi) => data.projects.find((p) => p.id === pi.projectId)?.name).filter(Boolean);
    const cdiData = cdiByName.get(lead.name);
    const invested = cdiData?.invested ?? 0;
    const cdiValue = cdiData?.cdiValue ?? 0;
    const potentialValue = interests.reduce((s, i) => s + ((i as { value?: number }).value ?? 0), 0);
    return (
      <button key={lead.id} onClick={() => setSelected(lead.id)}
        className="w-full border bg-card p-3 text-left transition-colors hover:bg-accent/20">
        <p className="truncate text-sm font-semibold text-primary">{lead.name}</p>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">{projNames.length ? projNames.join(", ") : "—"}{lead.cpf ? ` · ${lead.cpf}` : ""}</p>
        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="truncate rounded-sm bg-muted px-1.5 py-0.5 text-[10px]">{lead.source}</span>
          {invested > 0 ? (
            <div className="text-right">
              <span className="num block text-xs font-semibold text-positive">{brl(cdiValue)}</span>
              {cdiValue > invested && <span className="num block text-[10px] text-muted-foreground">+{brl(cdiValue - invested)} CDI</span>}
            </div>
          ) : potentialValue > 0 ? (
            <span className="num shrink-0">{brl(potentialValue)}</span>
          ) : null}
        </div>
      </button>
    );
  }

  return (
    <>
      <div className="sticky top-16 z-10 -mx-4 mb-5 border-b bg-background/95 px-4 pb-3 pt-3 backdrop-blur md:-mx-8 md:px-8">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar lead..."
                className="w-full border bg-background pl-8 pr-3 py-2 text-sm"
              />
            </div>
            <button className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center bg-primary text-primary-foreground",
              "relative overflow-hidden",
              "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
            )}>
              <Filter className="relative z-10 size-4" />
            </button>
          </div>
          <button
            onClick={() => setShowNew(true)}
            className={cn(
              "flex w-full items-center justify-center gap-2 bg-primary py-3 text-sm font-semibold text-primary-foreground",
              "relative overflow-hidden",
              "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
            )}
          >
            <Plus className="relative z-10 size-4" />
            <span className="relative z-10">Novo lead</span>
          </button>
        </div>
      </div>

      {/* Mobile: collapsible stacked cards */}
      <div className="sm:hidden space-y-1">
        {STAGES.map((stage) => {
          const cards = visibleLeads.filter((l) => l.status === stage);
          const isActive = stage === "Investidor ativo";
          const isOpen = openStages.has(stage);
          return (
            <div key={stage} className="border">
              <button
                onClick={() => toggleStage(stage)}
                className={cn("flex w-full items-center justify-between border-t-2 px-4 py-3 text-left", STAGE_COLOR[stage])}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{stage}</span>
                  <span className="num font-display text-xl text-primary">{cards.length}</span>
                </div>
                <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
              </button>
              {isOpen && (
                <div className="space-y-2 p-3">
                  {cards.map((lead) => renderLeadCard(lead, isActive))}
                  {cards.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
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
            const cards = visibleLeads.filter((l) => l.status === stage);
            const isActive = stage === "Investidor ativo";
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                <div className={cn("mb-3 border-t-2 pt-3", STAGE_COLOR[stage])}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground leading-tight">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{cards.length}</p>
                </div>
                <div className="space-y-2">
                  {cards.map((lead) => renderLeadCard(lead, isActive))}
                  {cards.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <p className="mt-5 text-xs text-muted-foreground">
        {search.trim() ? `${visibleLeads.length} de ${data.leads.length}` : data.leads.length} lead{data.leads.length !== 1 ? "s" : ""} no total.
      </p>

      <LeadDrawer
        key={selected ?? "none"}
        lead={selectedLead}
        projects={data.projects}
        cdiByName={cdiByName}
        onClose={() => setSelected(null)}
      />

      {showNew && <NewLeadDialog projects={data.projects} onClose={() => setShowNew(false)} />}
    </>
  );
}
