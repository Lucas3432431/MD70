import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";

const config = { planned: { label: "Previsto", color: "var(--color-chart-2)" }, actual: { label: "Realizado", color: "var(--color-chart-1)" } } satisfies ChartConfig;
export function BudgetChart({ data }: { data: { month: string; planned: number; actual: number | null }[] }) {
  return <ChartContainer config={config} className="h-[18rem] w-full aspect-auto"><LineChart data={data}><CartesianGrid vertical={false} strokeDasharray="3 3"/><XAxis dataKey="month" tickLine={false} axisLine={false}/><YAxis tickFormatter={(v) => `R$ ${v} mi`} tickLine={false} axisLine={false} width={60}/><Tooltip formatter={(v) => [`R$ ${Number(v).toLocaleString("pt-BR")} mi`]}/><Line dataKey="planned" stroke="var(--color-planned)" strokeDasharray="5 5" dot={false}/><Line dataKey="actual" stroke="var(--color-actual)" strokeWidth={2.5} dot={false}/></LineChart></ChartContainer>;
}
