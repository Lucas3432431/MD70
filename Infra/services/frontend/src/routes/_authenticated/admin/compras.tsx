import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { Plus, Trash2, X, ChevronDown, Search, Filter } from "lucide-react";
import { toast } from "sonner";
import { useAdmin } from "@/components/admin/AdminLayout";
import { usePatchPurchase, useCreatePurchase, useDeletePurchase, useCreateQuote, usePatchQuote, useDeleteQuote } from "@/lib/hooks/useAdminData";
import { brl, dateBR, maskBRL, parseBRL } from "@/lib/format";
import { quoteTotal } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose,
} from "@/components/ui/drawer";
import { Switch } from "@/components/ui/switch";
import type { Purchase, PurchaseStatus, Quote } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/compras")({
  head: () => ({ meta: [
    { title: "Compras — Administração MD70" },
    { name: "description", content: "Kanban de compras: solicitação, cotações, aprovação e entrega." },
  ] }),
  component: Compras,
});

const OBRA_TYPES_FB = ["MO", "Material"];
const OBRA_CATEGORIES_FB = ["Alvenaria", "Aprovação", "Aquisição do imóvel", "Custo recorrente", "Elétrica", "Fundação", "Hidráulica", "Mão de obra", "Máquinas e equipamentos", "Projetos", "Segurança", "Outros"];

const STAGES: PurchaseStatus[] = [
  "Solicitado", "Fornecedores Contatados", "Orçamento 1", "Orçamento 2", "Orçamento 3",
  "Aguardando entrega", "Entregue", "Cancelado",
];

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

// ─── Quote form (inline add / edit) ──────────────────────────────────────────

function QuoteRow({
  purchaseId,
  quote,
  suppliers,
  onDelete,
}: {
  purchaseId: string;
  quote: Quote & { supplierName?: string };
  suppliers: { id: string; name: string }[];
  onDelete: (id: string) => void;
}) {
  const patchQuote = usePatchQuote();
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState({
    supplier_name: quote.supplierName ?? suppliers.find((s) => s.id === quote.supplierId)?.name ?? "",
    value: quote.value ? quote.value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0,00",
    shipping: quote.shipping ? quote.shipping.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0,00",
    discount: quote.discount ? quote.discount.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "0,00",
    payment: quote.payment,
    delivery: quote.delivery,
    validity: quote.validity,
    notes: quote.notes ?? "",
    attachment_url: quote.attachment ?? "",
  });
  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }
  const total = quoteTotal(quote);

  if (!edit) {
    return (
      <div className="flex items-start gap-3 border p-3 text-sm">
        <div className="flex-1">
          <p className="font-semibold">{suppliers.find((s) => s.id === quote.supplierId)?.name ?? "—"}</p>
          <p className="num mt-1 text-base text-primary">{brl(total)}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {brl(quote.value)} + frete {brl(quote.shipping)} − desc {brl(quote.discount)}
          </p>
          {quote.payment && <p className="mt-0.5 text-xs text-muted-foreground">Pgto: {quote.payment} · Entrega: {quote.delivery} · Val: {dateBR(quote.validity)}</p>}
        </div>
        <div className="flex gap-1">
          <button onClick={() => setEdit(true)} className="border px-2 py-1 text-xs hover:bg-muted">Editar</button>
          <button onClick={() => onDelete(quote.id)} className="border border-destructive/30 px-2 py-1 text-xs text-destructive hover:bg-destructive/5">
            <Trash2 className="size-3" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="border p-3">
      <div className="grid gap-2 sm:grid-cols-2 text-sm">
        <div>
          <label className="block text-xs text-muted-foreground">Fornecedor</label>
          <input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Valor (R$)</label>
          <input type="text" inputMode="numeric" value={form.value} onChange={(e) => set("value", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Frete (R$)</label>
          <input type="text" inputMode="numeric" value={form.shipping} onChange={(e) => set("shipping", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Desconto (R$)</label>
          <input type="text" inputMode="numeric" value={form.discount} onChange={(e) => set("discount", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Forma de pagamento</label>
          <input value={form.payment} onChange={(e) => set("payment", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Prazo de entrega</label>
          <input value={form.delivery} onChange={(e) => set("delivery", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Validade</label>
          <input type="date" value={form.validity} onChange={(e) => set("validity", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Observações</label>
          <input value={form.notes} onChange={(e) => set("notes", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div className="sm:col-span-2">
          <label className="block text-xs text-muted-foreground">Anexo (URL)</label>
          <input value={form.attachment_url} onChange={(e) => set("attachment_url", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" placeholder="https://…" />
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          onClick={() => {
            patchQuote.mutate({
              id: quote.id,
              ...(form.supplier_name ? { supplier_name: form.supplier_name } : {}),
              value: parseBRL(form.value),
              shipping: parseBRL(form.shipping),
              discount: parseBRL(form.discount),
              payment: form.payment,
              delivery: form.delivery,
              validity: form.validity,
              ...(form.notes ? { notes: form.notes } : {}),
              ...(form.attachment_url ? { attachment_url: form.attachment_url } : {}),
            }, {
              onSuccess: () => { toast.success("Cotação salva."); setEdit(false); },
              onError: () => toast.error("Erro ao salvar cotação."),
            });
          }}
          disabled={patchQuote.isPending}
          className="bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {patchQuote.isPending ? "Salvando…" : "Salvar"}
        </button>
        <button onClick={() => setEdit(false)} className="border px-4 py-1.5 text-xs text-muted-foreground hover:bg-muted">Cancelar</button>
      </div>
    </div>
  );
}

function NewQuoteForm({ purchaseId, onDone }: { purchaseId: string; onDone: () => void }) {
  const createQuote = useCreateQuote();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    supplier_name: "", value: "", shipping: "0,00", discount: "0,00",
    payment: "", delivery: "", validity: today, notes: "", attachment_url: "",
  });
  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  return (
    <div className="border border-dashed p-3 mt-2">
      <p className="mb-2 text-xs font-semibold text-muted-foreground">Nova cotação</p>
      <div className="grid gap-2 sm:grid-cols-2 text-sm">
        <div>
          <label className="block text-xs text-muted-foreground">Fornecedor *</label>
          <input value={form.supplier_name} onChange={(e) => set("supplier_name", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Valor (R$) *</label>
          <input type="text" inputMode="numeric" value={form.value} onChange={(e) => set("value", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Frete (R$)</label>
          <input type="text" inputMode="numeric" value={form.shipping} onChange={(e) => set("shipping", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Desconto (R$)</label>
          <input type="text" inputMode="numeric" value={form.discount} onChange={(e) => set("discount", maskBRL(e.target.value))}
            placeholder="0,00" className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Pgto</label>
          <input value={form.payment} onChange={(e) => set("payment", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Entrega</label>
          <input value={form.delivery} onChange={(e) => set("delivery", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Validade</label>
          <input type="date" value={form.validity} onChange={(e) => set("validity", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground">Anexo (URL)</label>
          <input value={form.attachment_url} onChange={(e) => set("attachment_url", e.target.value)}
            className="mt-1 w-full border bg-background px-2 py-1.5 text-sm" placeholder="https://…" />
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          onClick={() => {
            if (!form.supplier_name.trim() || !form.value) { toast.error("Fornecedor e valor obrigatórios."); return; }
            createQuote.mutate({
              purchase_id: purchaseId,
              supplier_name: form.supplier_name.trim(),
              value: parseBRL(form.value),
              shipping: parseBRL(form.shipping),
              discount: parseBRL(form.discount),
              payment: form.payment,
              delivery: form.delivery,
              validity: form.validity,
              ...(form.notes ? { notes: form.notes } : {}),
              ...(form.attachment_url ? { attachment_url: form.attachment_url } : {}),
            }, {
              onSuccess: () => { toast.success("Cotação adicionada."); onDone(); },
              onError: () => toast.error("Erro ao adicionar cotação."),
            });
          }}
          disabled={createQuote.isPending}
          className="bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {createQuote.isPending ? "Adicionando…" : "Adicionar"}
        </button>
        <button onClick={onDone} className="border px-4 py-1.5 text-xs text-muted-foreground hover:bg-muted">Cancelar</button>
      </div>
    </div>
  );
}

// ─── Purchase detail drawer ───────────────────────────────────────────────────

interface PurchaseForm {
  desc: string;
  qty: string;
  unit: string;
  note: string;
  newStatus: PurchaseStatus;
  is_operational: boolean;
  development_id: string;
  obra_type: string;
  obra_category: string;
  cnpj: string;
  recipient_name: string;
  attachment_url: string;
}

function PurchaseDrawer({
  purchase,
  projects,
  suppliers,
  minQuotes,
  obraCategories,
  obraTypes,
  onClose,
}: {
  purchase: Purchase | null;
  projects: { id: string; name: string }[];
  suppliers: { id: string; name: string }[];
  minQuotes: number;
  obraCategories: string[];
  obraTypes: string[];
  onClose: () => void;
}) {
  const patchPurchase = usePatchPurchase();
  const deletePurchase = useDeletePurchase();
  const deleteQuote = useDeleteQuote();
  const [addingQuote, setAddingQuote] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [form, setForm] = useState<PurchaseForm>({
    desc: purchase?.description ?? "",
    qty: String(purchase?.quantity ?? ""),
    unit: purchase?.unit ?? "",
    note: purchase?.note ?? "",
    newStatus: purchase?.status ?? "Solicitado",
    is_operational: purchase?.isOperational ?? false,
    development_id: purchase?.projectId ?? projects.find((p) => p.id !== "fundo-md70")?.id ?? "",
    obra_type: purchase?.obraType ?? obraTypes[0] ?? "",
    obra_category: purchase?.obraCategory ?? obraCategories[0] ?? "",
    cnpj: purchase?.cnpj ?? "",
    recipient_name: purchase?.recipientName ?? "",
    attachment_url: purchase?.attachment ?? "",
  });

  if (!purchase) return null;

  const p = purchase;
  const projName = projects.find((x) => x.id === p.projectId)?.name ?? "";

  function setStr(k: keyof { [P in keyof PurchaseForm as PurchaseForm[P] extends string ? P : never]: string }, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }
  function setBool(k: keyof { [P in keyof PurchaseForm as PurchaseForm[P] extends boolean ? P : never]: boolean }, v: boolean) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function saveDetails() {
    type DetailPatch = {
      id: string; quantity?: number; unit?: string; description?: string; note?: string;
      development_id?: string; cnpj?: string; recipient_name?: string;
      is_operational?: boolean; obra_type?: string; obra_category?: string; attachment?: string;
    };
    const patch: DetailPatch = { id: p.id };
    if (form.qty !== String(p.quantity)) patch.quantity = parseFloat(form.qty) || 1;
    if (form.unit !== p.unit) patch.unit = form.unit;
    if (form.desc !== p.description) patch.description = form.desc;
    if (form.note !== (p.note ?? "")) patch.note = form.note;
    if (form.is_operational !== (p.isOperational ?? false)) patch.is_operational = form.is_operational;
    if (!form.is_operational && form.development_id !== p.projectId) patch.development_id = form.development_id;
    if (!form.is_operational && form.obra_type !== (p.obraType ?? "")) patch.obra_type = form.obra_type;
    if (!form.is_operational && form.obra_category !== (p.obraCategory ?? "")) patch.obra_category = form.obra_category;
    if (form.cnpj !== (p.cnpj ?? "")) patch.cnpj = form.cnpj;
    if (form.recipient_name !== (p.recipientName ?? "")) patch.recipient_name = form.recipient_name;
    if (form.attachment_url !== (p.attachment ?? "")) patch.attachment = form.attachment_url;
    if (Object.keys(patch).length === 1) { toast("Sem alterações."); return; }
    patchPurchase.mutate(patch, {
      onSuccess: () => toast.success("Salvo."),
      onError: () => toast.error("Erro ao salvar."),
    });
  }

  function applyStatus() {
    if (form.newStatus === p.status) return;
    patchPurchase.mutate({ id: p.id, status: form.newStatus }, {
      onSuccess: () => toast.success("Status atualizado."),
      onError: () => toast.error("Erro ao atualizar status."),
    });
  }

  function handleDelete() {
    deletePurchase.mutate(p.id, {
      onSuccess: () => { toast.success("Excluído."); onClose(); },
      onError: () => toast.error("Erro ao excluir."),
    });
  }

  function handleDeleteQuote(qid: string) {
    if (!confirm("Excluir esta cotação?")) return;
    deleteQuote.mutate(qid, {
      onSuccess: () => toast.success("Cotação excluída."),
      onError: () => toast.error("Erro ao excluir cotação."),
    });
  }

  const cheapest = purchase.quotes.length ? Math.min(...purchase.quotes.map(quoteTotal)) : 0;

  return (
    <Drawer open onOpenChange={(v) => !v && onClose()}>
      <DrawerContent className="flex max-h-[92vh] flex-col lg:left-[25%] lg:right-[25%]">
        <DrawerHeader className="shrink-0 border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <DrawerTitle className="font-display text-2xl text-primary">{purchase.description}</DrawerTitle>
            <DrawerClose asChild>
              <button onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
            </DrawerClose>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{projName} · {dateBR(purchase.date)} · {purchase.requester}</p>
        </DrawerHeader>

        <div className="flex-1 overflow-y-auto">
        <div className="space-y-6 p-5">
          {/* Operational toggle */}
          <section>
            <label className="flex items-center justify-between gap-4 rounded border p-4">
              <div>
                <p className="text-sm font-medium">Operacional do fundo</p>
                <p className="text-xs text-muted-foreground">
                  {form.is_operational ? "Despesa do fundo, não vinculada a uma obra." : "Vinculada a um empreendimento."}
                </p>
              </div>
              <Switch
                checked={form.is_operational}
                onCheckedChange={(v) => setBool("is_operational", v)}
              />
            </label>
          </section>

          {/* Empreendimento + obra fields */}
          {!form.is_operational && (
            <section>
              <h3 className="mb-3 text-sm font-semibold text-primary">Empreendimento</h3>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="sm:col-span-3">
                  <label className="block text-xs text-muted-foreground">Empreendimento</label>
                  <select value={form.development_id} onChange={(e) => setStr("development_id", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground">Tipo</label>
                  <select value={form.obra_type} onChange={(e) => setStr("obra_type", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    {obraTypes.map((t) => <option key={t}>{t}</option>)}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs text-muted-foreground">Categoria da obra</label>
                  <select value={form.obra_category} onChange={(e) => setStr("obra_category", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    {obraCategories.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </div>
              </div>
            </section>
          )}

          {/* Editable basics */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Detalhes</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted-foreground">Descrição</label>
                <input value={form.desc} onChange={(e) => setStr("desc", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Quantidade</label>
                <input type="number" min="0.01" step="any" value={form.qty} onChange={(e) => setStr("qty", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Unidade</label>
                <input value={form.unit} onChange={(e) => setStr("unit", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted-foreground">Observações</label>
                <input value={form.note} onChange={(e) => setStr("note", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
            </div>
          </section>

          {/* Recipient */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Fornecedor / Destinatário</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs text-muted-foreground">CNPJ / CPF</label>
                <input value={form.cnpj} onChange={(e) => setStr("cnpj", e.target.value)} maxLength={18}
                  placeholder="00.000.000/0000-00"
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Nome / Razão social</label>
                <input value={form.recipient_name} onChange={(e) => setStr("recipient_name", e.target.value)} maxLength={200}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
            </div>
          </section>

          {/* Attachment */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Nota fiscal / Recibo</h3>
            {form.attachment_url ? (
              <div className="relative inline-block">
                <a href={form.attachment_url} target="_blank" rel="noopener noreferrer"
                  className="block overflow-hidden rounded border">
                  <img src={form.attachment_url} alt="Anexo"
                    className="h-28 w-auto max-w-[200px] object-cover"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                      const p = e.currentTarget.parentElement as HTMLElement;
                      p.innerHTML = '<div class="flex h-28 w-28 items-center justify-center bg-muted text-muted-foreground"><svg xmlns="http://www.w3.org/2000/svg" class="size-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg></div>';
                    }}
                  />
                </a>
                <button onClick={() => setStr("attachment_url", "")}
                  className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full bg-destructive text-white text-xs">
                  ×
                </button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground mb-2">Sem anexo.</p>
            )}
            <div className="mt-2">
              <label className="block text-xs text-muted-foreground">URL do anexo</label>
              <input type="url" value={form.attachment_url} onChange={(e) => setStr("attachment_url", e.target.value)}
                className="mt-1 w-full border bg-background px-3 py-2 text-sm" placeholder="https://…" />
            </div>
          </section>

          {/* Status */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Status</h3>
            <div className="flex flex-wrap items-center gap-3">
              <select value={form.newStatus} onChange={(e) => setForm((f) => ({ ...f, newStatus: e.target.value as PurchaseStatus }))}
                className="border bg-background px-3 py-2 text-sm">
                {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button onClick={applyStatus} disabled={patchPurchase.isPending}
                className="bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
                Aplicar
              </button>
              {purchase.approvedBy && (
                <p className="text-xs text-muted-foreground">Aprovado por {purchase.approvedBy} em {dateBR(purchase.approvedAt ?? purchase.date)}</p>
              )}
            </div>
          </section>

          {/* Quotes */}
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-primary">Cotações ({purchase.quotes.length})</h3>
              {!addingQuote && (
                <button onClick={() => setAddingQuote(true)}
                  className="flex items-center gap-1.5 border px-3 py-1.5 text-xs hover:bg-muted">
                  <Plus className="size-3" /> Nova cotação
                </button>
              )}
            </div>
            {purchase.quotes.length < minQuotes && purchase.quotes.length > 0 && (
              <p className="mb-2 border-l-2 border-warning bg-warning/10 p-2 text-xs">
                Apenas {purchase.quotes.length} cotação. Mínimo recomendado: {minQuotes}.
              </p>
            )}
            <div className="space-y-2">
              {purchase.quotes.map((q) => {
                const total = quoteTotal(q);
                const isBest = total === cheapest && purchase.quotes.length > 1;
                return (
                  <div key={q.id} className={cn(isBest && "ring-1 ring-positive/40")}>
                    {isBest && <span className="block bg-positive/10 px-3 py-0.5 text-[10px] font-semibold text-positive">Menor preço</span>}
                    <QuoteRow
                      purchaseId={purchase.id}
                      quote={{ ...q, ...(suppliers.find((s) => s.id === q.supplierId)?.name ? { supplierName: suppliers.find((s) => s.id === q.supplierId)!.name } : {}) }}
                      suppliers={suppliers}
                      onDelete={handleDeleteQuote}
                    />
                  </div>
                );
              })}
              {addingQuote && <NewQuoteForm purchaseId={purchase.id} onDone={() => setAddingQuote(false)} />}
              {purchase.quotes.length === 0 && !addingQuote && (
                <p className="text-xs text-muted-foreground">Nenhuma cotação. Adicione a primeira.</p>
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
              <button onClick={handleDelete} disabled={deleteInput !== "EXCLUIR" || deletePurchase.isPending}
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
              <button onClick={saveDetails} disabled={patchPurchase.isPending}
                className={cn(
                  "relative flex flex-1 items-center justify-center overflow-hidden py-2.5 text-sm font-semibold text-primary-foreground",
                  "bg-primary disabled:opacity-60",
                  "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
                )}>
                <span className="relative z-10">{patchPurchase.isPending ? "Salvando…" : "Salvar"}</span>
              </button>
            </div>
          )}
        </div>
      </DrawerContent>
    </Drawer>
  );
}

// ─── New purchase dialog ──────────────────────────────────────────────────────

// ─── Inline supplier combobox (portal-based, same pattern as financeiro) ──────

function QuoteSupplierSelect({
  value, onChange,
  contacts,
}: {
  value: string;
  onChange: (id: string) => void;
  contacts: { id: string; name: string; cnpj?: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dropPos, setDropPos] = useState<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 });
  const inputRef = useRef<HTMLInputElement>(null);
  const selected = contacts.find((s) => s.id === value);
  const filtered = query ? contacts.filter((s) => s.name.toLowerCase().includes(query.toLowerCase())) : contacts;

  function openDrop() {
    const r = inputRef.current?.getBoundingClientRect();
    if (r) setDropPos({ top: r.bottom + 2, left: r.left, width: r.width });
    setQuery("");
    setOpen(true);
  }
  function pick(id: string) { onChange(id); setQuery(""); setOpen(false); }

  return (
    <div>
      <label className="block text-sm font-medium">Fornecedor / Cliente</label>
      <div className="relative mt-1.5">
        <input ref={inputRef} type="text"
          value={open ? query : (selected?.name ?? "")}
          onChange={(e) => { setQuery(e.target.value); if (!open) openDrop(); }}
          onFocus={openDrop}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Buscar..."
          className="w-full border bg-background px-3 py-2 text-sm" />
        {value && (
          <button type="button" onMouseDown={(e) => { e.preventDefault(); pick(""); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="size-3" />
          </button>
        )}
      </div>
      {open && createPortal(
        <div style={{ position: "fixed", top: dropPos.top, left: dropPos.left, width: dropPos.width, zIndex: 9999 }}
          className="max-h-48 overflow-y-auto border bg-card shadow-lg">
          {filtered.map((s) => (
            <button key={s.id} type="button" onMouseDown={() => pick(s.id)}
              className={cn("flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/20", value === s.id && "bg-primary/10 text-primary")}>
              <span className="flex-1 truncate">{s.name}</span>
              {s.id.startsWith("lead:") ? <span className="shrink-0 rounded-sm bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">cliente</span>
                : s.cnpj ? <span className="shrink-0 text-xs text-muted-foreground">{s.cnpj}</span> : null}
            </button>
          ))}
          {filtered.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">Nenhum resultado.</p>}
        </div>,
        document.body,
      )}
    </div>
  );
}

// ─── New purchase dialog ──────────────────────────────────────────────────────

interface PendingQuote { supplierId: string; description: string; value: string }

function NewPurchaseDialog({
  projects, obraCategories, obraTypes, allContacts, onClose,
}: {
  projects: { id: string; name: string }[];
  obraCategories: string[];
  obraTypes: string[];
  allContacts: { id: string; name: string; cnpj?: string }[];
  onClose: () => void;
}) {
  const createPurchase = useCreatePurchase();
  const createQuote = useCreateQuote();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    development_id: projects[0]?.id ?? "", description: "", quantity: "1",
    requester: "", date: today,
    is_operational: false, obra_type: obraTypes[0] ?? "", obra_category: obraCategories[0] ?? "",
  });
  const [quotes, setQuotes] = useState<PendingQuote[]>([]);
  const [newQ, setNewQ] = useState<PendingQuote>({ supplierId: "", description: "", value: "" });

  function set(k: string, v: string | boolean) { setForm((f) => ({ ...f, [k]: v })); }

  function addQuote() {
    if (!newQ.supplierId || !newQ.value) { toast.error("Selecione fornecedor e informe o valor."); return; }
    setQuotes((q) => [...q, newQ]);
    setNewQ({ supplierId: "", description: "", value: "" });
  }

  function removeQuote(i: number) { setQuotes((q) => q.filter((_, idx) => idx !== i)); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.description.trim() || (!form.is_operational && !form.development_id)) {
      toast.error("Preencha os campos obrigatórios."); return;
    }
    try {
      const res = await createPurchase.mutateAsync({
        development_id: form.is_operational ? "fundo-md70" : form.development_id,
        description: form.description.trim(),
        quantity: parseFloat(form.quantity) || 1,
        unit: "serviço",
        date: form.date,
        is_operational: form.is_operational,
        ...(form.requester ? { requester: form.requester } : {}),
        ...(!form.is_operational ? { obra_type: form.obra_type, obra_category: form.obra_category } : {}),
      }) as { id: string };
      for (const q of quotes) {
        const supplierName = allContacts.find((s) => s.id === q.supplierId)?.name ?? q.supplierId;
        await createQuote.mutateAsync({
          purchase_id: res.id,
          supplier_name: supplierName,
          value: parseBRL(q.value),
          shipping: 0, discount: 0,
          ...(q.description ? { notes: q.description } : {}),
        });
      }
      toast.success("Solicitação criada.");
      onClose();
    } catch { toast.error("Erro ao criar."); }
  }

  const isPending = createPurchase.isPending || createQuote.isPending;

  return (
    <Drawer open onOpenChange={(v) => !v && onClose()}>
      <DrawerContent className="flex max-h-[92vh] flex-col lg:left-[25%] lg:right-[25%]">
        <DrawerHeader className="shrink-0 border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <DrawerTitle className="font-display text-2xl text-primary">Nova solicitação de compra</DrawerTitle>
            <DrawerClose asChild>
              <button onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
            </DrawerClose>
          </div>
        </DrawerHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <div className="space-y-5 p-5">
              {/* Operational toggle */}
              <label className="flex items-center justify-between gap-4 rounded border p-3">
                <div>
                  <p className="text-sm font-medium">Operacional do fundo</p>
                  <p className="text-xs text-muted-foreground">{form.is_operational ? "Não vinculado a obra" : "Vinculado a empreendimento"}</p>
                </div>
                <Switch checked={form.is_operational} onCheckedChange={(v) => set("is_operational", v)} />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                {!form.is_operational && (
                  <>
                    <div className="sm:col-span-2">
                      <label className="block text-sm font-medium">Empreendimento *</label>
                      <select required value={form.development_id} onChange={(e) => set("development_id", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium">Tipo obra</label>
                      <select value={form.obra_type} onChange={(e) => set("obra_type", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                        {obraTypes.map((t) => <option key={t}>{t}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium">Categoria da obra</label>
                      <select value={form.obra_category} onChange={(e) => set("obra_category", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                        {obraCategories.map((c) => <option key={c}>{c}</option>)}
                      </select>
                    </div>
                  </>
                )}
                <div className="sm:col-span-2">
                  <label className="block text-sm font-medium">Descrição *</label>
                  <input required value={form.description} onChange={(e) => set("description", e.target.value)} maxLength={200} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium">Solicitante</label>
                  <input value={form.requester} onChange={(e) => set("requester", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium">Data</label>
                  <input type="date" value={form.date} onChange={(e) => set("date", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium">Qtd</label>
                  <input type="number" min="0.01" step="any" value={form.quantity} onChange={(e) => set("quantity", e.target.value)} className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
                </div>
              </div>

              {/* Orçamentos */}
              <div>
                <p className="mb-2 text-sm font-semibold">Orçamentos</p>
                {quotes.length > 0 && (
                  <div className="mb-3 space-y-1">
                    {quotes.map((q, i) => {
                      const name = allContacts.find((s) => s.id === q.supplierId)?.name ?? q.supplierId;
                      return (
                        <div key={i} className="flex items-center gap-2 border px-3 py-2 text-sm">
                          <span className="flex-1 truncate font-medium">{name}</span>
                          {q.description && <span className="truncate text-xs text-muted-foreground">{q.description}</span>}
                          <span className="num shrink-0 text-primary">{brl(parseBRL(q.value))}</span>
                          <button type="button" onClick={() => removeQuote(i)}><X className="size-3.5 text-muted-foreground" /></button>
                        </div>
                      );
                    })}
                  </div>
                )}
                <div className="grid gap-3 border border-dashed p-3 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <QuoteSupplierSelect value={newQ.supplierId} onChange={(id) => setNewQ((q) => ({ ...q, supplierId: id }))} contacts={allContacts} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium">Detalhes</label>
                    <input value={newQ.description} onChange={(e) => setNewQ((q) => ({ ...q, description: e.target.value }))} maxLength={200}
                      className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" placeholder="Obs sobre este orçamento" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium">Valor (R$)</label>
                    <input type="text" inputMode="numeric" value={newQ.value} onChange={(e) => setNewQ((q) => ({ ...q, value: maskBRL(e.target.value) }))}
                      placeholder="0,00" className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
                  </div>
                  <div className="sm:col-span-2">
                    <button type="button" onClick={addQuote}
                      className="flex items-center gap-1.5 border px-3 py-1.5 text-xs font-medium text-primary hover:bg-accent/20">
                      <Plus className="size-3.5" /> Adicionar orçamento
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="shrink-0 border-t bg-background px-5 py-3">
            <button type="submit" disabled={isPending}
              className={cn(
                "relative flex w-full items-center justify-center overflow-hidden py-2.5 text-sm font-semibold text-primary-foreground",
                "bg-primary disabled:opacity-60",
                "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
              )}>
              <span className="relative z-10">{isPending ? "Criando…" : "Criar solicitação"}</span>
            </button>
          </div>
        </form>
      </DrawerContent>
    </Drawer>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function Compras() {
  const { data } = useAdmin();
  const [filterProject, setFilterProject] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [openStages, setOpenStages] = useState<Set<string>>(new Set());

  const allContacts = useMemo(() => [
    ...data.suppliers,
    ...data.leads.map(l => ({ id: `lead:${l.id}`, name: l.name, cnpj: l.cpf })),
  ], [data.suppliers, data.leads]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return data.purchases.filter((p) => {
      if (filterProject !== "all" && p.projectId !== filterProject) return false;
      if (q && !p.description.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data.purchases, filterProject, search]);
  const selectedPurchase = selected ? data.purchases.find((p) => p.id === selected) ?? null : null;

  function toggleStage(stage: string) {
    setOpenStages((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) next.delete(stage); else next.add(stage);
      return next;
    });
  }

  function renderPurchaseCard(p: typeof filtered[number]) {
    const proj = data.projects.find((x) => x.id === p.projectId);
    return (
      <button key={p.id} onClick={() => setSelected(p.id)}
        className="w-full border bg-card p-3 text-left transition-colors hover:bg-accent/20">
        <p className="truncate text-sm font-semibold text-primary">{p.description}</p>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">{proj?.name}</p>
        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
          <span>{p.quotes.length} cot.</span>
          <span className="num">{brl(p.estimate)}</span>
        </div>
      </button>
    );
  }

  return (
    <>
      <div className="sticky top-16 z-10 -mx-4 mb-6 border-b bg-background/95 px-4 pb-3 pt-3 backdrop-blur md:-mx-8 md:px-8">
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar compra..."
                className="w-full border bg-background pl-8 pr-3 py-2 text-sm"
              />
            </div>
            <label className="shrink-0">
              <select value={filterProject} onChange={(e) => setFilterProject(e.target.value)} className="border bg-background px-3 py-2 text-sm">
                <option value="all">Todos</option>
                {data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
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
            <span className="relative z-10">Nova solicitação</span>
          </button>
        </div>
      </div>

      {/* Mobile: collapsible stacked cards */}
      <div className="sm:hidden space-y-1">
        {STAGES.map((stage) => {
          const cards = filtered.filter((p) => p.status === stage);
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
                  {cards.map((p) => renderPurchaseCard(p))}
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
            const cards = filtered.filter((p) => p.status === stage);
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                <div className={`mb-3 border-t-2 pt-3 ${STAGE_COLOR[stage]}`}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{cards.length}</p>
                </div>
                <div className="space-y-2">
                  {cards.map((p) => renderPurchaseCard(p))}
                  {cards.length === 0 && <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <PurchaseDrawer
        purchase={selectedPurchase}
        projects={data.projects}
        suppliers={data.suppliers}
        minQuotes={data.minQuotes}
        obraCategories={data.obraCategories ?? OBRA_CATEGORIES_FB}
        obraTypes={data.obraTypes ?? OBRA_TYPES_FB}
        onClose={() => setSelected(null)}
      />

      {showNew && <NewPurchaseDialog
        projects={data.projects.filter(p => p.id !== 'fundo-md70')}
        obraCategories={data.obraCategories ?? OBRA_CATEGORIES_FB}
        obraTypes={data.obraTypes ?? OBRA_TYPES_FB}
        allContacts={allContacts}
        onClose={() => setShowNew(false)}
      />}
    </>
  );
}
