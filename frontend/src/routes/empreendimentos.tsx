import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteLayout, PageIntro, InvestCta } from "@/components/site/SiteLayout";
import { developments } from "@/lib/data/developments";

export const Route = createFileRoute("/empreendimentos")({
  head: () => ({
    meta: [
      { title: "Empreendimentos — MD70 Imóveis e Negócios" },
      { name: "description", content: "Conheça os empreendimentos residenciais e corporativos em que a MD70 trabalha." },
      { property: "og:title", content: "Empreendimentos MD70" },
      { property: "og:description", content: "Projetos em desenvolvimento, em obra e em captação." },
    ],
  }),
  component: Empreendimentos,
});

function Empreendimentos() {
  return (
    <SiteLayout>
      <PageIntro eyebrow="Empreendimentos" title="Como acompanhamos cada projeto.">
        Conheça exemplos ilustrativos da apresentação de empreendimentos aos investidores.
      </PageIntro>
      <div className="mx-auto max-w-7xl px-6 pt-10"><p className="border-l-2 border-warning pl-4 text-sm text-muted-foreground">Projetos ilustrativos para apresentação. Estes empreendimentos não representam ofertas reais da MD70.</p></div>
      <section className="mx-auto max-w-7xl px-6 py-20 space-y-20">
        {developments.map((d, i) => (
          <article key={d.id} className={`grid gap-10 md:grid-cols-2 md:items-center ${i % 2 ? "md:[&>*:first-child]:order-2" : ""}`}>
            <img src={d.image} alt={d.name} loading="lazy" width={1200} height={912} className="photo aspect-[4/3] w-full object-cover" />
            <div>
              <p className="eyebrow">{d.category}</p>
              <h2 className="mt-3 font-display text-5xl text-primary">{d.name}</h2>
              <p className="mt-2 text-muted-foreground">{d.city}</p>
              <p className="mt-6 text-lg">{d.summary}</p>
              <div className="mt-6 inline-flex items-center gap-2 border px-3 py-1 text-xs uppercase tracking-[0.14em] text-primary">
                <span className="h-1.5 w-1.5 rounded-full bg-positive" />{d.status}
              </div>
              <div className="mt-8">
                <Link to="/quero-investir" className="text-sm font-semibold text-primary underline underline-offset-4">Conhecer projeto</Link>
              </div>
            </div>
          </article>
        ))}
      </section>
      <InvestCta />
    </SiteLayout>
  );
}
