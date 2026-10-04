import { createFileRoute, Link } from "@tanstack/react-router";
import hero from "@/assets/hero-city.jpg";
import { SiteLayout, InvestCta } from "@/components/site/SiteLayout";
import { Button } from "@/components/ui/button";
import { steps } from "@/lib/data/site";
import { developments } from "@/lib/data/developments";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "MD70 Imóveis e Negócios — Investimentos em negócios reais" },
      { name: "description", content: "Identificamos, estruturamos e acompanhamos oportunidades em negócios reais para nossos investidores, com transparência em cada etapa." },
      { property: "og:title", content: "MD70 Imóveis e Negócios" },
      { property: "og:description", content: "Investimentos em negócios reais. Acompanhamento de verdade." },
    ],
  }),
  component: Home,
});

function Home() {
  return (
    <SiteLayout overlay>
      <section className="relative min-h-[92vh] overflow-hidden bg-ink text-primary-foreground">
        <img src={hero} alt="Vista aérea da cidade em preto e branco" width={1600} height={1200} className="photo absolute inset-0 h-full w-full object-cover opacity-70" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink via-ink/40 to-ink/30" />
        <div className="relative mx-auto flex min-h-[92vh] max-w-7xl flex-col justify-end px-6 pb-20 pt-32">
          <p className="eyebrow !text-primary-foreground/70 fade-up">MD70 Imóveis e Negócios</p>
          <h1 className="mt-6 max-w-4xl font-display text-5xl leading-[1] md:text-8xl fade-up">
            Investimentos em negócios reais.<br /><em className="opacity-80">Acompanhamento de verdade.</em>
          </h1>
          <p className="mt-8 max-w-xl text-lg opacity-80 fade-up">
            Identificamos, estruturamos e acompanhamos oportunidades para nossos investidores, com transparência em cada etapa.
          </p>
          <div className="mt-10 flex flex-wrap gap-3 fade-up">
            <Button asChild variant="hero" size="lg"><Link to="/sobre">Conheça a MD70</Link></Button>
            <Button asChild variant="heroOutline" size="lg"><Link to="/quero-investir">Quero investir</Link></Button>
          </div>
          <div className="mt-16 h-px w-32 bg-primary-foreground/50" />
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-24">
        <div className="grid gap-10 md:grid-cols-[1fr_2fr]">
          <div>
            <p className="eyebrow">Como funciona</p>
            <h2 className="mt-4 font-display text-4xl text-primary md:text-5xl">Cinco etapas, do terreno ao resultado.</h2>
          </div>
          <ol className="divide-y border-y">
            {steps.map((s) => (
              <li key={s.n} className="grid grid-cols-[3rem_1fr] gap-4 py-6 md:grid-cols-[4rem_1fr_1.4fr]">
                <span className="num text-sm text-muted-foreground">{s.n}</span>
                <span className="font-semibold text-primary">{s.title}</span>
                <span className="col-start-2 text-muted-foreground md:col-start-auto">{s.text}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="border-t bg-card">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <p className="mb-8 border-l-2 border-warning pl-4 text-sm text-muted-foreground">Projetos ilustrativos para apresentação. Os empreendimentos e resultados exibidos não representam ofertas reais da MD70.</p>
          <div className="flex items-end justify-between gap-6">
            <div>
              <p className="eyebrow">Empreendimentos</p>
              <h2 className="mt-4 font-display text-4xl text-primary md:text-5xl">Exemplos de acompanhamento.</h2>
            </div>
            <Link to="/empreendimentos" className="hidden text-sm underline underline-offset-4 md:block">Ver todos</Link>
          </div>
          <div className="mt-12 grid gap-8 md:grid-cols-3">
            {developments.map((d) => (
              <Link key={d.id} to="/empreendimentos" className="group">
                <div className="overflow-hidden">
                  <img src={d.image} alt={d.name} loading="lazy" width={1200} height={912} className="photo aspect-[4/3] w-full object-cover transition-transform duration-700 group-hover:scale-[1.03]" />
                </div>
                <p className="eyebrow mt-5">{d.category} · {d.city}</p>
                <h3 className="mt-2 font-display text-2xl text-primary">{d.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{d.status}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-24">
        <div className="grid gap-12 md:grid-cols-2 md:items-center">
          <div>
            <p className="eyebrow">Portal do investidor</p>
            <h2 className="mt-4 font-display text-4xl text-primary md:text-5xl">Acompanhe onde seu dinheiro está.</h2>
            <p className="mt-6 text-lg text-muted-foreground">Cada investidor tem acesso a um portal privado com a evolução do patrimônio, a comparação com o CDI, o andamento das obras, o orçamento e todos os documentos em um único lugar.</p>
          </div>
          <ul className="divide-y border-y text-primary">
            {["Veja como o projeto está evoluindo.", "Entenda o resultado do seu investimento.", "Tenha acesso aos documentos em um único lugar.", "Saiba o que mudou desde o último mês."].map((t) => (
              <li key={t} className="py-5 font-display text-2xl">{t}</li>
            ))}
          </ul>
        </div>
      </section>
      <InvestCta />
    </SiteLayout>
  );
}
