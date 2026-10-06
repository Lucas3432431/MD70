import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { PrevistVsRealizadoChart } from "@/components/admin/PrevistVsRealizadoChart";
import { brl } from "@/lib/format";
import { sum } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

export const Route = createFileRoute("/_authenticated/admin/relatorios")({
  head: () => ({
    meta: [
      { title: "Relatórios — Administração MD70" },
      { name: "description", content: "Relatórios financeiros e operacionais dos empreendimentos MD70." },
      { property: "og:title", content: "Relatórios administrativos MD70" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: Relatorios,
});

const PIE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"];

function Relatorios() {
  const { data } = useAdmin();

  const totalEntradas = useMemo(
    () => sum(data.movements.filter((m) => m.direction === "Entrada" && m.status === "Realizado").map((m) => m.value)),
    [data.movements],
  );
  const totalSaidas = useMemo(
    () => sum(data.movements.filter((m) => m.direction === "Saída" && m.status === "Realizado").map((m) => m.value)),
    [data.movements],
  );
  const saldo = totalEntradas - totalSaidas;

  const entradasByCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of data.movements.filter((m) => m.direction === "Entrada" && m.status === "Realizado")) {
      map.set(m.category, (map.get(m.category) ?? 0) + m.value);
    }
    return Array.from(map.entries()).map(([name, value]) => ({ name, value }));
  }, [data.movements]);

  const saidasByCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of data.movements.filter((m) => m.direction === "Saída" && m.status === "Realizado")) {
      map.set(m.category, (map.get(m.category) ?? 0) + m.value);
    }
    return Array.from(map.entries()).map(([name, value]) => ({ name, value }));
  }, [data.movements]);

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <AdminHeading title="Relatórios">Visão consolidada financeira e operacional dos empreendimentos.</AdminHeading>

      {/* Saldo — full width above */}
      <div className="border bg-card p-5">
        <p className="text-xs text-muted-foreground">Saldo</p>
        <p className={cn("num mt-2 font-display text-3xl", saldo >= 0 ? "text-positive" : "text-destructive")}>{brl(saldo)}</p>
      </div>
      {/* Entradas / Saídas — side by side below */}
      <div className="mt-px grid gap-px border-x border-b bg-border sm:grid-cols-2">
        <div className="bg-card p-5">
          <p className="text-xs text-muted-foreground">Entradas realizadas</p>
          <p className="num mt-2 font-display text-2xl text-primary">{brl(totalEntradas)}</p>
        </div>
        <div className="bg-card p-5">
          <p className="text-xs text-muted-foreground">Saídas realizadas</p>
          <p className="num mt-2 font-display text-2xl text-primary">{brl(totalSaidas)}</p>
        </div>
      </div>

      {/* Pie charts — entradas e saídas por destino */}
      <div className="mt-12 grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="font-display text-3xl text-primary">Entradas por origem</h2>
          <p className="mt-1 text-sm text-muted-foreground">Categoria das entradas realizadas.</p>
          {entradasByCategory.length === 0 ? (
            <p className="mt-6 text-sm text-muted-foreground">Nenhuma entrada registrada.</p>
          ) : (
            <div className="mt-6 border bg-card p-4">
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={entradasByCategory} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={75} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                    {entradasByCategory.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => brl(v)} contentStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
              <ul className="mt-3 space-y-1">
                {entradasByCategory.map(({ name, value }, i) => (
                  <li key={name} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2">
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      {name}
                    </span>
                    <span className="num font-medium">{brl(value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section>
          <h2 className="font-display text-3xl text-primary">Saídas por destino</h2>
          <p className="mt-1 text-sm text-muted-foreground">Categoria das saídas realizadas.</p>
          {saidasByCategory.length === 0 ? (
            <p className="mt-6 text-sm text-muted-foreground">Nenhuma saída registrada.</p>
          ) : (
            <div className="mt-6 border bg-card p-4">
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={saidasByCategory} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={75} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                    {saidasByCategory.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => brl(v)} contentStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
              <ul className="mt-3 space-y-1">
                {saidasByCategory.map(({ name, value }, i) => (
                  <li key={name} className="flex items-center justify-between text-xs">
                    <span className="flex items-center gap-2">
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      {name}
                    </span>
                    <span className="num font-medium">{brl(value)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>

      {/* Previsto vs Realizado — line chart with period switcher */}
      <section className="mt-12">
        <h2 className="font-display text-3xl text-primary">Previsto vs. Realizado</h2>
        <p className="mt-1 text-sm text-muted-foreground">Saídas realizadas versus orçamento previsto, por período.</p>
        <div className="mt-6 border bg-card p-4">
          <PrevistVsRealizadoChart height={280} />
        </div>
      </section>

      <p className="mt-8 text-xs text-muted-foreground">Dados de demonstração. Valores fictícios — não representam informações reais.</p>
    </div>
  );
}
