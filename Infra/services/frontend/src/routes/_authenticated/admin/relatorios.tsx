import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useEffect } from "react";
import { ChevronDown } from "lucide-react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { PrevistVsRealizadoChart, type Period, periodKey, periodWindowFilter } from "@/components/admin/PrevistVsRealizadoChart";
import { brl } from "@/lib/format";
import { sum } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";

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

const PIE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

function originLabel(description: string): string {
  return description.includes(" — ") ? description.split(" — ")[0]! : description;
}

function CategoryDropdown({
  categories,
  selected,
  onChange,
}: {
  categories: string[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const allSelected = selected.size === 0;
  const label = allSelected ? "Todas as categorias" : selected.size === 1 ? [...selected][0]! : `${selected.size} categorias`;

  function toggle(c: string) {
    const next = new Set(selected);
    if (next.has(c)) next.delete(c); else next.add(c);
    onChange(next);
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
      >
        <span>{label}</span>
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 min-w-[200px] border bg-card shadow-md">
          <label className="flex cursor-pointer items-center gap-2 border-b px-3 py-2 text-sm hover:bg-muted">
            <input type="checkbox" checked={allSelected} onChange={() => onChange(new Set())} className="rounded" />
            <span className="font-medium">Todas</span>
          </label>
          <div className="max-h-56 overflow-y-auto">
            {categories.map((c) => (
              <label key={c} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-muted">
                <input type="checkbox" checked={selected.has(c)} onChange={() => toggle(c)} className="rounded" />
                <span>{c}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface DonutChartProps {
  data: { name: string; value: number }[];
  height?: number;
}

function DonutChart({ data, height = 140 }: DonutChartProps) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          cx="26%"
          cy="50%"
          innerRadius={22}
          outerRadius={38}
        >
          {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
        </Pie>
        <Tooltip
          formatter={(v: number, _name: string, props: { payload?: { name: string; value: number } }) => {
            const pct = total > 0 ? ((props.payload?.value ?? 0) / total * 100).toFixed(1) : "0";
            return [`${brl(v)} (${pct}%)`, props.payload?.name ?? ""];
          }}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend
          layout="vertical"
          align="right"
          verticalAlign="middle"
          iconType="circle"
          iconSize={6}
          wrapperStyle={{ fontSize: 10, maxWidth: "66%", lineHeight: "1.5", paddingRight: 4 }}
          formatter={(value: string, entry: { payload?: { value?: number } }) => (
            <span style={{ display: "inline-flex", maxWidth: 130, verticalAlign: "middle", fontSize: 10, color: "#000", gap: 4 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{value}</span>
              <span style={{ whiteSpace: "nowrap", flexShrink: 0 }}>· {brl(entry.payload?.value ?? 0)}</span>
            </span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

function Relatorios() {
  const { data } = useAdmin();
  const [period, setPeriod] = useState<Period>("year");
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());

  const allCategories = useMemo(
    () => Array.from(new Set(data.movements.map((m) => m.category))).sort(),
    [data.movements],
  );

  // Category filter only — used for the chart (shows full period window)
  const catFiltered = useMemo(
    () =>
      selectedCategories.size === 0
        ? data.movements
        : data.movements.filter((m) => selectedCategories.has(m.category)),
    [data.movements, selectedCategories],
  );

  // Category + period filter — used for KPIs and donuts
  const periodFiltered = useMemo(
    () => catFiltered.filter((m) => periodWindowFilter(m.date, period)),
    [catFiltered, period],
  );

  const realized = useMemo(() => periodFiltered.filter((m) => m.status === "Realizado"), [periodFiltered]);
  const forecastMvs = useMemo(
    () => catFiltered.filter((m) => m.status === "Previsto" || m.status === "Comprometido"),
    [catFiltered],
  );

  const totalEntradas = useMemo(() => sum(realized.filter((m) => m.direction === "Entrada").map((m) => m.value)), [realized]);
  const totalSaidas = useMemo(() => sum(realized.filter((m) => m.direction === "Saída").map((m) => m.value)), [realized]);
  const saldo = totalEntradas - totalSaidas;

  const forecastEntradas = useMemo(() => sum(forecastMvs.filter((m) => m.direction === "Entrada").map((m) => m.value)), [forecastMvs]);
  const forecastSaidas = useMemo(() => sum(forecastMvs.filter((m) => m.direction === "Saída").map((m) => m.value)), [forecastMvs]);
  const hasForecast = forecastEntradas > 0 || forecastSaidas > 0;

  const entradasByOrigem = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of realized.filter((m) => m.direction === "Entrada")) {
      const key = originLabel(m.description);
      map.set(key, (map.get(key) ?? 0) + m.value);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([name, value]) => ({ name, value }));
  }, [realized]);

  const saidasByCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of realized.filter((m) => m.direction === "Saída")) {
      map.set(m.category, (map.get(m.category) ?? 0) + m.value);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([name, value]) => ({ name, value }));
  }, [realized]);

  const PERIODS: { key: Period; label: string }[] = [
    { key: "year", label: "Ano" },
    { key: "month", label: "Mês" },
    { key: "week", label: "Semana" },
  ];

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <AdminHeading title="Relatórios">Visão consolidada financeira e operacional dos empreendimentos.</AdminHeading>

      {/* ── Filtros globais ─────────────────────────────────────────── */}
      <div className="mb-6 flex flex-wrap items-center gap-4 text-sm">
        <div className="flex rounded border">
          {PERIODS.map(({ key, label }) => (
            <button key={key} onClick={() => setPeriod(key)}
              className={cn(
                "px-4 py-1.5 transition-colors",
                period === key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
              )}>
              {label}
            </button>
          ))}
        </div>
        <CategoryDropdown
          categories={allCategories}
          selected={selectedCategories}
          onChange={setSelectedCategories}
        />
      </div>

      {/* ── KPI cards ───────────────────────────────────────────────── */}
      <div className="border bg-card p-5">
        <p className="text-xs text-muted-foreground">Saldo</p>
        <p className={cn("num mt-2 font-display text-3xl", saldo >= 0 ? "text-positive" : "text-destructive")}>{brl(saldo)}</p>
      </div>
      <div className="mt-px grid gap-px border-x border-b bg-border sm:grid-cols-2">
        <div className="bg-card p-5">
          <p className="text-xs text-muted-foreground">Entradas realizadas</p>
          <p className="num mt-2 font-display text-2xl text-positive">{brl(totalEntradas)}</p>
        </div>
        <div className="bg-card p-5">
          <p className="text-xs text-muted-foreground">Saídas realizadas</p>
          <p className="num mt-2 font-display text-2xl text-destructive">{brl(totalSaidas)}</p>
        </div>
      </div>

      {/* ── Forecast table ──────────────────────────────────────────── */}
      {hasForecast && (
        <section className="mt-8">
          <h2 className="font-display text-2xl text-primary">Previsto vs. Realizado</h2>
          <div className="mt-4 border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-4 py-2 text-left">Tipo</th>
                  <th className="px-4 py-2 text-right">Previsto</th>
                  <th className="px-4 py-2 text-right">Realizado</th>
                  <th className="px-4 py-2 text-right">Δ</th>
                </tr>
              </thead>
              <tbody>
                {forecastEntradas > 0 && (
                  <tr className="border-b">
                    <td className="px-4 py-3 font-medium text-positive">Entradas</td>
                    <td className="num px-4 py-3 text-right text-muted-foreground">{brl(forecastEntradas)}</td>
                    <td className="num px-4 py-3 text-right">{brl(totalEntradas)}</td>
                    <td className={cn("num px-4 py-3 text-right", totalEntradas >= forecastEntradas ? "text-positive" : "text-destructive")}>
                      {brl(totalEntradas - forecastEntradas)}
                    </td>
                  </tr>
                )}
                {forecastSaidas > 0 && (
                  <tr>
                    <td className="px-4 py-3 font-medium text-destructive">Saídas</td>
                    <td className="num px-4 py-3 text-right text-muted-foreground">{brl(forecastSaidas)}</td>
                    <td className="num px-4 py-3 text-right">{brl(totalSaidas)}</td>
                    <td className={cn("num px-4 py-3 text-right", totalSaidas <= forecastSaidas ? "text-positive" : "text-destructive")}>
                      {brl(totalSaidas - forecastSaidas)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Donut charts ────────────────────────────────────────────── */}
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <section>
          {entradasByOrigem.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nenhuma entrada registrada.</p>
          ) : (
            <div className="border bg-card p-4">
              <h2 className="mb-3 font-display text-xl text-primary">Entradas por origem</h2>
              <DonutChart data={entradasByOrigem} />
            </div>
          )}
        </section>

        <section>
          {saidasByCategory.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nenhuma saída registrada.</p>
          ) : (
            <div className="border bg-card p-4">
              <h2 className="mb-3 font-display text-xl text-primary">Saídas por categoria</h2>
              <DonutChart data={saidasByCategory} />
            </div>
          )}
        </section>
      </div>

      {/* ── Evolução temporal ───────────────────────────────────────── */}
      <section className="mt-10">
        <h2 className="font-display text-2xl text-primary">Evolução temporal</h2>
        <p className="mt-1 text-sm text-muted-foreground">Entradas e saídas realizadas e previstas por período.</p>
        <div className="mt-4 border bg-card p-4">
          <PrevistVsRealizadoChart period={period} movements={catFiltered} height={280} />
        </div>
      </section>
    </div>
  );
}
