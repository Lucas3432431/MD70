import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteLayout, PageIntro } from "@/components/site/SiteLayout";

export const Route = createFileRoute("/contato")({
  head: () => ({
    meta: [
      { title: "Contato — MD70 Imóveis e Negócios" },
      { name: "description", content: "Entre em contato com a MD70 pelo formulário de interesse." },
      { property: "og:title", content: "Contato MD70" },
      { property: "og:description", content: "Converse diretamente com a equipe da MD70." },
    ],
  }),
  component: Contato,
});

function Contato() {
  return (
    <SiteLayout>
      <PageIntro eyebrow="Contato" title="Fale com a gente.">
        Atendimento direto com a equipe responsável pelos projetos.
      </PageIntro>
      <section className="mx-auto max-w-7xl px-6 py-20">
        <p className="max-w-2xl text-muted-foreground">Quer conhecer as oportunidades? Deixe seus dados para que a equipe entre em contato.</p>
        <Link to="/quero-investir" className="mt-7 inline-block border border-primary px-6 py-3 text-sm font-semibold text-primary transition-colors hover:bg-primary hover:text-primary-foreground">Preencher formulário</Link>
      </section>
    </SiteLayout>
  );
}
