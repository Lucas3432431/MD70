import { useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine } from "recharts";
import { brl, brlShort } from "@/lib/format";
import type { Movement } from "@/lib/data/admin-types";

export type Period = "year" | "month" | "week";

const TODAY = new Date();

function currentYearMonths(): string[] {
  const y = TODAY.getFullYear();
  return Array.from({ length: 12 }, (_, i) => `${y}-${String(i + 1).padStart(2, "0")}`);
}

function currentMonthWeeks(): string[] {
  const y = TODAY.getFullYear();
  const m = TODAY.getMonth();
  const firstDay = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0);
  const weeks: string[] = [];
  let d = new Date(firstDay);
  while (d <= lastDay) {
    weeks.push(isoWeek(d));
    d.setDate(d.getDate() + 7);
  }
  return [...new Set(weeks)];
}

function currentWeekDays(): string[] {
  const d = new Date(TODAY);
  const dow = d.getDay();
  const monday = new Date(d);
  monday.setDate(d.getDate() - (dow === 0 ? 6 : dow - 1));
  return Array.from({ length: 7 }, (_, i) => {
    const day = new Date(monday);
    day.setDate(monday.getDate() + i);
    return day.toISOString().slice(0, 10);
  });
}

function isoWeek(d: Date): string {
  const jan1 = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(((d.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

export function periodKey(date: string, p: Period): string {
  if (p === "year") return date.slice(0, 7);
  if (p === "month") return isoWeek(new Date(date + "T12:00:00"));
  return date.slice(0, 10);
}

export function periodLabel(key: string, p: Period): string {
  if (p === "year") {
    const [, m = "01"] = key.split("-");
    return new Date(2000, +m - 1, 1).toLocaleString("pt-BR", { month: "short" });
  }
  if (p === "month") return key.replace(/^\d{4}-/, "");
  const d = new Date(key + "T12:00:00");
  return d.toLocaleString("pt-BR", { weekday: "short", day: "2-digit" });
}

function windowKeys(p: Period): string[] {
  if (p === "year") return currentYearMonths();
  if (p === "month") return currentMonthWeeks();
  return currentWeekDays();
}

export function periodWindowFilter(date: string, p: Period): boolean {
  const keys = new Set(windowKeys(p));
  return keys.has(periodKey(date, p));
}

interface Props {
  period: Period;
  movements: Movement[];
  height?: number;
}

export function PrevistVsRealizadoChart({ period, movements, height = 240 }: Props) {
  const hasForecastEntradas = useMemo(
    () => movements.some((m) => (m.status === "Previsto" || m.status === "Comprometido") && m.direction === "Entrada"),
    [movements],
  );
  const hasForecastSaidas = useMemo(
    () => movements.some((m) => (m.status === "Previsto" || m.status === "Comprometido") && m.direction === "Saída"),
    [movements],
  );

  const todayPeriodKey = periodKey(TODAY.toISOString().slice(0, 10), period);

  const { chartData, todayLabel } = useMemo(() => {
    type Bucket = { entradasReal: number; saidasReal: number; entradasPrev: number; saidasPrev: number };
    const buckets = new Map<string, Bucket>();

    const keys = windowKeys(period);
    for (const k of keys) buckets.set(k, { entradasReal: 0, saidasReal: 0, entradasPrev: 0, saidasPrev: 0 });

    for (const m of movements) {
      const k = periodKey(m.date, period);
      if (!buckets.has(k)) continue;
      const b = buckets.get(k)!;
      const isReal = m.status === "Realizado";
      const isPrev = m.status === "Previsto" || m.status === "Comprometido";
      if (m.direction === "Entrada") {
        if (isReal) b.entradasReal += m.value;
        if (isPrev) b.entradasPrev += m.value;
      } else {
        if (isReal) b.saidasReal += m.value;
        if (isPrev) b.saidasPrev += m.value;
      }
    }

    const todayIdx = keys.indexOf(todayPeriodKey);
    const tLabel = todayIdx >= 0 ? periodLabel(todayPeriodKey, period) : null;

    const data = Array.from(buckets.entries())
      .map(([k, v], idx) => {
        const isFuture = todayIdx >= 0 && idx > todayIdx;
        return {
          name: periodLabel(k, period),
          "Entradas realizadas": isFuture ? null : v.entradasReal,
          "Saídas realizadas": isFuture ? null : v.saidasReal,
          ...(hasForecastEntradas ? { "Entradas previstas": v.entradasPrev } : {}),
          ...(hasForecastSaidas ? { "Saídas previstas": v.saidasPrev } : {}),
        };
      });

    return { chartData: data, todayLabel: tLabel };
  }, [movements, period, hasForecastEntradas, hasForecastSaidas, todayPeriodKey]);

  if (chartData.length === 0) {
    return <p className="text-sm text-muted-foreground">Nenhum dado disponível.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={(v: number) => brlShort(v)} tick={{ fontSize: 11 }} width={64} />
        <Tooltip formatter={(v: unknown) => typeof v === "number" ? brl(v) : "—"} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {todayLabel && (
          <ReferenceLine
            x={todayLabel}
            stroke="#94a3b8"
            strokeDasharray="5 3"
            label={{ value: "hoje", position: "insideTopRight", fontSize: 9, fill: "#94a3b8" }}
          />
        )}
        <Line type="monotone" dataKey="Entradas realizadas" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
        <Line type="monotone" dataKey="Saídas realizadas" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
        {hasForecastEntradas && (
          <Line type="monotone" dataKey="Entradas previstas" stroke="#22c55e" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 3 }} />
        )}
        {hasForecastSaidas && (
          <Line type="monotone" dataKey="Saídas previstas" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="4 2" dot={{ r: 3 }} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
