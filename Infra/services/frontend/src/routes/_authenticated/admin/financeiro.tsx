import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import {
  FileText, Plus, Trash2, X, Search, Filter,
  Zap, Droplet, Hammer, Wrench, FileCheck, Home, TrendingUp,
  RefreshCw, ShieldCheck, Package, Percent, Layers, Landmark, Triangle,
} from "lucide-react";

const CATEGORY_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  "Capital":                 TrendingUp,
  "Alvenaria":               Layers,
  "Aprovação":               FileCheck,
  "Aquisição do imóvel":     Home,
  "Custo recorrente":        RefreshCw,
  "Elétrica":                Zap,
  "Fundação":                Landmark,
  "Hidráulica":              Droplet,
  "Mão de obra":             Hammer,
  "Máquinas e equipamentos": Wrench,
  "Projetos":                FileText,
  "Segurança":               ShieldCheck,
  "Telhado":                 Triangle,
  "Outros":                  Package,
  "Comissão":                Percent,
};
import { toast } from "sonner";
import { useAdmin } from "@/components/admin/AdminLayout";
import { useCreateMovement, usePatchMovement, useDeleteMovement } from "@/lib/hooks/useAdminData";
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose,
} from "@/components/ui/drawer";
import { Switch } from "@/components/ui/switch";
import { brl, dateBR, maskBRL, parseBRL } from "@/lib/format";
import { quoteTotal } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";
import type { Movement } from "@/lib/data/admin-types";

// quoteTotal is kept for potential future use in related-purchase display
void quoteTotal;

export const Route = createFileRoute("/_authenticated/admin/financeiro")({
  head: () => ({
    meta: [
      { title: "Lançamentos — Administração MD70" },
      { name: "description", content: "Entradas, saídas e compromissos financeiros dos empreendimentos MD70." },
    ],
  }),
  component: Financeiro,
});

// Fallbacks used only before /data loads; replaced by data.obraCategories / data.obraTypes
const OBRA_TYPES_FB = ["MO", "Material"];
const OBRA_CATEGORIES_FB = ["Capital", "Alvenaria", "Aprovação", "Aquisição do imóvel", "Custo recorrente", "Elétrica", "Fundação", "Hidráulica", "Mão de obra", "Máquinas e equipamentos", "Projetos", "Segurança", "Outros"];

function originLabel(description: string): string {
  return description.includes(" — ") ? description.split(" — ")[0]! : description;
}

// ─── Supplier select ──────────────────────────────────────────────────────────

function SupplierSelect({
  value,
  onChange,
  suppliers,
  label,
}: {
  value: string;
  onChange: (id: string) => void;
  suppliers: { id: string; name: string; cnpj?: string }[];
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dropPos, setDropPos] = useState<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 });
  const inputRef = useRef<HTMLInputElement>(null);
  const selected = suppliers.find((s) => s.id === value);

  const filtered = query
    ? suppliers.filter(
        (s) =>
          s.name.toLowerCase().includes(query.toLowerCase()) ||
          (s.cnpj ?? "").includes(query),
      )
    : suppliers;

  function openDrop() {
    const r = inputRef.current?.getBoundingClientRect();
    if (r) setDropPos({ top: r.bottom + 2, left: r.left, width: r.width });
    setQuery("");
    setOpen(true);
  }

  function pick(id: string) {
    onChange(id);
    setQuery("");
    setOpen(false);
  }

  return (
    <div>
      <label className="block text-xs text-muted-foreground">{label ?? "Fornecedor / Cliente"}</label>
      <div className="relative mt-1">
        <input
          ref={inputRef}
          type="text"
          value={open ? query : (selected?.name ?? "")}
          onChange={(e) => { setQuery(e.target.value); if (!open) openDrop(); }}
          onFocus={openDrop}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Buscar fornecedor..."
          className="w-full border bg-background px-3 py-2 text-sm"
        />
        {value && (
          <button
            type="button"
            onMouseDown={(e) => { e.preventDefault(); pick(""); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        )}
      </div>
      {open && createPortal(
        <div
          style={{ position: "fixed", top: dropPos.top, left: dropPos.left, width: dropPos.width, zIndex: 9999 }}
          className="max-h-48 overflow-y-auto border bg-card shadow-lg"
        >
          <button
            type="button"
            onMouseDown={() => pick("")}
            className="flex w-full px-3 py-2 text-left text-sm text-muted-foreground hover:bg-accent/20"
          >
            — Nenhum —
          </button>
          {filtered.map((s) => (
            <button
              key={s.id}
              type="button"
              onMouseDown={() => pick(s.id)}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/20",
                value === s.id && "bg-primary/10 text-primary",
              )}
            >
              <span className="flex-1 truncate">{s.name}</span>
              {s.id.startsWith("lead:")
                ? <span className="shrink-0 rounded-sm bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">cliente</span>
                : s.cnpj ? <span className="shrink-0 text-xs text-muted-foreground">{s.cnpj}</span> : null}
            </button>
          ))}
          {filtered.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">Nenhum resultado.</p>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}

// ─── Movement detail drawer ───────────────────────────────────────────────────

interface DrawerForm {
  description: string;
  category: string;
  direction: "Entrada" | "Saída";
  value: string;
  date: string;
  date_competencia: string;
  status: "Previsto" | "Comprometido" | "Realizado";
  is_operational: boolean;
  development_id: string;
  obra_type: string;
  obra_category: string;
  supplier_id: string;
  attachment_url: string;
}

function MovementDrawer({
  movement,
  projects,
  suppliers,
  obraCategories,
  obraTypes,
  onClose,
}: {
  movement: Movement | null;
  projects: { id: string; name: string }[];
  suppliers: { id: string; name: string; cnpj?: string }[];
  obraCategories: string[];
  obraTypes: string[];
  onClose: () => void;
}) {
  const patchMovement = usePatchMovement();
  const deleteMovement = useDeleteMovement();

  const initForm: DrawerForm = {
    description: movement?.description ?? "",
    category: movement?.category ?? "Comissão",
    direction: movement?.direction ?? "Saída",
    value: movement?.value ? movement.value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "",
    date: movement?.date ?? new Date().toISOString().slice(0, 10),
    date_competencia: movement?.dateCompetencia ?? "",
    status: movement?.status ?? "Realizado",
    is_operational: movement?.isOperational ?? false,
    development_id: movement?.projectId ?? projects.find((p) => p.id !== "fundo-md70")?.id ?? "",
    obra_type: movement?.obraType ?? obraTypes[0] ?? "",
    obra_category: movement?.obraCategory ?? movement?.category ?? obraCategories[0] ?? "",
    supplier_id: movement?.supplierId
      ?? (movement?.recipientName
        ? (suppliers.find((s) => s.name === movement.recipientName)?.id ?? "")
        : ""),
    attachment_url: movement?.attachments?.[0] ?? "",
  };
  const [form, setForm] = useState<DrawerForm>(initForm);
  const [deleteInput, setDeleteInput] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  function setStr(k: keyof { [P in keyof DrawerForm as DrawerForm[P] extends string ? P : never]: string }, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }
  function setBool(k: keyof { [P in keyof DrawerForm as DrawerForm[P] extends boolean ? P : never]: boolean }, v: boolean) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  if (!movement) return null;

  function save() {
    type PatchPayload = {
      id: string;
      description?: string;
      category?: string;
      direction?: "Entrada" | "Saída";
      value?: number;
      date?: string;
      date_competencia?: string | null;
      status?: "Previsto" | "Comprometido" | "Realizado";
      is_operational?: boolean;
      development_id?: string;
      obra_type?: string;
      obra_category?: string;
      supplier_id?: string | null;
      recipient_name?: string | null;
      attachment_url?: string | null;
    };
    const upd: PatchPayload = { id: movement!.id };
    if (form.description !== movement!.description) upd.description = form.description;
    if (form.direction !== movement!.direction) upd.direction = form.direction;
    const v = parseBRL(form.value);
    if (v !== movement!.value) upd.value = v;
    if (form.date !== movement!.date) upd.date = form.date;
    if (form.date_competencia !== (movement!.dateCompetencia ?? "")) upd.date_competencia = form.date_competencia || null;
    if (form.status !== movement!.status) upd.status = form.status;
    if (form.is_operational !== (movement!.isOperational ?? false)) upd.is_operational = form.is_operational;
    if (!form.is_operational && form.development_id !== movement!.projectId) upd.development_id = form.development_id;
    if (!form.is_operational && form.obra_type !== (movement!.obraType ?? "")) upd.obra_type = form.obra_type;
    if (form.is_operational) {
      if (form.category !== movement!.category) upd.category = form.category;
    } else {
      if (form.obra_category !== movement!.category) upd.category = form.obra_category;
      if (form.obra_category !== (movement!.obraCategory ?? "")) upd.obra_category = form.obra_category;
    }
    if (form.supplier_id.startsWith("lead:")) {
      const contact = suppliers.find((s) => s.id === form.supplier_id);
      upd.supplier_id = null;
      upd.recipient_name = contact?.name ?? null;
    } else if (form.supplier_id !== (movement!.supplierId ?? "")) {
      upd.supplier_id = form.supplier_id || null;
    }
    if (form.attachment_url !== (movement!.attachments?.[0] ?? "")) upd.attachment_url = form.attachment_url || null;
    if (Object.keys(upd).length === 1) { toast("Sem alterações."); return; }
    patchMovement.mutate(upd, {
      onSuccess: () => { toast.success("Lançamento salvo."); onClose(); },
      onError: () => toast.error("Erro ao salvar."),
    });
  }

  function handleDelete() {
    deleteMovement.mutate(movement!.id, {
      onSuccess: () => { toast.success("Lançamento excluído."); onClose(); },
      onError: () => toast.error("Erro ao excluir."),
    });
  }

  const isEntrada = form.direction === "Entrada";

  return (
    <Drawer open onOpenChange={(v) => !v && onClose()}>
      <DrawerContent className="flex max-h-[92vh] flex-col lg:left-[25%] lg:right-[25%]">
        <DrawerHeader className="shrink-0 border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <DrawerTitle className="font-display text-xl text-primary">{movement.description}</DrawerTitle>
            <DrawerClose asChild>
              <button onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
            </DrawerClose>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {isEntrada ? "+" : "−"}{brl(movement.value)} · {dateBR(movement.date)} · {movement.status}
          </p>
        </DrawerHeader>

        <div className="flex-1 overflow-y-auto">
        <div className="space-y-6 p-5">
          {/* Toggle: Empreendimento / Operacional */}
          <section>
            <label className="flex items-center justify-between gap-4 rounded border p-4">
              <div>
                <p className="text-sm font-medium">Operacional do fundo</p>
                <p className="text-xs text-muted-foreground">
                  {form.is_operational ? "Despesa ou receita do fundo, não vinculada a uma obra." : "Vinculado a um empreendimento."}
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
                  <label className="block text-xs text-muted-foreground">Categoria</label>
                  <select value={form.obra_category} onChange={(e) => setStr("obra_category", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    {obraCategories.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </div>
              </div>
            </section>
          )}

          {/* Core fields */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Lançamento</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="block text-xs text-muted-foreground">Descrição</label>
                <input value={form.description} onChange={(e) => setStr("description", e.target.value)} maxLength={200}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Tipo</label>
                <div className="mt-1 flex overflow-hidden border">
                  {(["Entrada", "Saída"] as const).map((d) => (
                    <button key={d} type="button" onClick={() => setStr("direction", d)}
                      className={cn(
                        "flex-1 py-2 text-sm transition-colors",
                        form.direction === d ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                      )}>
                      {d}
                    </button>
                  ))}
                </div>
              </div>
              {form.is_operational && (
                <div>
                  <label className="block text-xs text-muted-foreground">Categoria</label>
                  <select value={form.category} onChange={(e) => setStr("category", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    <option value="Comissão">Comissão</option>
                  </select>
                </div>
              )}
              <div>
                <label className="block text-xs text-muted-foreground">Valor (R$)</label>
                <input type="text" inputMode="numeric" value={form.value} onChange={(e) => setStr("value", maskBRL(e.target.value))}
                  placeholder="0,00"
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Status</label>
                <select value={form.status} onChange={(e) => setStr("status", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                  <option value="Realizado">Realizado</option>
                  <option value="Comprometido">Comprometido</option>
                  <option value="Previsto">Previsto</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Data Caixa</label>
                <input type="date" value={form.date} onChange={(e) => setStr("date", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground">Data Competência</label>
                <input type="date" value={form.date_competencia} onChange={(e) => setStr("date_competencia", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
                <p className="mt-0.5 text-xs text-muted-foreground">Se diferente do caixa.</p>
              </div>
            </div>
          </section>

          {/* Supplier */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Fornecedor / Cliente</h3>
            <SupplierSelect
              value={form.supplier_id}
              onChange={(v) => setStr("supplier_id", v)}
              suppliers={suppliers}
            />
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
              <label className="block text-xs text-muted-foreground">Anexar arquivo (PDF ou imagem)</label>
              <input type="file" accept="image/*,application/pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = () => setStr("attachment_url", reader.result as string);
                  reader.readAsDataURL(file);
                }}
                className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
            </div>
          </section>

          {/* Related quotes (from purchase) */}
          {movement.purchaseId && (
            <section>
              <h3 className="mb-3 text-sm font-semibold text-primary">Cotações da compra vinculada</h3>
              <p className="text-xs text-muted-foreground">ID: {movement.purchaseId}</p>
            </section>
          )}

        </div>
        </div>

        <div className="shrink-0 border-t bg-background px-5 py-3">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-2">
              <input autoFocus value={deleteInput} onChange={(e) => setDeleteInput(e.target.value)}
                placeholder="Digite EXCLUIR" className="flex-1 border bg-background px-3 py-2 text-sm" />
              <button onClick={handleDelete} disabled={deleteInput !== "EXCLUIR" || deleteMovement.isPending}
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
              <button onClick={save} disabled={patchMovement.isPending}
                className={cn(
                  "relative flex flex-1 items-center justify-center overflow-hidden py-2.5 text-sm font-semibold text-primary-foreground",
                  "bg-primary disabled:opacity-60",
                  "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
                )}>
                <span className="relative z-10">{patchMovement.isPending ? "Salvando…" : "Salvar"}</span>
              </button>
            </div>
          )}
        </div>
      </DrawerContent>
    </Drawer>
  );
}

// ─── Movement card ────────────────────────────────────────────────────────────

function MovementCard({
  m,
  projName,
  dateField,
  onClick,
}: {
  m: Movement;
  projName: string;
  dateField: "date" | "dateCompetencia";
  onClick: () => void;
}) {
  const isEntrada = m.direction === "Entrada";
  const displayDate = dateField === "dateCompetencia" ? (m.dateCompetencia ?? m.date) : m.date;
  const CatIcon = CATEGORY_ICON[m.category] ?? Package;
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-4 border bg-card px-4 py-4 text-left transition-colors hover:bg-accent/20"
    >
      <div className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
        isEntrada ? "bg-positive/15 text-positive" : "bg-destructive/15 text-destructive",
      )}>
        <CatIcon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{m.description}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          <span>{m.isOperational ? "Fundo MD70" : projName}</span>
          <span className="opacity-40">·</span>
          <span>{dateBR(displayDate)}</span>
          <span className="opacity-40">·</span>
          <span className="rounded-sm bg-muted px-1.5 py-0.5">{m.category}</span>
          {m.status !== "Realizado" && (
            <>
              <span className="opacity-40">·</span>
              <span className="rounded-sm bg-warning/15 px-1.5 py-0.5 text-warning">{m.status}</span>
            </>
          )}
          {m.cnpj && (
            <>
              <span className="opacity-40">·</span>
              <span>{m.cnpj}</span>
            </>
          )}
        </p>
        {m.recipientName && <p className="mt-0.5 truncate text-xs text-muted-foreground">{m.recipientName}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <p className={cn("num text-sm font-semibold", isEntrada ? "text-positive" : "text-destructive")}>
          {isEntrada ? "+" : "−"}{brl(m.value)}
        </p>
        {m.attachments?.[0] ? (
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded border bg-muted">
            <img src={m.attachments[0]} alt="Anexo" className="h-full w-full object-cover"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
                (e.currentTarget.nextElementSibling as HTMLElement).style.display = "flex";
              }}
            />
            <span className="absolute inset-0 hidden items-center justify-center text-muted-foreground">
              <FileText className="size-4" />
            </span>
          </div>
        ) : (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-dashed bg-muted/40 text-muted-foreground">
            <Plus className="size-4" />
          </div>
        )}
      </div>
    </button>
  );
}

// ─── New movement dialog ──────────────────────────────────────────────────────

function NewMovementDialog({
  projects,
  suppliers,
  obraCategories,
  obraTypes,
  onClose,
}: {
  projects: { id: string; name: string }[];
  suppliers: { id: string; name: string; cnpj?: string }[];
  obraCategories: string[];
  obraTypes: string[];
  onClose: () => void;
}) {
  const createMovement = useCreateMovement();
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    development_id: projects.find((p) => p.id !== "fundo-md70")?.id ?? "",
    description: "",
    category: "Comissão",
    direction: "Saída" as "Entrada" | "Saída",
    value: "",
    date: today,
    date_competencia: "",
    status: "Realizado" as "Previsto" | "Comprometido" | "Realizado",
    is_operational: false,
    obra_type: obraTypes[0] ?? "",
    obra_category: obraCategories[0] ?? "",
    supplier_id: "",
  });
  function set(k: string, v: string | boolean) { setForm((f) => ({ ...f, [k]: v })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = parseBRL(form.value);
    if (!form.description.trim() || value <= 0) { toast.error("Preencha todos os campos obrigatórios."); return; }
    try {
      await createMovement.mutateAsync({
        development_id: form.is_operational ? "fundo-md70" : form.development_id,
        description: form.description.trim(),
        category: form.is_operational ? form.category : form.obra_category,
        direction: form.direction,
        value,
        date: form.date,
        status: form.status,
        is_operational: form.is_operational,
        ...(form.date_competencia ? { date_competencia: form.date_competencia } : {}),
        ...(!form.is_operational ? { obra_type: form.obra_type, obra_category: form.obra_category } : {}),
        ...(form.supplier_id.startsWith("lead:")
          ? { recipient_name: suppliers.find((s) => s.id === form.supplier_id)?.name }
          : form.supplier_id ? { supplier_id: form.supplier_id } : {}),
      });
      toast.success("Lançamento criado.");
      onClose();
    } catch { toast.error("Erro ao criar lançamento."); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/60 p-4" onClick={onClose}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit} className="my-8 w-full max-w-xl border bg-card p-6 shadow-xl">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-display text-2xl text-primary">Novo lançamento</h2>
          <button type="button" onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
        </div>

        {/* Operational toggle */}
        <label className="mb-4 flex items-center justify-between gap-4 rounded border p-3">
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
                <select required value={form.development_id} onChange={(e) => set("development_id", e.target.value)}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                  {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium">Tipo obra</label>
                <select value={form.obra_type} onChange={(e) => set("obra_type", e.target.value)}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                  {obraTypes.map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium">Categoria</label>
                <select value={form.obra_category} onChange={(e) => set("obra_category", e.target.value)}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                  {obraCategories.map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium">Descrição *</label>
            <input required value={form.description} onChange={(e) => set("description", e.target.value)} maxLength={200}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Tipo</label>
            <div className="mt-1.5 flex overflow-hidden border">
              {(["Entrada", "Saída"] as const).map((d) => (
                <button key={d} type="button" onClick={() => set("direction", d)}
                  className={cn(
                    "flex-1 py-2 text-sm transition-colors",
                    form.direction === d ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                  )}>
                  {d}
                </button>
              ))}
            </div>
          </div>
          {form.is_operational && (
            <div>
              <label className="block text-sm font-medium">Categoria</label>
              <select value={form.category} onChange={(e) => set("category", e.target.value)}
                className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                <option value="Comissão">Comissão</option>
              </select>
            </div>
          )}
          <div>
            <label className="block text-sm font-medium">Valor (R$) *</label>
            <input type="text" inputMode="numeric" value={form.value} onChange={(e) => set("value", maskBRL(e.target.value))}
              placeholder="0,00"
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Status</label>
            <select value={form.status} onChange={(e) => set("status", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
              <option value="Realizado">Realizado</option>
              <option value="Comprometido">Comprometido</option>
              <option value="Previsto">Previsto</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Data Caixa *</label>
            <input required type="date" value={form.date} onChange={(e) => set("date", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium">Data Competência</label>
            <input type="date" value={form.date_competencia} onChange={(e) => set("date_competencia", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
          </div>
          <div className="sm:col-span-2">
            <SupplierSelect
              value={form.supplier_id}
              onChange={(v) => set("supplier_id", v)}
              suppliers={suppliers}
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="border px-5 py-2.5 text-sm text-muted-foreground hover:bg-muted">Cancelar</button>
          <button type="submit" disabled={createMovement.isPending}
            className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {createMovement.isPending ? "Criando…" : "Criar lançamento"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Scope toggle + filters ───────────────────────────────────────────────────

type Scope = "all" | "operational" | "empreendimentos";

function ScopeFilters({
  scope, onScope, projectId, onProject, category, onCategory, categories, projects, onNew, search, onSearch,
}: {
  scope: Scope; onScope: (v: Scope) => void;
  projectId: string; onProject: (v: string) => void;
  category: string; onCategory: (v: string) => void;
  categories: string[];
  projects: { id: string; name: string }[];
  onNew: () => void;
  search: string;
  onSearch: (v: string) => void;
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  return (
    <div className="sticky top-[104px] z-10 -mx-4 mb-4 border-b bg-background/95 px-4 pb-3 pt-3 backdrop-blur md:-mx-8 md:px-8 space-y-3">
      {/* Search row */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Buscar lançamento..."
            className="w-full border bg-background pl-8 pr-3 py-2 text-sm"
          />
        </div>
        <button
          onClick={() => setFilterOpen((v) => !v)}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center bg-primary text-primary-foreground",
            "relative overflow-hidden",
            "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
          )}
        >
          <Filter className="relative z-10 size-4" />
        </button>
      </div>

      {/* Filter panel */}
      {filterOpen && (
        <div className="border bg-card p-4 space-y-3 text-sm">
          <div>
            <p className="mb-2 text-xs text-muted-foreground">Escopo</p>
            <div className="flex rounded border">
              {([
                { key: "operational" as const, label: "Operacional" },
                { key: "empreendimentos" as const, label: "Empreendimentos" },
              ]).map(({ key, label }) => (
                <button key={key} onClick={() => onScope(scope === key ? "all" : key)}
                  className={cn(
                    "flex-1 px-4 py-1.5 transition-colors",
                    scope === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                  )}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {scope === "empreendimentos" && (
            <div>
              <label className="text-xs text-muted-foreground">Empreendimento</label>
              <select value={projectId} onChange={(e) => onProject(e.target.value)}
                className="mt-1 w-full border bg-background px-3 py-2">
                <option value="all">Todos</option>
                {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}

          {categories.length > 1 && (
            <div>
              <label className="text-xs text-muted-foreground">Categoria</label>
              <select value={category} onChange={(e) => onCategory(e.target.value)}
                className="mt-1 w-full border bg-background px-3 py-2">
                <option value="all">Todas</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          )}
        </div>
      )}

      {/* CTA */}
      <button
        onClick={onNew}
        className={cn(
          "flex w-full items-center justify-center gap-2 bg-primary py-3 text-sm font-medium text-primary-foreground",
          "relative overflow-hidden",
          "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
        )}
      >
        <Plus className="relative z-10 size-4" />
        <span className="relative z-10">Novo lançamento</span>
      </button>
    </div>
  );
}

function useMovementFilter(movements: ReturnType<typeof useAdmin>["data"]["movements"]) {
  const [scope, setScope] = useState<Scope>("all");
  const [projectId, setProjectId] = useState("all");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => movements.filter((m) => {
    if (scope === "operational" && !m.isOperational) return false;
    if (scope === "empreendimentos") {
      if (m.isOperational) return false;
      if (projectId !== "all" && m.projectId !== projectId) return false;
    }
    if (category !== "all" && m.category !== category) return false;
    if (search.trim() && !m.description.toLowerCase().includes(search.toLowerCase().trim()) && !(m.recipientName ?? "").toLowerCase().includes(search.toLowerCase().trim())) return false;
    return true;
  }), [movements, scope, projectId, category, search]);

  return { scope, setScope, projectId, setProjectId, category, setCategory, search, setSearch, filtered };
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────

function CaixaTab({ onNew, onSelect }: { onNew: () => void; onSelect: (id: string) => void }) {
  const { data } = useAdmin();
  const allCategories = useMemo(() => Array.from(new Set(data.movements.map((m) => m.category))).sort(), [data.movements]);
  const { scope, setScope, projectId, setProjectId, category, setCategory, search, setSearch, filtered } = useMovementFilter(data.movements);
  const movements = useMemo(() => filtered.filter((m) => m.status === "Realizado")
    .sort((a, b) => b.date.localeCompare(a.date)), [filtered]);

  return (
    <>
      <ScopeFilters
        scope={scope} onScope={setScope}
        projectId={projectId} onProject={setProjectId}
        category={category} onCategory={setCategory}
        categories={allCategories} projects={data.projects} onNew={onNew}
        search={search} onSearch={setSearch}
      />
      <div className="space-y-2">
        {movements.map((m) => {
          const projName = data.projects.find((p) => p.id === m.projectId)?.name ?? m.projectId;
          return <MovementCard key={m.id} m={m} projName={projName} dateField="date" onClick={() => onSelect(m.id)} />;
        })}
        {movements.length === 0 && <p className="text-sm text-muted-foreground">Nenhum lançamento encontrado.</p>}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">Caixa: apenas movimentos realizados — data do recebimento ou pagamento efetivo.</p>
    </>
  );
}

function CompetenciaTab({ onNew, onSelect }: { onNew: () => void; onSelect: (id: string) => void }) {
  const { data } = useAdmin();
  const allCategories = useMemo(() => Array.from(new Set(data.movements.map((m) => m.category))).sort(), [data.movements]);
  const { scope, setScope, projectId, setProjectId, category, setCategory, search, setSearch, filtered } = useMovementFilter(data.movements);
  const movements = useMemo(() => filtered.sort((a, b) => {
    const da = a.dateCompetencia ?? a.date;
    const db = b.dateCompetencia ?? b.date;
    return db.localeCompare(da);
  }), [filtered]);

  return (
    <>
      <ScopeFilters
        scope={scope} onScope={setScope}
        projectId={projectId} onProject={setProjectId}
        category={category} onCategory={setCategory}
        categories={allCategories} projects={data.projects} onNew={onNew}
        search={search} onSearch={setSearch}
      />
      <div className="space-y-2">
        {movements.map((m) => {
          const projName = data.projects.find((p) => p.id === m.projectId)?.name ?? m.projectId;
          return <MovementCard key={m.id} m={m} projName={projName} dateField="dateCompetencia" onClick={() => onSelect(m.id)} />;
        })}
        {movements.length === 0 && <p className="text-sm text-muted-foreground">Nenhum lançamento encontrado.</p>}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">Competência: todos os lançamentos — data de reconhecimento, independente do pagamento.</p>
    </>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function Financeiro() {
  const [tab, setTab] = useState<"caixa" | "competencia">("caixa");
  const [showNew, setShowNew] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data } = useAdmin();
  const selectedMovement = selectedId ? data.movements.find((m) => m.id === selectedId) ?? null : null;

  const allContacts = useMemo(() => [
    ...data.suppliers.map((s) => ({ id: s.id, name: s.name, cnpj: s.cnpj })),
    ...data.leads.map((l) => ({ id: `lead:${l.id}`, name: l.name, cnpj: l.cpf })),
  ], [data.suppliers, data.leads]);

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <div className="sticky top-16 z-[15] -mx-4 mb-6 border-b bg-background/95 backdrop-blur md:-mx-8">
        <div className="flex px-4 md:px-8">
          {(["caixa", "competencia"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={cn(
                "flex-1 border-b-2 -mb-px py-2.5 text-sm font-medium transition-colors",
                tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
              )}>
              {t === "caixa" ? "Caixa" : "Competência"}
            </button>
          ))}
        </div>
      </div>

      {tab === "caixa"
        ? <CaixaTab onNew={() => setShowNew(true)} onSelect={setSelectedId} />
        : <CompetenciaTab onNew={() => setShowNew(true)} onSelect={setSelectedId} />}

      <MovementDrawer
        key={selectedId ?? "none"}
        movement={selectedMovement}
        projects={data.projects}
        suppliers={allContacts}
        obraCategories={data.obraCategories ?? OBRA_CATEGORIES_FB}
        obraTypes={data.obraTypes ?? OBRA_TYPES_FB}
        onClose={() => setSelectedId(null)}
      />

      {showNew && <NewMovementDialog
        projects={data.projects}
        suppliers={allContacts}
        obraCategories={data.obraCategories ?? OBRA_CATEGORIES_FB}
        obraTypes={data.obraTypes ?? OBRA_TYPES_FB}
        onClose={() => setShowNew(false)}
      />}
    </div>
  );
}
