import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { PortalHeading } from "@/components/portal/PortalLayout";
import { usePortalData, usePortalDevelopments } from "@/lib/hooks/usePortalData";
import { brl, dateBR, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_authenticated/portal/investimentos")({ head: () => ({ meta: [
  { title: "Meus investimentos — Portal MD70" }, { name: "description", content: "Seus investimentos e movimentações na MD70." },
  { property: "og:title", content: "Meus investimentos — Portal MD70" }, { property: "og:description", content: "Visão privada da sua carteira." },
] }), component: Investments });

function Investments() {
  const [open, setOpen] = useState<string | null>(null);
  const { data: portalData, isPending: loadingPortal } = usePortalData();
  const { data: developments, isPending: loadingDevs } = usePortalDevelopments();

  if (loadingPortal || loadingDevs) {
    return (
      <div className="lg:w-1/2 lg:mx-auto">
        <PortalHeading eyebrow="Carteira" title="Meus investimentos">
          <p>Valores, rentabilidade e histórico financeiro por projeto.</p>
        </PortalHeading>
        <p className="text-sm text-muted-foreground">Carregando…</p>
      </div>
    );
  }

  if (!portalData || !developments) return null;

  const devById = new Map(developments.map((d) => [d.id, d]));

  return (
    <div className="lg:w-1/2 lg:mx-auto">
      <PortalHeading eyebrow="Carteira" title="Meus investimentos">
        <p>Valores, rentabilidade e histórico financeiro por projeto.</p>
      </PortalHeading>
      <div className="space-y-4">
        {portalData.investments.map((inv) => {
          const dev = devById.get(inv.developmentId);
          return (
            <article key={inv.id} className="border bg-card">
              <button
                onClick={() => setOpen(open === inv.id ? null : inv.id)}
                className="grid w-full gap-5 p-5 text-left sm:grid-cols-[5rem_1fr_repeat(3,minmax(7rem,auto))_2rem] sm:items-center"
              >
                {dev?.image_url ? (
                  <img src={dev.image_url} alt="" className="photo aspect-square w-20 object-cover" />
                ) : (
                  <div className="photo aspect-square w-20 bg-muted" />
                )}
                <div>
                  <h2 className="font-display text-2xl text-primary">{dev?.name ?? inv.developmentId}</h2>
                  <p className="text-xs text-muted-foreground">{dev?.city}</p>
                </div>
                <Metric l="Investido" v={brl(inv.invested)} />
                <Metric l="Atualizado" v={brl(inv.value)} />
                <Metric l="Rentabilidade" v={pct(inv.rent)} positive />
                <ChevronDown className={cn("size-4 transition-transform", open === inv.id && "rotate-180")} />
              </button>
              {open === inv.id && (
                <div className="border-t p-6">
                  <h3 className="font-semibold text-primary">Histórico mensal</h3>
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[500px] text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs text-muted-foreground">
                          <th className="p-3">Mês</th>
                          <th className="p-3 text-right">Investido</th>
                          <th className="p-3 text-right">Valor</th>
                          <th className="p-3 text-right">Rentabilidade</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inv.series.slice(-6).reverse().map((s) => (
                          <tr key={s.month} className="border-b">
                            <td className="p-3">{s.month}</td>
                            <td className="num p-3 text-right">{brl(s.invested)}</td>
                            <td className="num p-3 text-right">{brl(s.value)}</td>
                            <td className="num p-3 text-right text-positive">{pct(s.returnRate)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {dev && (
                    <Link
                      to="/portal/empreendimentos/$id"
                      params={{ id: dev.id }}
                      className="mt-6 inline-block text-sm font-semibold text-primary underline underline-offset-4"
                    >
                      Ver empreendimento
                    </Link>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function Metric({ l, v, positive }: { l: string; v: string; positive?: boolean }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{l}</p>
      <p className={cn("num mt-1 font-semibold", positive && "text-positive")}>{v}</p>
    </div>
  );
}
