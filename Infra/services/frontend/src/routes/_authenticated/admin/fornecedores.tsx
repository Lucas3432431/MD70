import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { Plus, Trash2, X, Search, Filter, Pencil } from "lucide-react";
import { toast } from "sonner";
import { useAdmin } from "@/components/admin/AdminLayout";
import { useCreateSupplier, usePatchSupplier, useDeleteSupplier } from "@/lib/hooks/useAdminData";
import { cn } from "@/lib/utils";
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerClose,
} from "@/components/ui/drawer";
import { maskCnpjCpf, maskPhone } from "@/lib/format";
import type { Supplier } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/fornecedores")({
  head: () => ({
    meta: [
      { title: "Fornecedores — Administração MD70" },
      { name: "description", content: "Cadastro de fornecedores e prestadores de serviço." },
    ],
  }),
  component: Fornecedores,
});

// ─── Form dialog (create / edit) ────────────────────────────────────────────

function SupplierDialog({
  supplier,
  onClose,
}: {
  supplier: Supplier | null;
  onClose: () => void;
}) {
  const createSupplier = useCreateSupplier();
  const patchSupplier = usePatchSupplier();
  const deleteSupplier = useDeleteSupplier();

  const [form, setForm] = useState({
    name: supplier?.name ?? "",
    cnpj: supplier?.cnpj ?? "",
    contact: supplier?.contact ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    notes: supplier?.notes ?? "",
  });
  const [deleteInput, setDeleteInput] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error("Nome obrigatório."); return; }
    const payload = {
      name: form.name.trim(),
      ...(form.cnpj ? { cnpj: form.cnpj.trim() } : {}),
      ...(form.contact ? { contact: form.contact.trim() } : {}),
      ...(form.phone ? { phone: form.phone.trim() } : {}),
      ...(form.email ? { email: form.email.trim() } : {}),
      ...(form.notes ? { notes: form.notes.trim() } : {}),
    };
    try {
      if (supplier) {
        await patchSupplier.mutateAsync({ id: supplier.id, ...payload });
        toast.success("Fornecedor atualizado.");
      } else {
        await createSupplier.mutateAsync(payload);
        toast.success("Fornecedor criado.");
      }
      onClose();
    } catch {
      toast.error("Erro ao salvar fornecedor.");
    }
  }

  async function handleDelete() {
    if (!supplier) return;
    try {
      await deleteSupplier.mutateAsync(supplier.id);
      toast.success("Fornecedor excluído.");
      onClose();
    } catch {
      toast.error("Erro ao excluir fornecedor.");
    }
  }

  const isPending = createSupplier.isPending || patchSupplier.isPending;

  return (
    <Drawer open onOpenChange={(v) => !v && onClose()}>
      <DrawerContent className="flex max-h-[92vh] flex-col lg:left-[25%] lg:right-[25%]">
        <DrawerHeader className="shrink-0 border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <DrawerTitle className="font-display text-2xl text-primary">
              {supplier ? "Editar fornecedor" : "Novo fornecedor"}
            </DrawerTitle>
            <DrawerClose asChild>
              <button onClick={onClose}><X className="size-5 text-muted-foreground" /></button>
            </DrawerClose>
          </div>
        </DrawerHeader>

        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium">Nome / Razão social *</label>
                <input required value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={200}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium">CNPJ / CPF</label>
                <input value={form.cnpj} onChange={(e) => set("cnpj", maskCnpjCpf(e.target.value))} maxLength={18}
                  placeholder="00.000.000/0000-00"
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium">Contato</label>
                <input value={form.contact} onChange={(e) => set("contact", e.target.value)} maxLength={100}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium">Telefone</label>
                <input value={form.phone} onChange={(e) => set("phone", maskPhone(e.target.value))} maxLength={20}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium">E-mail</label>
                <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)}
                  className="mt-1.5 w-full border bg-background px-3 py-2 text-sm" />
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm font-medium">Observações</label>
                <textarea value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={500} rows={2}
                  className="mt-1.5 w-full border bg-background p-2 text-sm" />
              </div>
            </div>
          </div>

          <div className="shrink-0 border-t bg-background px-5 py-3">
            {showDeleteConfirm ? (
              <div className="flex items-center gap-2">
                <input autoFocus value={deleteInput} onChange={(e) => setDeleteInput(e.target.value)}
                  placeholder="Digite EXCLUIR" className="flex-1 border bg-background px-3 py-2 text-sm" />
                <button type="button" onClick={handleDelete}
                  disabled={deleteInput !== "EXCLUIR" || deleteSupplier.isPending}
                  className="bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground disabled:opacity-40">
                  Confirmar
                </button>
                <button type="button" onClick={() => { setShowDeleteConfirm(false); setDeleteInput(""); }}
                  className="px-3 py-2 text-sm text-muted-foreground">×</button>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                {supplier && (
                  <button type="button" onClick={() => setShowDeleteConfirm(true)}
                    className="flex shrink-0 items-center gap-2 text-sm text-destructive">
                    <Trash2 className="size-4" /> Excluir
                  </button>
                )}
                <button type="submit" disabled={isPending}
                  className={cn(
                    "relative flex flex-1 items-center justify-center overflow-hidden py-2.5 text-sm font-semibold text-primary-foreground",
                    "bg-primary disabled:opacity-60",
                    "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
                  )}>
                  <span className="relative z-10">{isPending ? "Salvando…" : supplier ? "Salvar" : "Criar fornecedor"}</span>
                </button>
              </div>
            )}
          </div>
        </form>
      </DrawerContent>
    </Drawer>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function Fornecedores() {
  const { data } = useAdmin();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Supplier | null | "new">(null);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return data.suppliers;
    return data.suppliers.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.cnpj ?? "").toLowerCase().includes(q) ||
        (s.email ?? "").toLowerCase().includes(q) ||
        (s.contact ?? "").toLowerCase().includes(q),
    );
  }, [data.suppliers, search]);

  return (
    <>
      {/* Sticky search + CTA */}
      <div className="sticky top-16 z-10 -mx-4 mb-6 border-b bg-background/95 px-4 pb-3 pt-3 backdrop-blur md:-mx-8 md:px-8">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar fornecedor..."
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
            onClick={() => setEditing("new")}
            className={cn(
              "flex w-full items-center justify-center gap-2 bg-primary py-3 text-sm font-medium text-primary-foreground",
              "relative overflow-hidden",
              "before:absolute before:inset-0 before:-translate-x-full before:animate-[shimmer_2s_infinite] before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent",
            )}
          >
            <Plus className="relative z-10 size-4" />
            <span className="relative z-10">Novo fornecedor</span>
          </button>
        </div>
      </div>

      {/* List */}
      <div className="space-y-2">
        {filtered.map((s) => (
          <button
            key={s.id}
            onClick={() => setEditing(s)}
            className="flex w-full items-center gap-4 border bg-card px-4 py-3 text-left transition-colors hover:bg-accent/20"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-primary">{s.name}</p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {[s.cnpj, s.contact, s.phone].filter(Boolean).join(" · ") || "—"}
              </p>
            </div>
            {s.email && (
              <p className="shrink-0 text-xs text-muted-foreground hidden sm:block">{s.email}</p>
            )}
            <Pencil className="size-3.5 shrink-0 text-muted-foreground/50" />
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {search ? "Nenhum fornecedor encontrado." : "Nenhum fornecedor cadastrado."}
          </p>
        )}
      </div>

      {editing !== null && (
        <SupplierDialog
          supplier={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
