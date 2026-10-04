import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { brlShort } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Lead, LeadStatus } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/crm")({
  head: () => ({ meta: [
    { title: "CRM — Administração MD70" },
    { name: "description", content: "Leads e investidores por empreendimento." },
    { property: "og:title", content: "CRM administrativo MD70" },
    { property: "og:type", content: "website" },
  ] }),
  component: CRM,
});

const STAGES: LeadStatus[] = [
  "Interesse",
  "Qualificado",
  "Em negociação",
  "Investidor ativo",
  "Descartado",
];

const STAGE_COLOR: Record<LeadStatus, string> = {
  "Interesse":        "border-t-muted-foreground/30",
  "Qualificado":      "border-t-blue-300",
  "Em negociação":    "border-t-warning",
  "Investidor ativo": "border-t-positive",
  "Descartado":       "border-t-destructive/40",
};

function CRM() {
  const { data, setData } = useAdmin();
  const [selected, setSelected] = useState<string | null>(null);
  const [editStatus, setEditStatus] = useState<LeadStatus>("Interesse");
  const [editNotes, setEditNotes] = useState("");

  function selectLead(lead: Lead) {
    if (selected === lead.id) { setSelected(null); return; }
    setSelected(lead.id);
    setEditStatus(lead.status);
    setEditNotes(lead.notes ?? "");
  }

  function saveLead(lead: Lead) {
    setData((prev) => ({
      ...prev,
      leads: prev.leads.map((l) => {
        if (l.id !== lead.id) return l;
        const updated: Lead = { ...l, status: editStatus };
        if (editNotes.trim()) updated.notes = editNotes.trim(); else delete updated.notes;
        return updated;
      }),
    }));
    setSelected(null);
  }

  const totalLeads = data.leads.length;
  const selectedLead = selected ? data.leads.find((l) => l.id === selected) : null;

  return (
    <>
      <AdminHeading title="CRM">Leads e investidores por empreendimento e estágio do funil.</AdminHeading>

      {/* Kanban */}
      <div className="overflow-x-auto pb-4">
        <div className="flex gap-3" style={{ minWidth: `${STAGES.length * 216}px` }}>
          {STAGES.map((stage) => {
            const cards = data.leads.filter((l) => l.status === stage);
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                {/* Column header */}
                <div className={cn("mb-3 border-t-2 pt-3", STAGE_COLOR[stage])}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground leading-tight">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{cards.length}</p>
                </div>

                {/* Cards */}
                <div className="space-y-2">
                  {cards.map((lead) => {
                    const proj = data.projects.find((p) => p.id === lead.projectInterest);
                    const isSelected = selected === lead.id;
                    return (
                      <button
                        key={lead.id}
                        onClick={() => selectLead(lead)}
                        className={cn(
                          "w-full border bg-card p-3 text-left transition-colors hover:bg-accent/20",
                          isSelected && "border-primary ring-1 ring-primary",
                        )}
                      >
                        <p className="truncate text-sm font-semibold text-primary">{lead.name}</p>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">{proj?.name ?? lead.projectInterest}</p>
                        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="truncate rounded-sm bg-muted px-1.5 py-0.5 text-[10px]">{lead.source}</span>
                          {lead.value != null && (
                            <span className="num shrink-0">{brlShort(lead.value)}</span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                  {cards.length === 0 && (
                    <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail panel */}
      {selectedLead && (
        <div className="mt-8 border bg-card">
          <div className="border-b px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-display text-2xl text-primary">{selectedLead.name}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {selectedLead.email}
                  {selectedLead.phone ? ` · ${selectedLead.phone}` : ""}
                </p>
              </div>
              <span className="shrink-0 rounded-sm bg-muted px-3 py-1 text-xs font-semibold">{selectedLead.status}</span>
            </div>

            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
              <p className="text-muted-foreground">
                Empreendimento:{" "}
                <strong className="text-foreground">
                  {data.projects.find((p) => p.id === selectedLead.projectInterest)?.name ?? selectedLead.projectInterest}
                </strong>
              </p>
              <p className="text-muted-foreground">
                Origem: <strong className="text-foreground">{selectedLead.source}</strong>
              </p>
              <p className="text-muted-foreground">
                Potencial:{" "}
                <strong className="num text-foreground">
                  {selectedLead.value != null ? brlShort(selectedLead.value) : "—"}
                </strong>
              </p>
            </div>
          </div>

          <div className="px-5 py-5">
            <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
              <div>
                <label className="block text-sm font-medium" htmlFor={`status-${selectedLead.id}`}>
                  Status
                </label>
                <select
                  id={`status-${selectedLead.id}`}
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value as LeadStatus)}
                  className="mt-2 border bg-background px-3 py-2 text-sm"
                >
                  {STAGES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium" htmlFor={`notes-${selectedLead.id}`}>
                  Observações
                </label>
                <textarea
                  id={`notes-${selectedLead.id}`}
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  className="mt-2 min-h-[4rem] w-full border bg-background p-3 text-sm"
                  placeholder="Anotações sobre o lead…"
                  maxLength={500}
                />
              </div>
            </div>

            <button
              onClick={() => saveLead(selectedLead)}
              className="mt-4 bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
            >
              Salvar (demonstração)
            </button>
          </div>
        </div>
      )}

      <p className="mt-5 text-xs text-muted-foreground">
        {totalLeads} lead{totalLeads !== 1 ? "s" : ""} no total. Alterações ficam nesta sessão e não são salvas.
      </p>
    </>
  );
}
