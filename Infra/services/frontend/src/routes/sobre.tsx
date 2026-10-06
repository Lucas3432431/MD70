import { createFileRoute } from "@tanstack/react-router";
import hero from "@/assets/hero-city.jpg";
import { SiteLayout, PageIntro, InvestCta } from "@/components/site/SiteLayout";

export const Route = createFileRoute("/sobre")({
  head: () => ({
    meta: [
      { title: "Sobre — MD70 Imóveis e Negócios" },
      { name: "description", content: "Quem somos, como trabalhamos e por que acompanhamos cada investimento de perto." },
      { property: "og:title", content: "Sobre a MD70" },
      { property: "og:description", content: "Uma empresa de investimentos imobiliários que trata o dinheiro do investidor com seriedade." },
    ],
  }),
  component: Sobre,
});

const values = [
  { t: "Transparência", d: "O investidor vê os mesmos números que nós: previsto, realizado e estimado." },
  { t: "Controle", d: "Orçamento, cronograma e riscos acompanhados mensalmente em cada projeto." },
  { t: "Proximidade", d: "Atendimento direto com quem decide, sem intermediários." },
];

function Sobre() {
  return (
    <SiteLayout>
      <PageIntro eyebrow="Sobre a MD70" title="Uma empresa que trabalha com negócios reais.">
        A MD70 identifica, estrutura e executa projetos imobiliários e de negócios, reunindo investidores que buscam rentabilidade com segurança e clareza.
      </PageIntro>
      <section className="mx-auto grid max-w-7xl gap-12 px-6 py-24 md:grid-cols-2">
        <img src={hero} alt="Cidade" loading="lazy" width={1600} height={1200} className="photo aspect-[4/5] w-full object-cover" />
        <div className="flex flex-col justify-center">
          <p className="eyebrow">Nossa forma de trabalhar</p>
          <h2 className="mt-4 font-display text-4xl text-primary">Complexidade com a gente. Clareza para você.</h2>
          <p className="mt-6 text-muted-foreground">Cuidamos da análise de mercado, da aquisição, das aprovações, da obra e das vendas. Ao investidor, entregamos o que importa: quanto investiu, quanto vale hoje, como o projeto está e o que mudou.</p>
          <dl className="mt-10 divide-y border-y">
            {values.map((v) => (
              <div key={v.t} className="grid grid-cols-[10rem_1fr] gap-4 py-5">
                <dt className="font-semibold text-primary">{v.t}</dt>
                <dd className="text-muted-foreground">{v.d}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
      <InvestCta />
    </SiteLayout>
  );
}
