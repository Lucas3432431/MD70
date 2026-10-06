import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { brl, brlShort, monthLabel, pct } from "@/lib/format";
import type { MonthPoint } from "@/lib/data/portal";

const config = {
  value: { label: "Investimento", color: "var(--color-chart-1)" },
  cdiValue: { label: "CDI", color: "var(--color-chart-2)" },
} satisfies ChartConfig;

export function PortfolioChart({ data }: { data: MonthPoint[] }) {
  return (
    <ChartContainer config={config} className="h-[19rem] w-full aspect-auto">
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="month" tickFormatter={monthLabel} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis tickFormatter={brlShort} tickLine={false} axisLine={false} width={70} />
        <Tooltip content={({ active, payload, label }) => active && payload?.length ? <div className="border bg-popover p-3 text-xs shadow-soft"><p className="mb-2 font-semibold">{monthLabel(String(label))}</p><p>Investimento: <strong>{brl(Number(payload[0]?.value ?? 0))}</strong></p><p>CDI: <strong>{brl(Number(payload[1]?.value ?? 0))}</strong></p><p className="mt-1 text-muted-foreground">Rentabilidade no mês: {pct(Number(payload[0]?.payload.returnRate ?? 0))}</p></div> : null} />
        <Line type="monotone" dataKey="value" stroke="var(--color-value)" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
        <Line type="monotone" dataKey="cdiValue" stroke="var(--color-cdiValue)" strokeWidth={1.5} strokeDasharray="5 5" dot={false} />
      </LineChart>
    </ChartContainer>
  );
}
