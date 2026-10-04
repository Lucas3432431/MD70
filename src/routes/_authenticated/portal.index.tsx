import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { PortalHeading } from "@/components/portal/PortalLayout";
import { PortfolioChart } from "@/components/portal/PortfolioChart";
import { getPortfolioSeries, summarize } from "@/lib/data/portal";
import { brl, monthLabel, pct, pp } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_authenticated/portal/")({
  head: () => ({ meta: [
    { title: "Visão geral — Portal MD70" }, { name: "description", content: "Resumo privado dos seus investimentos na MD70." },
    { property: "og:title", content: "Visão geral — Portal MD70" }, { property: "og:description", content: "Resumo privado dos seus investimentos." },
  ] }), component: Dashboard,
});

const fullSeries = getPortfolioSeries();
function Dashboard() {
  const [period, setPeriod] = useState<6 | 12 | 24>(12); const [expanded, setExpanded] = useState<string | null>(null);
  const series = fullSeries.slice(-period); const summary = summarize(fullSeries);
  return <div className="lg:mx-auto lg:max-w-xl"><PortalHeading eyebrow="Visão geral" title="Como estão meus investimentos?"><p>Aqui está um resumo da sua carteira na MD70.</p></PortalHeading>
    <section className="grid gap-px bg-border border md:grid-cols-4">
      <div className="bg-primary p-7 text-primary-foreground md:col-span-2"><p className="text-xs uppercase tracking-[0.14em] opacity-60">Patrimônio atualizado</p><p className="num mt-4 font-display text-5xl md:text-6xl">{brl(summary.value)}</p><p className="mt-4 text-sm opacity-70">Total investido: {brl(summary.invested)}</p></div>
      {[["Rentabilidade", pct(summary.rent)], ["CDI de referência", pct(summary.cdiRent)], ["Acima do CDI", pp(summary.excessPp)], ["Resultado acumulado", brl(summary.gain)]].map(([l,v]) => <div key={l} className="bg-card p-7"><p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{l}</p><p className="num mt-4 font-display text-3xl text-primary">{v}</p></div>)}
    </section>
    <section className="mt-8 border bg-card p-5 md:p-8"><div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div><h2 className="font-display text-3xl text-primary">Evolução do patrimônio</h2><div className="mt-2 flex gap-5 text-xs text-muted-foreground"><span><i className="mr-2 inline-block h-0.5 w-5 bg-chart-1"/>Investimento</span><span><i className="mr-2 inline-block h-0.5 w-5 bg-chart-2"/>CDI</span></div></div><div className="flex border">{([6,12,24] as const).map((p) => <button key={p} onClick={() => setPeriod(p)} className={cn("px-3 py-2 text-xs", period === p && "bg-primary text-primary-foreground")}>{p === 24 ? "Todo período" : `${p} meses`}</button>)}</div></div><PortfolioChart data={series}/></section>
    <section className="mt-8 border bg-card p-7 md:p-9"><h2 className="font-display text-3xl text-primary">Como seu investimento evoluiu</h2><div className="mt-8 grid items-center gap-4 sm:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">{[["Valor inicial", brl(summary.invested)], ["CDI de referência", brl(summary.cdiGain)], ["Performance excedente", brl(summary.excessGain)], ["Valor atualizado", brl(summary.value)]].map(([l,v],i) => <div key={l} className="contents"><div className={cn("border-t pt-4", i === 3 && "text-primary")}><p className="text-xs text-muted-foreground">{l}</p><p className="num mt-2 text-xl font-semibold">{v}</p></div>{i < 3 && <span className="hidden text-muted-foreground sm:block">{i === 2 ? "=" : "+"}</span>}</div>)}</div><p className="mt-8 max-w-3xl text-sm text-muted-foreground">Seu investimento valorizou <strong className="text-foreground">{brl(summary.gain)}</strong> no período. Desse resultado, {brl(summary.cdiGain)} correspondem ao CDI de referência e {brl(summary.excessGain)} representam a performance excedente.</p></section>
    <section className="mt-8 border bg-card"><div className="p-7"><h2 className="font-display text-3xl text-primary">Histórico mensal</h2></div><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-sm"><thead><tr className="border-y text-left text-xs text-muted-foreground"><th className="p-4 pl-7">Mês</th><th className="p-4 text-right">Valor investido</th><th className="p-4 text-right">CDI</th><th className="p-4 text-right">Rentabilidade</th><th className="p-4 text-right">Valor atualizado</th><th className="w-12"/></tr></thead><tbody>{fullSeries.slice(-8).reverse().map((m) => <tr key={m.month} className="border-b hover:bg-muted/40 cursor-pointer" onClick={() => setExpanded(expanded === m.month ? null : m.month)}><td className="p-4 pl-7 font-medium">{monthLabel(m.month)}</td><td className="num p-4 text-right">{brl(m.invested)}</td><td className="num p-4 text-right">{pct(m.cdiRate)}</td><td className="num p-4 text-right text-positive">{pct(m.returnRate)}</td><td className="num p-4 text-right font-semibold">{brl(m.value)}</td><td><ChevronDown className={cn("size-4 transition-transform", expanded === m.month && "rotate-180")}/></td></tr>)}</tbody></table></div></section>
  </div>;
}
