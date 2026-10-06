import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { brl } from "@/lib/format";
import { sum } from "@/lib/data/admin-calculations";

export const Route = createFileRoute("/_authenticated/admin/orcamento")({
  head: () => ({ meta: [
    { title: "Orçamento — Administração MD70" },
    { name: "description", content: "Orçamento e previsão por empreendimento e categoria." },
    { property: "og:title", content: "Orçamento administrativo MD70" },
    { property: "og:type", content: "website" },
  ] }),
  component: Orcamento,
});

const MOVEMENT_TO_BUDGET_CAT: Record<string, string> = {
  "Aquisição do imóvel": "Aquisição e Docs",
  "Aprovação": "Aquisição e Docs",
  "Projetos": "Projeto / Estudos",
};

function Orcamento() {
  const { data } = useAdmin();
  const [project, setProject] = useState(data.projects[0]?.id ?? "");
  const rows = data.budgets.filter((b) => b.projectId === project);
  const categories = [...new Set(rows.map((r) => r.category))];

  const realizedByCat = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of data.movements.filter(
      (m) => m.projectId === project && m.direction === "Saída" && m.status === "Realizado" && m.category !== "Capital"
    )) {
      const cat = MOVEMENT_TO_BUDGET_CAT[m.category] ?? "Obra";
      map.set(cat, (map.get(cat) ?? 0) + m.value);
    }
    return map;
  }, [data.movements, project]);

  function figures(items: typeof rows) {
    const planned = sum(items.map((b) => b.planned));
    const realized = sum(items.map((b) => realizedByCat.get(b.category) ?? 0));
    const committed = sum(items.map((b) => b.committed));
    const remaining = sum(items.map((b) => b.remaining));
    return [planned, committed, realized, realized + committed + remaining, planned - realized - committed - remaining];
  }

  return (
    <>
      <AdminHeading title="Orçamento">Do empreendimento à categoria e ao item, com previsão e saldo.</AdminHeading>
      <label className="block text-sm">
        Empreendimento{" "}
        <select value={project} onChange={(e) => setProject(e.target.value)} className="ml-2 border bg-background px-3 py-2">
          {data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <div className="mt-6 overflow-x-auto border">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr>
              {["Categoria / item", "Orçado", "Comprometido", "Realizado", "Forecast", "Saldo"].map((h) => (
                <th key={h} className="px-4 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <>
                <tr key={`${c}-head`} className="border-t bg-muted/30">
                  <th className="px-4 py-4 text-primary">{c}</th>
                  {figures(rows.filter((r) => r.category === c)).map((v, i) => (
                    <th key={i} className={`num px-4 py-4 font-semibold ${i === 4 && v < 0 ? "text-destructive" : ""}`}>{brl(v)}</th>
                  ))}
                </tr>
                {rows.filter((r) => r.category === c).map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="px-4 py-4 pl-8">{r.item}</td>
                    {figures([r]).map((v, i) => (
                      <td key={i} className={`num px-4 py-4 ${i === 4 && v < 0 ? "text-destructive" : ""}`}>{brl(v)}</td>
                    ))}
                  </tr>
                ))}
              </>
            ))}
            <tr className="border-t-2 bg-primary text-primary-foreground">
              <th className="px-4 py-4">Total do empreendimento</th>
              {figures(rows).map((v, i) => (
                <th key={i} className="num px-4 py-4">{brl(v)}</th>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-xs text-muted-foreground">Forecast = realizado + comprometido + estimativa restante. Realizado calculado dos lançamentos financeiros.</p>
    </>
  );
}
