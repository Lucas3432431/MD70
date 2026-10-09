import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useEffect } from "react";
import { ChevronDown, ListFilter } from "lucide-react";
import { AdminHeading, useAdmin } from "@/components/admin/AdminLayout";
import { PrevistVsRealizadoChart, type Period, periodKey, periodWindowFilter } from "@/components/admin/PrevistVsRealizadoChart";
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

const PIE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

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
  hidden: Set<string>;
}

function DonutChart({ data, hidden }: DonutChartProps) {
  const visible = data.filter((d) => !hidden.has(d.name));
  const visibleTotal = visible.reduce((s, d) => s + d.value, 0);

  return (
    <div className="flex items-start gap-2">
      <div className="h-[80px] w-[80px] shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={visible}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={20}
              outerRadius={34}
              focusable={false}
              style={{ outline: "none" }}
            >
              {visible.map((entry) => {
                const origIdx = data.findIndex((d) => d.name === entry.name);
                return <Cell key={entry.name} fill={PIE_COLORS[origIdx % PIE_COLORS.length]} style={{ outline: "none" }} />;
              })}
            </Pie>
            <Tooltip
              formatter={(v: number, _name: string, props: { payload?: { name: string; value: number } }) => {
                const pct = visibleTotal > 0 ? ((props.payload?.value ?? 0) / visibleTotal * 100).toFixed(1) : "0";
                return [`${brl(v)} (${pct}%)`, props.payload?.name ?? ""];
              }}
              contentStyle={{ fontSize: 12 }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="min-w-0 flex-1" style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 10, lineHeight: "1.7" }}>
        {data.map((entry, i) => (
          <li key={i} style={{ display: "flex", alignItems: "center", gap: 4, overflow: "hidden", opacity: hidden.has(entry.name) ? 0.35 : 1 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: PIE_COLORS[i % PIE_COLORS.length], flexShrink: 0, display: "inline-block" }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0, color: "#000" }}>{entry.name}</span>
            <span style={{ whiteSpace: "nowrap", flexShrink: 0, color: "#000" }}>· {brl(entry.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Relatorios() {
  const { data } = useAdmin();
  const [period, setPeriod] = useState<Period>("year");
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [donutMode, setDonutMode] = useState<"categoria" | "origem" | "tipo">("categoria");
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set());
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) setFilterOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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

  const entradasDonut = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of realized.filter((m) => m.direction === "Entrada")) {
      const key = donutMode === "origem"
        ? (m.description.includes(" — ") ? m.description.split(" — ")[0]! : m.description)
        : donutMode === "tipo" ? (m.obraType ?? m.category) : m.category;
      map.set(key, (map.get(key) ?? 0) + m.value);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
  }, [realized, donutMode]);

  const saidasDonut = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of realized.filter((m) => m.direction === "Saída")) {
      const key = donutMode === "origem"
        ? (m.description.includes(" — ") ? m.description.split(" — ")[0]! : m.description)
        : donutMode === "tipo" ? (m.obraType ?? m.category) : m.category;
      map.set(key, (map.get(key) ?? 0) + m.value);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
  }, [realized, donutMode]);

  const allDonutKeys = useMemo(() => {
    const keys = new Set([...entradasDonut.map((d) => d.name), ...saidasDonut.map((d) => d.name)]);
    return Array.from(keys);
  }, [entradasDonut, saidasDonut]);

  useEffect(() => { setHiddenKeys(new Set()); }, [donutMode]);

  function toggleKey(key: string) {
    setHiddenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  const PERIODS: { key: Period; label: string }[] = [
    { key: "year", label: "Ano" },
    { key: "month", label: "Mês" },
    { key: "week", label: "Semana" },
  ];

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <AdminHeading title="Relatórios">Visão consolidada financeira e operacional dos empreendimentos.</AdminHeading>

      {/* ── Filtros globais ─────────────────────────────────────────── */}
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm">
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
        <p className={cn("num mt-2 font-display text-2xl sm:text-3xl", saldo >= 0 ? "text-positive" : "text-destructive")}>{brl(saldo)}</p>
      </div>
      <div className="mt-px grid grid-cols-2 gap-px border-x border-b bg-border">
        <div className="bg-card p-3 sm:p-5">
          <p className="truncate text-xs text-muted-foreground">Entradas realizadas</p>
          <p className="num mt-2 font-display text-xl sm:text-2xl text-positive">{brl(totalEntradas)}</p>
        </div>
        <div className="bg-card p-3 sm:p-5">
          <p className="truncate text-xs text-muted-foreground">Saídas realizadas</p>
          <p className="num mt-2 font-display text-xl sm:text-2xl text-destructive">{brl(totalSaidas)}</p>
        </div>
      </div>

      {/* ── Forecast table ──────────────────────────────────────────── */}
      {hasForecast && (
        <section className="mt-8">
          <h2 className="font-display text-2xl text-primary">Previsto vs. Realizado</h2>
          <div className="mt-4 overflow-x-auto border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="whitespace-nowrap px-3 py-2 text-left">Tipo</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right">Previsto</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right">Realizado</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right">Δ</th>
                </tr>
              </thead>
              <tbody>
                {forecastEntradas > 0 && (
                  <tr className="border-b">
                    <td className="whitespace-nowrap px-3 py-3 font-medium text-positive">Entradas</td>
                    <td className="num whitespace-nowrap px-3 py-3 text-right text-muted-foreground">{brl(forecastEntradas)}</td>
                    <td className="num whitespace-nowrap px-3 py-3 text-right">{brl(totalEntradas)}</td>
                    <td className={cn("num whitespace-nowrap px-3 py-3 text-right", totalEntradas >= forecastEntradas ? "text-positive" : "text-destructive")}>
                      {brl(totalEntradas - forecastEntradas)}
                    </td>
                  </tr>
                )}
                {forecastSaidas > 0 && (
                  <tr>
                    <td className="whitespace-nowrap px-3 py-3 font-medium text-destructive">Saídas</td>
                    <td className="num whitespace-nowrap px-3 py-3 text-right text-muted-foreground">{brl(forecastSaidas)}</td>
                    <td className="num whitespace-nowrap px-3 py-3 text-right">{brl(totalSaidas)}</td>
                    <td className={cn("num whitespace-nowrap px-3 py-3 text-right", totalSaidas <= forecastSaidas ? "text-positive" : "text-destructive")}>
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
      <div className="mt-8">
        <div className="mb-3 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Agrupar por</span>
          <select
            value={donutMode}
            onChange={(e) => setDonutMode(e.target.value as "categoria" | "origem" | "tipo")}
            className="border bg-background px-2 py-1 text-sm"
          >
            <option value="categoria">Categoria</option>
            <option value="origem">Origem</option>
            <option value="tipo">MO / Mat.</option>
          </select>
          <div className="relative" ref={filterRef}>
            <button
              onClick={() => setFilterOpen((v) => !v)}
              className={cn(
                "flex items-center gap-1 rounded border px-2 py-1 text-xs transition-colors hover:bg-muted",
                (filterOpen || hiddenKeys.size > 0) && "border-primary text-primary",
              )}
              title="Filtrar itens"
            >
              <ListFilter className="size-3.5" />
              {hiddenKeys.size > 0 && <span>{allDonutKeys.length - hiddenKeys.size}/{allDonutKeys.length}</span>}
            </button>
            {filterOpen && (
              <div className="absolute left-0 top-full z-50 mt-1 min-w-[200px] border bg-card shadow-md">
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <span className="text-xs font-medium text-muted-foreground">Filtrar itens</span>
                  <button
                    onClick={() => setHiddenKeys(new Set())}
                    className="text-xs text-primary hover:underline"
                  >
                    Limpar
                  </button>
                </div>
                <div className="grid grid-cols-2 divide-x">
                  {([
                    { label: "Entradas", items: entradasDonut },
                    { label: "Saídas",   items: saidasDonut },
                  ] as const).map(({ label, items }) => (
                    <div key={label} className="max-h-60 overflow-y-auto">
                      <p className="sticky top-0 bg-card px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground border-b">{label}</p>
                      {items.map(({ name }) => (
                        <label key={name} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted">
                          <input
                            type="checkbox"
                            checked={!hiddenKeys.has(name)}
                            onChange={() => toggleKey(name)}
                            className="rounded"
                          />
                          <span className={cn("flex-1 truncate", hiddenKeys.has(name) && "text-muted-foreground line-through")}>{name}</span>
                        </label>
                      ))}
                      {items.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">—</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <section>
            {entradasDonut.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma entrada.</p>
            ) : (
              <div className="flex h-full flex-col border bg-card p-2">
                <h2 className="mb-2 truncate font-display text-sm text-primary">Entradas</h2>
                <div className="flex flex-1 items-center">
                  <DonutChart data={entradasDonut} hidden={hiddenKeys} />
                </div>
              </div>
            )}
          </section>
          <section>
            {saidasDonut.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma saída.</p>
            ) : (
              <div className="flex h-full flex-col border bg-card p-2">
                <h2 className="mb-2 truncate font-display text-sm text-primary">Saídas</h2>
                <div className="flex flex-1 items-center">
                  <DonutChart data={saidasDonut} hidden={hiddenKeys} />
                </div>
              </div>
            )}
          </section>
        </div>
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
