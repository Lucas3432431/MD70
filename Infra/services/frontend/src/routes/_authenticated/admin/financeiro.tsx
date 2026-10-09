import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useEffect } from "react";
import { FileText, Plus, Trash2, X, Search } from "lucide-react";
import { toast } from "sonner";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { useCreateMovement, usePatchMovement, useDeleteMovement } from "@/lib/hooks/useAdminData";
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose,
} from "@/components/ui/drawer";
import { Switch } from "@/components/ui/switch";
import { brl, dateBR } from "@/lib/format";
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

const OBRA_TYPES = ["MO", "Material"];
const OBRA_CATEGORIES = ["Capital", "Alvenaria", "Aprovação", "Aquisição do imóvel", "Custo recorrente", "Elétrica", "Fundação", "Hidráulica", "Mão de obra", "Máquinas e equipamentos", "Projetos", "Outros"];

function originLabel(description: string): string {
  return description.includes(" — ") ? description.split(" — ")[0]! : description;
}

// ─── Recipient autocomplete ───────────────────────────────────────────────────

interface Recipient { name: string; cnpj: string }

function useRecipients(): Recipient[] {
  const { data } = useAdmin();
  return useMemo(() => {
    const seen = new Map<string, string>();
    for (const m of data.movements) {
      const name = m.recipientName?.trim() ?? "";
      const cnpj = m.cnpj?.trim() ?? "";
      if (name && !seen.has(name)) seen.set(name, cnpj);
    }
    return Array.from(seen.entries()).map(([name, cnpj]) => ({ name, cnpj }));
  }, [data.movements]);
}

function RecipientFields({
  name,
  cnpj,
  onName,
  onCnpj,
  recipients,
}: {
  name: string;
  cnpj: string;
  onName: (v: string) => void;
  onCnpj: (v: string) => void;
  recipients: Recipient[];
}) {
  const [nameSuggestions, setNameSuggestions] = useState<Recipient[]>([]);
  const [cnpjSuggestions, setCnpjSuggestions] = useState<Recipient[]>([]);
  const nameRef = useRef<HTMLDivElement>(null);
  const cnpjRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function close(e: MouseEvent) {
      if (nameRef.current && !nameRef.current.contains(e.target as Node)) setNameSuggestions([]);
      if (cnpjRef.current && !cnpjRef.current.contains(e.target as Node)) setCnpjSuggestions([]);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function onNameChange(v: string) {
    onName(v);
    const q = v.trim().toLowerCase();
    setNameSuggestions(q.length < 1 ? [] : recipients.filter((r) => r.name.toLowerCase().includes(q)).slice(0, 10));
  }
  function onCnpjChange(v: string) {
    onCnpj(v);
    const q = v.trim().toLowerCase();
    setCnpjSuggestions(q.length < 1 ? [] : recipients.filter((r) => r.cnpj.toLowerCase().includes(q)).slice(0, 10));
  }
  function pickName(r: Recipient) { onName(r.name); onCnpj(r.cnpj); setNameSuggestions([]); }
  function pickCnpj(r: Recipient) { onCnpj(r.cnpj); onName(r.name); setCnpjSuggestions([]); }

  return (
    <>
      <div className="relative" ref={cnpjRef}>
        <label className="block text-xs text-muted-foreground">CNPJ / CPF</label>
        <input value={cnpj} onChange={(e) => onCnpjChange(e.target.value)} maxLength={18}
          placeholder="00.000.000/0000-00"
          className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
        {cnpjSuggestions.length > 0 && (
          <ul className="absolute left-0 top-full z-50 w-full border bg-card shadow-md text-sm">
            {cnpjSuggestions.map((r, i) => (
              <li key={i}>
                <button type="button" onMouseDown={() => pickCnpj(r)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-muted">
                  <span className="truncate font-mono">{r.cnpj}</span>
                  {r.name && <span className="shrink-0 truncate text-xs text-muted-foreground max-w-[120px]">{r.name}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="relative" ref={nameRef}>
        <label className="block text-xs text-muted-foreground">Nome / Razão social</label>
        <input value={name} onChange={(e) => onNameChange(e.target.value)} maxLength={200}
          className="mt-1 w-full border bg-background px-3 py-2 text-sm" />
        {nameSuggestions.length > 0 && (
          <ul className="absolute left-0 top-full z-50 w-full border bg-card shadow-md text-sm">
            {nameSuggestions.map((r, i) => (
              <li key={i}>
                <button type="button" onMouseDown={() => pickName(r)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-muted">
                  <span className="truncate">{r.name}</span>
                  {r.cnpj && <span className="shrink-0 font-mono text-xs text-muted-foreground">{r.cnpj}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
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
  cnpj: string;
  recipient_name: string;
  attachment_url: string;
}

function MovementDrawer({
  movement,
  projects,
  onClose,
}: {
  movement: Movement | null;
  projects: { id: string; name: string }[];
  onClose: () => void;
}) {
  const patchMovement = usePatchMovement();
  const deleteMovement = useDeleteMovement();
  const recipients = useRecipients();

  const initForm: DrawerForm = {
    description: movement?.description ?? "",
    category: movement?.category ?? "Comissão",
    direction: movement?.direction ?? "Saída",
    value: String(movement?.value ?? ""),
    date: movement?.date ?? new Date().toISOString().slice(0, 10),
    date_competencia: movement?.dateCompetencia ?? "",
    status: movement?.status ?? "Realizado",
    is_operational: movement?.isOperational ?? false,
    development_id: movement?.projectId ?? projects.find((p) => p.id !== "fundo-md70")?.id ?? "",
    obra_type: movement?.obraType ?? OBRA_TYPES[0]!,
    obra_category: movement?.obraCategory ?? movement?.category ?? OBRA_CATEGORIES[0]!,
    cnpj: movement?.cnpj ?? "",
    recipient_name: movement?.recipientName || (movement ? originLabel(movement.description) : ""),
    attachment_url: movement?.attachments?.[0] ?? "",
  };
  const [form, setForm] = useState<DrawerForm>(initForm);

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
      cnpj?: string;
      recipient_name?: string;
      attachment_url?: string | null;
    };
    const upd: PatchPayload = { id: movement!.id };
    if (form.description !== movement!.description) upd.description = form.description;
    if (form.direction !== movement!.direction) upd.direction = form.direction;
    const v = parseFloat(form.value);
    if (!isNaN(v) && v !== movement!.value) upd.value = v;
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
    if (form.cnpj !== (movement!.cnpj ?? "")) upd.cnpj = form.cnpj;
    if (form.recipient_name !== (movement!.recipientName ?? "")) upd.recipient_name = form.recipient_name;
    if (form.attachment_url !== (movement!.attachments?.[0] ?? "")) upd.attachment_url = form.attachment_url || null;
    if (Object.keys(upd).length === 1) { toast("Sem alterações."); return; }
    patchMovement.mutate(upd, {
      onSuccess: () => { toast.success("Lançamento salvo."); onClose(); },
      onError: () => toast.error("Erro ao salvar."),
    });
  }

  function handleDelete() {
    if (!confirm("Excluir este lançamento?")) return;
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
                    {OBRA_TYPES.map((t) => <option key={t}>{t}</option>)}
                  </select>
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs text-muted-foreground">Categoria</label>
                  <select value={form.obra_category} onChange={(e) => setStr("obra_category", e.target.value)}
                    className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                    {OBRA_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
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
                <select value={form.direction} onChange={(e) => setStr("direction", e.target.value)}
                  className="mt-1 w-full border bg-background px-3 py-2 text-sm">
                  <option value="Entrada">Entrada</option>
                  <option value="Saída">Saída</option>
                </select>
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
                <input type="number" min="0.01" step="0.01" value={form.value} onChange={(e) => setStr("value", e.target.value)}
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

          {/* Recipient */}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-primary">Destinatário / Originador</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <RecipientFields
                name={form.recipient_name}
                cnpj={form.cnpj}
                onName={(v) => setStr("recipient_name", v)}
                onCnpj={(v) => setStr("cnpj", v)}
                recipients={recipients}
              />
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

          {/* Actions */}
          <section className="flex flex-wrap gap-3 border-t pt-4">
            <button onClick={save} disabled={patchMovement.isPending}
              className="bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
              {patchMovement.isPending ? "Salvando…" : "Salvar alterações"}
            </button>
            <button onClick={handleDelete}
              className="flex items-center gap-2 border border-destructive/30 px-4 py-2.5 text-sm text-destructive hover:bg-destructive/5">
              <Trash2 className="size-4" /> Excluir
            </button>
          </section>
        </div>
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
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-4 border bg-card px-4 py-4 text-left transition-colors hover:bg-accent/20"
    >
      <div className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold",
        isEntrada ? "bg-positive/15 text-positive" : "bg-destructive/15 text-destructive",
      )}>
        {isEntrada ? "+" : "−"}
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
  onClose,
}: {
  projects: { id: string; name: string }[];
  onClose: () => void;
}) {
  const createMovement = useCreateMovement();
  const recipients = useRecipients();
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
    obra_type: OBRA_TYPES[0],
    obra_category: OBRA_CATEGORIES[0],
    cnpj: "",
    recipient_name: "",
  });
  function set(k: string, v: string | boolean) { setForm((f) => ({ ...f, [k]: v })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = parseFloat(form.value);
    if (!form.description.trim() || isNaN(value) || value <= 0) { toast.error("Preencha todos os campos obrigatórios."); return; }
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
        ...(form.cnpj ? { cnpj: form.cnpj } : {}),
        ...(form.recipient_name ? { recipient_name: form.recipient_name } : {}),
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
                  {OBRA_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium">Categoria</label>
                <select value={form.obra_category} onChange={(e) => set("obra_category", e.target.value)}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
                  {OBRA_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
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
            <select value={form.direction} onChange={(e) => set("direction", e.target.value)}
              className="mt-1.5 w-full border bg-background px-3 py-2 text-sm">
              <option value="Entrada">Entrada</option>
              <option value="Saída">Saída</option>
            </select>
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
            <input required type="number" min="0.01" step="0.01" value={form.value} onChange={(e) => set("value", e.target.value)}
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
          <RecipientFields
            name={form.recipient_name}
            cnpj={form.cnpj}
            onName={(v) => set("recipient_name", v)}
            onCnpj={(v) => set("cnpj", v)}
            recipients={recipients}
          />
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
  const SCOPES: { key: Scope; label: string }[] = [
    { key: "all", label: "Todos" },
    { key: "operational", label: "Operacional" },
    { key: "empreendimentos", label: "Empreendimentos" },
  ];
  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded border text-sm">
          {SCOPES.map(({ key, label }) => (
            <button key={key} onClick={() => onScope(key)}
              className={cn(
                "px-4 py-1.5 transition-colors",
                scope === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}>
              {label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Buscar lançamento..."
            className="border bg-background pl-8 pr-3 py-1.5 text-sm w-44 sm:w-56"
          />
        </div>
        <button onClick={onNew} className="flex items-center gap-2 bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
          <Plus className="size-4" /> Novo lançamento
        </button>
      </div>
      {(scope === "empreendimentos" || scope === "all") && (
        <div className="flex flex-wrap gap-3 text-sm">
          {scope === "empreendimentos" && (
            <label>
              Empreendimento{" "}
              <select value={projectId} onChange={(e) => onProject(e.target.value)} className="ml-2 border bg-background px-3 py-2">
                <option value="all">Todos</option>
                {projects.filter((p) => p.id !== "fundo-md70").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          )}
          {categories.length > 1 && (
            <label>
              Categoria{" "}
              <select value={category} onChange={(e) => onCategory(e.target.value)} className="ml-2 border bg-background px-3 py-2">
                <option value="all">Todas</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          )}
        </div>
      )}
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

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <AdminHeading title="Lançamentos">Histórico de lançamentos por empreendimento.</AdminHeading>

      <div className="mb-6 flex gap-1 border-b">
        {(["caixa", "competencia"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={cn(
              "border-b-2 -mb-px px-4 py-2 text-sm font-medium transition-colors",
              tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
            )}>
            {t === "caixa" ? "Caixa" : "Competência"}
          </button>
        ))}
      </div>

      {tab === "caixa"
        ? <CaixaTab onNew={() => setShowNew(true)} onSelect={setSelectedId} />
        : <CompetenciaTab onNew={() => setShowNew(true)} onSelect={setSelectedId} />}

      <MovementDrawer
        key={selectedId ?? "none"}
        movement={selectedMovement}
        projects={data.projects}
        onClose={() => setSelectedId(null)}
      />

      {showNew && <NewMovementDialog projects={data.projects} onClose={() => setShowNew(false)} />}
    </div>
  );
}
