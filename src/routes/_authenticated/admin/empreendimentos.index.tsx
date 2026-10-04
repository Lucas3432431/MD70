import { createFileRoute, Link } from "@tanstack/react-router";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { projectSummary, budgetStatus } from "@/lib/data/admin-calculations";
import { brlShort } from "@/lib/format";
import type { ProjectStage } from "@/lib/data/admin-types";

export const Route = createFileRoute("/_authenticated/admin/empreendimentos/")({
  head: () => ({ meta: [
    { title: "Empreendimentos — Administração MD70" },
    { name: "description", content: "Pipeline de projetos e indicadores financeiros da área interna MD70." },
    { property: "og:title", content: "Empreendimentos MD70" },
    { property: "og:type", content: "website" },
  ] }),
  component: AdminProjects,
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

const STAGE_COLOR: Record<ProjectStage, string> = {
  "Oferecido / Interessado":  "border-t-muted-foreground/30",
  "Visita":                   "border-t-blue-300",
  "Business Plan / Capital":  "border-t-blue-500",
  "Projeto":                  "border-t-warning",
  "Proposta / Negociação":    "border-t-orange-400",
  "Construção / Reforma":     "border-t-primary",
  "Vendido":                  "border-t-positive",
};

const HEALTH_DOT: Record<ReturnType<typeof budgetStatus>, string> = {
  ok:   "bg-positive",
  warn: "bg-warning",
  over: "bg-destructive",
};

function AdminProjects() {
  const { data } = useAdmin();

  return (
    <>
      <AdminHeading title="Empreendimentos">Pipeline de projetos — do primeiro contato à venda.</AdminHeading>
      <div className="overflow-x-auto pb-4">
        <div className="flex gap-3" style={{ minWidth: `${STAGES.length * 216}px` }}>
          {STAGES.map((stage) => {
            const projects = data.projects.filter((p) => p.status === stage);
            return (
              <div key={stage} className="flex w-52 shrink-0 flex-col">
                {/* Column header */}
                <div className={`mb-3 border-t-2 pt-3 ${STAGE_COLOR[stage]}`}>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground leading-tight">{stage}</p>
                  <p className="num mt-1 font-display text-2xl text-primary">{projects.length}</p>
                </div>

                {/* Cards */}
                <div className="space-y-2">
                  {projects.map((p) => {
                    const s = projectSummary(data, p.id);
                    const health = s.budget > 0 ? budgetStatus(s.balance, s.budget) : null;
                    return (
                      <Link
                        key={p.id}
                        to="/admin/empreendimentos/$id"
                        params={{ id: p.id }}
                        className="block border bg-card p-3 transition-colors hover:bg-accent/20"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm font-semibold text-primary leading-tight">{p.name}</p>
                          {health && (
                            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${HEALTH_DOT[health]}`} aria-label={health === "ok" ? "Dentro do orçamento" : health === "warn" ? "Atenção" : "Acima do orçamento"} />
                          )}
                        </div>

                        {p.progress > 0 && (
                          <div className="mt-2">
                            <div className="h-1 bg-muted"><div className="h-full bg-primary" style={{ width: `${p.progress}%` }} /></div>
                            <p className="mt-1 text-[10px] text-muted-foreground">{p.progress}%</p>
                          </div>
                        )}

                        {s.capital > 0 && (
                          <div className="mt-2 grid grid-cols-2 gap-x-2 text-[10px]">
                            <span className="text-muted-foreground">Capital</span>
                            <span className="num text-right">{brlShort(s.capital)}</span>
                            <span className="text-muted-foreground">Forecast</span>
                            <span className="num text-right">{brlShort(s.forecast)}</span>
                          </div>
                        )}
                      </Link>
                    );
                  })}

                  {projects.length === 0 && (
                    <div className="border border-dashed p-3 text-center text-xs text-muted-foreground">—</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
