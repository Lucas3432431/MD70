import { useState, useMemo } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { useAdmin } from "@/components/admin/AdminLayout";
import { brl, brlShort } from "@/lib/format";
import { sum } from "@/lib/data/admin-calculations";
import { cn } from "@/lib/utils";

type Period = "year" | "month" | "week";

function periodKey(date: string, p: Period): string {
  if (p === "year") return date.slice(0, 4);
  if (p === "month") return date.slice(0, 7);
  const d = new Date(date + "T12:00:00");
  const jan1 = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(((d.getTime() - jan1.getTime()) / 86400000 + jan1.getDay() + 1) / 7);
  return `${d.getFullYear()}-W${String(week).padStart(2, "0")}`;
}

function periodLabel(key: string, p: Period): string {
  if (p === "year") return key;
  if (p === "month") {
    const parts = key.split("-");
    const y = parts[0] ?? "2000";
    const m = parts[1] ?? "01";
    return new Date(+y, +m - 1, 1).toLocaleString("pt-BR", { month: "short", year: "2-digit" });
  }
  return key;
}

export function PrevistVsRealizadoChart({ height = 240 }: { height?: number }) {
  const { data } = useAdmin();
  const [period, setPeriod] = useState<Period>("month");

  const chartData = useMemo(() => {
    const realized = data.movements.filter((m) => m.status === "Realizado");
    const map = new Map<string, number>();
    for (const m of realized) {
      const k = periodKey(m.date, period);
      map.set(k, (map.get(k) ?? 0) + (m.direction === "Saída" ? m.value : 0));
    }
    const keys = Array.from(map.keys()).sort();
    const totalBudget = sum(data.budgets.map((b) => b.planned));
    const previstoPer = keys.length > 0 ? totalBudget / keys.length : 0;
    return keys.map((k) => ({
      name: periodLabel(k, period),
      Previsto: Math.round(previstoPer),
      Realizado: map.get(k) ?? 0,
    }));
  }, [data, period]);

  return (
    <div>
      <div className="mb-4 flex gap-1">
        {(["year", "month", "week"] as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={cn(
              "border px-3 py-1 text-xs font-medium transition-colors",
              period === p
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {p === "year" ? "Ano" : p === "month" ? "Mês" : "Semana"}
          </button>
        ))}
      </div>
      {chartData.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nenhum dado disponível.</p>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={(v: number) => brlShort(v)} tick={{ fontSize: 11 }} width={64} />
            <Tooltip formatter={(v: number) => brl(v)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="Previsto" stroke="#3b82f6" strokeWidth={2} strokeDasharray="4 2" dot={{ r: 4 }} />
            <Line type="monotone" dataKey="Realizado" stroke="#22c55e" strokeWidth={2} dot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
