import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { brl, brlShort, dateBR } from "@/lib/format";
import { canApprove, quoteTotal } from "@/lib/data/admin-calculations";
import type { Purchase, PurchaseStatus } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/compras")({
  head: () => ({ meta: [
    { title: "Compras — Administração MD70" },
    { name: "description", content: "Kanban de compras: solicitação, cotações, aprovação e entrega." },
    { property: "og:title", content: "Compras administrativas MD70" },
    { property: "og:type", content: "website" },
  ] }),
  component: Compras,
});

const STAGES: PurchaseStatus[] = [
  "Solicitado", "Fornecedores Contatados", "Orçamento 1", "Orçamento 2", "Orçamento 3",
  "Aguardando entrega", "Entregue", "Cancelado",
];

const NEXT: Partial<Record<PurchaseStatus, PurchaseStatus>> = {
  "Solicitado":              "Fornecedores Contatados",
  "Fornecedores Contatados": "Orçamento 1",
  "Orçamento 1":       "Orçamento 2",
  "Orçamento 2":       "Orçamento 3",
  "Orçamento 3":       "Aguardando entrega",
  "Aguardando entrega":"Entregue",
};

const NEXT_LABEL: Partial<Record<PurchaseStatus, string>> = {
  "Solicitado":              "Contactar fornecedores",
  "Fornecedores Contatados": "Iniciar cotação",
  "Orçamento 1":       "2ª cotação recebida",
  "Orçamento 2":       "3ª cotação recebida",
  "Orçamento 3":       "Aprovar e avançar",
  "Aguardando entrega":"Confirmar entrega",
};

const STAGE_COLOR: Record<PurchaseStatus, string> = {
  "Solicitado":              "border-t-muted-foreground/30",
  "Fornecedores Contatados": "border-t-blue-200",
  "Orçamento 1":        "border-t-blue-300",
  "Orçamento 2":        "border-t-blue-500",
  "Orçamento 3":        "border-t-warning",
  "Aguardando entrega": "border-t-primary",
  "Entregue":           "border-t-positive",
  "Cancelado":          "border-t-destructive",
};

function Compras() {
  const { data, setData } = useAdmin();
  const [filterProject, setFilterProject] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [selection, setSelection] = useState("");
  const [reason, setReason] = useState("");
  const [feedback, setFeedback] = useState("");

  const filtered = data.purchases.filter(
    (p) => filterProject === "all" || p.projectId === filterProject,
  );

  function selectPurchase(p: Purchase) {
    if (selected === p.id) { setSelected(null); return; }
    setSelected(p.id);
    setSelection(p.selectedQuoteId ?? "");
    setReason("");
    setFeedback("");
  }

  function advance(p: Purchase) {
    const next = NEXT[p.status];
    if (!next) return;
    if (p.status === "Orçamento 3") {
      if (!canApprove(p, selection, reason, data.minQuotes)) {
        setFeedback("Selecione uma cotação. Se não for a de menor preço ou houver poucas cotações, registre uma justificativa.");
        return;
      }
      setData((prev) => ({
        ...prev,
        purchases: prev.purchases.map((item) =>
          item.id !== p.id ? item : {
            ...item, status: "Aguardando entrega" as PurchaseStatus,
            selectedQuoteId: selection,
            approvedBy: "Equipe MD70 (demonstração)",
            approvedAt: new Date().toISOString().slice(0, 10),
            ...(reason.trim() ? { justification: reason.trim() } : {}),
          },
        ),
      }));
    } else {
      setData((prev) => ({
        ...prev,
        purchases: prev.purchases.map((item) =>
          item.id !== p.id ? item : { ...item, status: next },
        ),
      }));
    }
    setFeedback("Atualizado (demonstração — não salvo).");
  }

  function cancel(p: Purchase) {
    setData((prev) => ({
      ...prev,
      purchases: prev.purchases.map((item) =>
        item.id !== p.id ? item : { ...item, status: "Cancelado" as PurchaseStatus },
      ),
    }));
    setSelected(null);
  }

  const selectedPurchase = selected ? data.purchases.find((p) => p.id === selected) : null;

  return (
    <>
      <AdminHeading title="Compras">Necessidade → Cotação → Aprovação → Entrega.</AdminHeading>

      {/* Filtro */}
      <div className="mb-6 text-sm">
        <label>
          Empreendimento{" "}
          <select value={filterProject} onChange={(e) => setFilterProject(e.target.value)} className="ml-2 border bg-background px-3 py-2">
            <option value="all">Todos</option>
            {data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>

      {/* Kanban */}
      <div className="overflow-x-auto pb-4">
        <div className="flex gap-3" style={{ minWidth: `${STAGES.length * 216}px` }}>
          {STAGES.map((stage) => {
            const cards = filtered.filter((p) => p.status === stage);
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                {/* Column header */}
                <div className={`mb-3 border-t-2 pt-3 ${STAGE_COLOR[stage]}`}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{cards.length}</p>
                </div>
                {/* Cards */}
                <div className="space-y-2">
                  {cards.map((p) => {
                    const proj = data.projects.find((x) => x.id === p.projectId);
                    const isSelected = selected === p.id;
                    return (
                      <button
                        key={p.id}
                        onClick={() => selectPurchase(p)}
                        className={`w-full border bg-card p-3 text-left transition-colors hover:bg-accent/20 ${isSelected ? "border-primary ring-1 ring-primary" : ""}`}
                      >
                        <p className="truncate text-sm font-semibold text-primary">{p.description}</p>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">{proj?.name}</p>
                        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                          <span>{p.quotes.length} cot.</span>
                          <span className="num">{brlShort(p.estimate)}</span>
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

      {/* Painel de detalhes */}
      {selectedPurchase && (
        <div className="mt-8 border bg-card">
          <div className="border-b px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-display text-2xl text-primary">{selectedPurchase.description}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {data.projects.find((p) => p.id === selectedPurchase.projectId)?.name}
                  {" · "}{dateBR(selectedPurchase.date)}
                  {" · "}Solicitante: {selectedPurchase.requester}
                </p>
              </div>
              <span className="shrink-0 rounded-sm bg-muted px-3 py-1 text-xs font-semibold">{selectedPurchase.status}</span>
            </div>
            <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
              <p className="text-muted-foreground">Qtd: <strong className="text-foreground">{selectedPurchase.quantity} {selectedPurchase.unit}</strong></p>
              <p className="text-muted-foreground">Estimativa: <strong className="num text-foreground">{brl(selectedPurchase.estimate)}</strong></p>
              <p className="text-muted-foreground">Cotações: <strong className="text-foreground">{selectedPurchase.quotes.length}</strong></p>
            </div>
          </div>

          {/* Comparação de cotações */}
          {selectedPurchase.quotes.length > 0 && (
            <div className="px-5 py-4">
              <h3 className="font-display text-xl text-primary">Comparação de cotações</h3>
              {selectedPurchase.quotes.length < data.minQuotes && (
                <p className="mt-3 border-l-2 border-warning bg-warning/10 p-3 text-sm">
                  Apenas {selectedPurchase.quotes.length} cotação. Mínimo recomendado: {data.minQuotes}.
                </p>
              )}
              <div className="mt-4 grid gap-3 lg:grid-cols-3">
                {selectedPurchase.quotes.map((q) => {
                  const total = quoteTotal(q);
                  const cheapest = Math.min(...selectedPurchase.quotes.map(quoteTotal));
                  const isBest = total === cheapest;
                  const canSelect = selectedPurchase.status === "Orçamento 3";
                  return (
                    <label key={q.id} className={`block border p-4 text-sm ${selection === q.id ? "border-primary bg-primary/5" : ""} ${isBest ? "ring-1 ring-positive/40" : ""}`}>
                      <span className="flex items-center gap-2">
                        {canSelect && <input type="radio" name={`quote-${selectedPurchase.id}`} value={q.id} checked={selection === q.id} onChange={() => setSelection(q.id)} />}
                        <strong>{data.suppliers.find((s) => s.id === q.supplierId)?.name}</strong>
                        {isBest && <span className="ml-auto rounded-sm bg-positive/15 px-1.5 py-0.5 text-[10px] font-semibold text-positive">Menor preço</span>}
                      </span>
                      <span className="num mt-3 block font-display text-2xl text-primary">{brl(total)}</span>
                      <span className="mt-2 block text-xs text-muted-foreground">Preço {brl(q.value)} · Frete {brl(q.shipping)} · Desconto {brl(q.discount)}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">Pagamento: {q.payment} · Entrega: {q.delivery}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">Validade: {dateBR(q.validity)}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {/* Ações */}
          <div className="border-t px-5 py-4">
            {selectedPurchase.approvedBy && (
              <p className="mb-4 text-xs text-muted-foreground">
                Aprovado por {selectedPurchase.approvedBy} em {dateBR(selectedPurchase.approvedAt ?? selectedPurchase.date)}.
                {selectedPurchase.justification && ` Justificativa: ${selectedPurchase.justification}`}
              </p>
            )}

            {NEXT[selectedPurchase.status] && (
              <div className="space-y-3">
                {selectedPurchase.status === "Orçamento 3" && (
                  <div className="max-w-xl">
                    <label className="block text-sm font-medium" htmlFor={`reason-${selectedPurchase.id}`}>
                      Justificativa (obrigatória se não for a de menor preço ou houver menos de {data.minQuotes} cotações)
                    </label>
                    <textarea
                      id={`reason-${selectedPurchase.id}`}
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      className="mt-2 min-h-20 w-full border bg-background p-3 text-sm"
                      maxLength={1000}
                      placeholder="Explique a escolha…"
                    />
                  </div>
                )}
                <div className="flex flex-wrap gap-3">
                  <button onClick={() => advance(selectedPurchase)} className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
                    {NEXT_LABEL[selectedPurchase.status]}
                  </button>
                  {selectedPurchase.status !== "Cancelado" && selectedPurchase.status !== "Entregue" && (
                    <button onClick={() => cancel(selectedPurchase)} className="border px-5 py-2.5 text-sm text-destructive hover:bg-destructive/5">
                      Cancelar compra
                    </button>
                  )}
                </div>
                {feedback && <p role="status" className="text-sm text-primary">{feedback}</p>}
              </div>
            )}

            {!NEXT[selectedPurchase.status] && (
              <p className="text-sm text-muted-foreground">
                {selectedPurchase.status === "Entregue" ? "Compra concluída." : "Compra cancelada."}
              </p>
            )}
          </div>
        </div>
      )}

    </>
  );
}
