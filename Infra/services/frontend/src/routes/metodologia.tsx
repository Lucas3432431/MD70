import { createFileRoute } from "@tanstack/react-router";
import { SiteLayout, PageIntro, InvestCta } from "@/components/site/SiteLayout";

export const Route = createFileRoute("/metodologia")({
  head: () => ({
    meta: [
      { title: "Metodologia — MD70 Imóveis e Negócios" },
      { name: "description", content: "Como a MD70 identifica, analisa, estrutura, executa e acompanha cada oportunidade." },
      { property: "og:title", content: "Metodologia MD70" },
      { property: "og:description", content: "Viabilidade, mercado, custos, riscos e cenários — antes de qualquer investimento." },
    ],
  }),
  component: Metodologia,
});

const sections = [
  { n: "01", t: "Identificação", d: "Buscamos oportunidades por relacionamento com proprietários, corretores e incorporadores, e por análise de dados de cada região.", items: [] as string[] },
  { n: "02", t: "Análise", d: "Cada oportunidade passa por uma avaliação completa antes de ser apresentada a investidores.", items: ["Viabilidade", "Mercado", "Localização", "Custos", "Receita", "Prazo", "Riscos", "Cenários"] },
  { n: "03", t: "Estruturação", d: "Definimos o veículo do investimento, a participação de cada investidor, as garantias e os contratos." , items: [] },
  { n: "04", t: "Execução", d: "Gerimos fornecedores, cronograma e orçamento com reuniões semanais e medições mensais.", items: [] },
  { n: "05", t: "Acompanhamento", d: "O investidor acessa o portal para acompanhar tudo o que acontece no projeto.", items: ["Evolução financeira", "Empreendimentos", "Cronograma", "Orçamento", "Documentos", "Atualizações"] },
];

function Metodologia() {
  return (
    <SiteLayout>
      <PageIntro eyebrow="Metodologia" title="Como analisamos uma oportunidade.">
        Só apresentamos aos investidores negócios que passaram por todas as etapas abaixo.
      </PageIntro>
      <section className="mx-auto max-w-5xl px-6 py-16">
        {sections.map((s) => (
          <article key={s.n} className="grid gap-6 border-b py-14 md:grid-cols-[8rem_1fr]">
            <span className="font-display text-6xl text-primary/25">{s.n}</span>
            <div>
              <h2 className="font-display text-4xl text-primary">{s.t}</h2>
              <p className="mt-4 max-w-2xl text-lg text-muted-foreground">{s.d}</p>
              {s.items.length > 0 && (
                <ul className="mt-8 grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
                  {s.items.map((i) => <li key={i} className="border-t pt-3 text-sm text-primary">{i}</li>)}
                </ul>
              )}
            </div>
          </article>
        ))}
      </section>
      <InvestCta />
    </SiteLayout>
  );
}
