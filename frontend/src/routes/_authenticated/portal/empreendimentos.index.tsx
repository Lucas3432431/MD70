import { createFileRoute, Link } from "@tanstack/react-router";
import { PortalHeading } from "@/components/portal/PortalLayout";
import { usePortalData, usePortalDevelopments } from "@/lib/hooks/usePortalData";
import { brl, dateBR, pct } from "@/lib/format";

export const Route = createFileRoute("/_authenticated/portal/empreendimentos/")({
  head: () => ({ meta: [
    { title: "Meus empreendimentos — Portal MD70" }, { name: "description", content: "Acompanhe os empreendimentos dos quais você participa." },
    { property: "og:title", content: "Meus empreendimentos — Portal MD70" }, { property: "og:description", content: "Evolução privada dos seus projetos." },
  ] }), component: Projects,
});

function Projects() {
  const { data: portalData, isPending: loadingPortal } = usePortalData();
  const { data: developments, isPending: loadingDevs } = usePortalDevelopments();

  if (loadingPortal || loadingDevs) {
    return (
      <>
        <PortalHeading eyebrow="Projetos" title="Meus empreendimentos">
          <p>Acompanhe obra, orçamento e resultados dos projetos em que você participa.</p>
        </PortalHeading>
        <p className="text-sm text-muted-foreground">Carregando…</p>
      </>
    );
  }

  if (!portalData || !developments) return null;

  // Build a lookup map: developmentId -> investment summary
  const investmentByDev = new Map(portalData.investments.map((inv) => [inv.developmentId, inv]));

  // Only show developments the investor participates in
  const myDevelopments = developments.filter((d) => investmentByDev.has(d.id));

  return (
    <>
      <PortalHeading eyebrow="Projetos" title="Meus empreendimentos">
        <p>Acompanhe obra, orçamento e resultados dos projetos em que você participa.</p>
      </PortalHeading>
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {myDevelopments.map((d) => {
          const inv = investmentByDev.get(d.id);
          const cdiMultiple = inv && inv.cdiRent > 0 ? Math.round(inv.rent / inv.cdiRent * 100) : null;
          return (
            <Link key={d.id} to="/portal/empreendimentos/$id" params={{ id: d.id }} className="group border bg-card">
              <div className="overflow-hidden">
                {d.image_url ? (
                  <img src={d.image_url} alt={d.name} className="photo aspect-[4/3] w-full object-cover transition-transform duration-700 group-hover:scale-[1.03]" />
                ) : (
                  <div className="photo aspect-[4/3] w-full bg-muted" />
                )}
              </div>
              <div className="p-6">
                <div className="flex justify-between gap-4">
                  <div>
                    <p className="eyebrow">{d.city}</p>
                    <h2 className="mt-2 font-display text-3xl text-primary">{d.name}</h2>
                  </div>
                  <span className="text-xs text-muted-foreground">{d.status}</span>
                </div>
                <div className="mt-6">
                  <div className="mb-2 flex justify-between text-xs">
                    <span>Conclusão</span><span>{d.progress}%</span>
                  </div>
                  <div className="h-1.5 bg-muted">
                    <div className="h-full bg-primary" style={{ width: `${d.progress}%` }} />
                  </div>
                </div>
                <dl className="mt-6 grid grid-cols-3 gap-4 border-t pt-5 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Investimento</dt>
                    <dd className="num mt-1 font-semibold">{brl(inv?.invested ?? 0)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Rentabilidade</dt>
                    {cdiMultiple != null ? (
                      <>
                        <dd className="num mt-1 font-semibold text-positive">{cdiMultiple}% do CDI</dd>
                        <dd className="num text-xs text-muted-foreground">{pct(inv?.rent ?? 0)} bruto</dd>
                      </>
                    ) : (
                      <dd className="num mt-1 font-semibold text-positive">{pct(inv?.rent ?? 0)}</dd>
                    )}
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Previsão</dt>
                    <dd className="mt-1 font-semibold">{dateBR(d.forecast)}</dd>
                  </div>
                </dl>
              </div>
            </Link>
          );
        })}
      </div>
    </>
  );
}
