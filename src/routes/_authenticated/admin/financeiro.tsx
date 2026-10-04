import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { brl, dateBR } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Movement } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/financeiro")({
  head: () => ({
    meta: [
      { title: "Financeiro — Administração MD70" },
      { name: "description", content: "Entradas, saídas e compromissos financeiros dos empreendimentos MD70." },
      { property: "og:title", content: "Financeiro administrativo MD70" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: Financeiro,
});

// ─── Shared movement card list ───────────────────────────────────────────────

function MovementList({ movements, projects }: { movements: Movement[]; projects: { id: string; name: string }[] }) {
  if (movements.length === 0) {
    return <p className="text-sm text-muted-foreground">Nenhum lançamento encontrado.</p>;
  }
  return (
    <div className="space-y-2">
      {movements.map((m) => {
        const projName = projects.find((p) => p.id === m.projectId)?.name ?? m.projectId;
        const isEntrada = m.direction === "Entrada";
        return (
          <div key={m.id} className="flex items-center gap-4 border bg-card px-4 py-4">
            <div className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold",
              isEntrada ? "bg-positive/15 text-positive" : "bg-destructive/15 text-destructive",
            )}>
              {isEntrada ? "+" : "−"}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{m.description}</p>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                <span>{projName}</span>
                <span className="opacity-40">·</span>
                <span>{dateBR(m.date)}</span>
                <span className="opacity-40">·</span>
                <span className="rounded-sm bg-muted px-1.5 py-0.5">{m.category}</span>
                {m.status !== "Realizado" && (
                  <>
                    <span className="opacity-40">·</span>
                    <span className="rounded-sm bg-warning/15 px-1.5 py-0.5 text-warning">{m.status}</span>
                  </>
                )}
              </p>
            </div>
            <p className={cn("num shrink-0 text-sm font-semibold", isEntrada ? "text-positive" : "text-destructive")}>
              {isEntrada ? "+" : "−"}{brl(m.value)}
            </p>
          </div>
        );
      })}
    </div>
  );
}

// ─── Shared filters ───────────────────────────────────────────────────────────

function Filters({
  project, onProject,
  category, onCategory,
  categories,
  projects,
}: {
  project: string; onProject: (v: string) => void;
  category: string; onCategory: (v: string) => void;
  categories: string[];
  projects: { id: string; name: string }[];
}) {
  return (
    <div className="mb-6 flex flex-wrap gap-3 text-sm">
      <label>
        Empreendimento{" "}
        <select value={project} onChange={(e) => onProject(e.target.value)} className="ml-2 border bg-background px-3 py-2">
          <option value="all">Todos</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
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
  );
}

// ─── Caixa tab — realized movements only ─────────────────────────────────────

function CaixaTab() {
  const { data } = useAdmin();
  const [project, setProject] = useState("all");
  const [category, setCategory] = useState("all");

  const allCategories = useMemo(
    () => Array.from(new Set(data.movements.map((m) => m.category))).sort(),
    [data.movements],
  );

  const movements = useMemo(
    () =>
      data.movements
        .filter(
          (m) =>
            m.status === "Realizado" &&
            (project === "all" || m.projectId === project) &&
            (category === "all" || m.category === category),
        )
        .sort((a, b) => b.date.localeCompare(a.date)),
    [data.movements, project, category],
  );

  return (
    <>
      <Filters project={project} onProject={setProject} category={category} onCategory={setCategory} categories={allCategories} projects={data.projects} />
      <MovementList movements={movements} projects={data.projects} />
      <p className="mt-4 text-xs text-muted-foreground">Caixa: apenas movimentos realizados — data do recebimento ou pagamento efetivo.</p>
    </>
  );
}

// ─── Competência tab — all statuses ──────────────────────────────────────────

function CompetenciaTab() {
  const { data } = useAdmin();
  const [project, setProject] = useState("all");
  const [category, setCategory] = useState("all");

  const allCategories = useMemo(
    () => Array.from(new Set(data.movements.map((m) => m.category))).sort(),
    [data.movements],
  );

  const movements = useMemo(
    () =>
      data.movements
        .filter(
          (m) =>
            (project === "all" || m.projectId === project) &&
            (category === "all" || m.category === category),
        )
        .sort((a, b) => b.date.localeCompare(a.date)),
    [data.movements, project, category],
  );

  return (
    <>
      <Filters project={project} onProject={setProject} category={category} onCategory={setCategory} categories={allCategories} projects={data.projects} />
      <MovementList movements={movements} projects={data.projects} />
      <p className="mt-4 text-xs text-muted-foreground">Competência: todos os lançamentos — data de reconhecimento da receita ou despesa, independente do pagamento.</p>
    </>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function Financeiro() {
  const [tab, setTab] = useState<"caixa" | "competencia">("caixa");

  return (
    <div className="lg:mx-auto lg:max-w-xl">
      <AdminHeading title="Financeiro">Histórico de lançamentos por empreendimento.</AdminHeading>

      <div className="mb-6 flex gap-1 border-b">
        {(["caixa", "competencia"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "border-b-2 -mb-px px-4 py-2 text-sm font-medium transition-colors",
              tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t === "caixa" ? "Caixa" : "Competência"}
          </button>
        ))}
      </div>

      {tab === "caixa" ? <CaixaTab /> : <CompetenciaTab />}
    </div>
  );
}
